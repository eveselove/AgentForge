use axum::{
    extract::{Path, Query, State},
    http::StatusCode,
    response::{Html, IntoResponse, Json},
    routing::{get, patch, post},
    Router,
};
use chrono::Utc;
use rusqlite::{params, Connection};
use serde::{Deserialize, Serialize};
use std::sync::{Arc, Mutex};
use tower_http::cors::CorsLayer;
use tracing::{info, warn};

// ═══════════════════════════════════════════════════════
//  Types
// ═══════════════════════════════════════════════════════

#[derive(Clone)]
struct AppState {
    db: Arc<Mutex<Connection>>,
    data_dir: String,
}

#[derive(Debug, Serialize, Deserialize)]
struct Task {
    task_id: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    title: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    last_step: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    last_updated: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    parent_task_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    team_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    manager_agent: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    created_at: Option<String>,
}

#[derive(Debug, Deserialize)]
struct CreateTask {
    title: String,
    #[serde(default)]
    description: Option<String>,
    #[serde(default)]
    repo: Option<String>,
    #[serde(default)]
    parent_id: Option<String>,
    #[serde(default)]
    priority: Option<String>,
}

#[derive(Debug, Deserialize)]
struct UpdateTask {
    #[serde(default)]
    status: Option<String>,
    #[serde(default)]
    last_step: Option<String>,
}

#[derive(Debug, Serialize, Deserialize)]
struct Agent {
    agent_id: String,
    name: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    role: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    status: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    registered_at: Option<String>,
}

#[derive(Debug, Deserialize)]
struct RegisterAgent {
    name: String,
    #[serde(default)]
    role: Option<String>,
}

#[derive(Debug, Serialize, Deserialize)]
struct Knowledge {
    id: i64,
    #[serde(skip_serializing_if = "Option::is_none")]
    agent: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    task_id: Option<String>,
    key: String,
    value: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    created_at: Option<String>,
}

#[derive(Debug, Deserialize)]
struct SaveKnowledge {
    key: String,
    value: String,
    #[serde(default)]
    agent: Option<String>,
    #[serde(default)]
    task_id: Option<String>,
}

#[derive(Debug, Serialize)]
struct BlackboardEntry {
    agent: String,
    message: String,
    team_id: Option<String>,
    task_id: Option<String>,
    created_at: String,
}

#[derive(Debug, Deserialize)]
struct PostActivity {
    agent: String,
    message: String,
    #[serde(default)]
    team_id: Option<String>,
    #[serde(default)]
    task_id: Option<String>,
}

#[derive(Debug, Deserialize)]
struct SearchQuery {
    #[serde(default)]
    q: Option<String>,
    #[serde(default)]
    status: Option<String>,
    #[serde(default)]
    limit: Option<usize>,
}

#[derive(Debug, Serialize)]
struct HealthResponse {
    status: String,
    version: String,
    uptime_secs: u64,
    tasks_total: i64,
    agents_total: i64,
    db_path: String,
}

// ═══════════════════════════════════════════════════════
//  Database init
// ═══════════════════════════════════════════════════════

fn init_db(conn: &Connection) {
    conn.execute_batch("PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA foreign_keys=ON; PRAGMA busy_timeout=30000;").unwrap();

    conn.execute_batch(
        "
        CREATE TABLE IF NOT EXISTS checkpoints (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id    TEXT NOT NULL,
            step       TEXT NOT NULL,
            data_json  TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_checkpoints_task_created ON checkpoints (task_id, created_at DESC);

        CREATE TABLE IF NOT EXISTS tasks (
            task_id        TEXT PRIMARY KEY,
            created_at     TEXT NOT NULL DEFAULT (datetime('now')),
            last_step      TEXT,
            last_updated   TEXT,
            parent_task_id TEXT,
            team_id        TEXT,
            subtasks_json  TEXT,
            team_json      TEXT,
            manager_agent  TEXT,
            depends_on_json TEXT,
            retry_count    INTEGER DEFAULT 0,
            tokens_used    INTEGER DEFAULT 0,
            cost_usd       REAL DEFAULT 0.0
        );
        CREATE INDEX IF NOT EXISTS idx_tasks_parent ON tasks (parent_task_id);
        CREATE INDEX IF NOT EXISTS idx_tasks_team ON tasks (team_id);

        CREATE TABLE IF NOT EXISTS agent_teams (
            team_id       TEXT PRIMARY KEY,
            manager_agent TEXT,
            config_json   TEXT,
            status        TEXT DEFAULT 'active',
            created_at    TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at    TEXT
        );

        CREATE TABLE IF NOT EXISTS agents (
            agent_id      TEXT PRIMARY KEY,
            name          TEXT NOT NULL,
            role          TEXT DEFAULT 'worker',
            status        TEXT DEFAULT 'active',
            registered_at TEXT NOT NULL DEFAULT (datetime('now')),
            last_seen     TEXT
        );

        CREATE TABLE IF NOT EXISTS blackboard_activity (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            agent      TEXT NOT NULL,
            team_id    TEXT,
            task_id    TEXT,
            message    TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_bb_team ON blackboard_activity (team_id, created_at DESC);

        CREATE VIRTUAL TABLE IF NOT EXISTS tasks_fts USING fts5(
            task_id UNINDEXED, title, content, tags, outcome,
            tokenize = 'unicode61 remove_diacritics 2'
        );
        ",
    )
    .unwrap();

    info!("✅ Database initialized");
}

// ═══════════════════════════════════════════════════════
//  Handlers
// ═══════════════════════════════════════════════════════

async fn health(State(state): State<AppState>) -> Json<HealthResponse> {
    let db = state.db.lock().unwrap();
    let tasks: i64 = db
        .query_row("SELECT COUNT(*) FROM tasks", [], |r| r.get(0))
        .unwrap_or(0);
    let agents: i64 = db
        .query_row("SELECT COUNT(*) FROM agents", [], |r| r.get(0))
        .unwrap_or(0);

    Json(HealthResponse {
        status: "ok".into(),
        version: env!("CARGO_PKG_VERSION").into(),
        uptime_secs: 0, // TODO: track start time
        tasks_total: tasks,
        agents_total: agents,
        db_path: state.data_dir.clone(),
    })
}

// ── Tasks ─────────────────────────────────────────────

async fn list_tasks(
    State(state): State<AppState>,
    Query(q): Query<SearchQuery>,
) -> Json<Vec<Task>> {
    let db = state.db.lock().unwrap();
    let limit = q.limit.unwrap_or(100);

    let sql = if let Some(ref status) = q.status {
        format!(
            "SELECT t.task_id, t.last_step, t.last_updated, t.parent_task_id, t.team_id, t.manager_agent, t.created_at,
                    (SELECT json_extract(c.data_json, '$.title') FROM checkpoints c WHERE c.task_id = t.task_id ORDER BY c.created_at DESC LIMIT 1) as title
             FROM tasks t WHERE t.last_step = ?1 ORDER BY t.last_updated DESC LIMIT {}",
            limit
        )
    } else {
        format!(
            "SELECT t.task_id, t.last_step, t.last_updated, t.parent_task_id, t.team_id, t.manager_agent, t.created_at,
                    (SELECT json_extract(c.data_json, '$.title') FROM checkpoints c WHERE c.task_id = t.task_id ORDER BY c.created_at DESC LIMIT 1) as title
             FROM tasks t ORDER BY t.last_updated DESC LIMIT {}",
            limit
        )
    };

    let mut stmt = db.prepare(&sql).unwrap();
    let params_vec: Vec<&dyn rusqlite::types::ToSql> = if let Some(ref s) = q.status {
        vec![s]
    } else {
        vec![]
    };

    let rows = stmt
        .query_map(params_vec.as_slice(), |row| {
            Ok(Task {
                task_id: row.get(0)?,
                last_step: row.get(1)?,
                last_updated: row.get(2)?,
                parent_task_id: row.get(3)?,
                team_id: row.get(4)?,
                manager_agent: row.get(5)?,
                created_at: row.get(6)?,
                title: row.get(7)?,
            })
        })
        .unwrap()
        .filter_map(|r| r.ok())
        .collect();

    Json(rows)
}

async fn get_task(State(state): State<AppState>, Path(id): Path<String>) -> impl IntoResponse {
    let db = state.db.lock().unwrap();
    let result = db.query_row(
        "SELECT t.task_id, t.last_step, t.last_updated, t.parent_task_id, t.team_id, t.manager_agent, t.created_at,
                (SELECT json_extract(c.data_json, '$.title') FROM checkpoints c WHERE c.task_id = t.task_id ORDER BY c.created_at DESC LIMIT 1) as title
         FROM tasks t WHERE t.task_id = ?1",
        params![id],
        |row| {
            Ok(Task {
                task_id: row.get(0)?,
                last_step: row.get(1)?,
                last_updated: row.get(2)?,
                parent_task_id: row.get(3)?,
                team_id: row.get(4)?,
                manager_agent: row.get(5)?,
                created_at: row.get(6)?,
                title: row.get(7)?,
            })
        },
    );

    match result {
        Ok(task) => Json(serde_json::to_value(task).unwrap()).into_response(),
        Err(_) => (StatusCode::NOT_FOUND, Json(serde_json::json!({"error": "task not found"}))).into_response(),
    }
}

async fn create_task(
    State(state): State<AppState>,
    Json(payload): Json<CreateTask>,
) -> impl IntoResponse {
    let db = state.db.lock().unwrap();
    let task_id = format!("task-{}", uuid::Uuid::new_v4().to_string()[..12].to_string());
    let now = Utc::now().to_rfc3339();

    let data = serde_json::json!({
        "title": payload.title,
        "description": payload.description,
        "repo": payload.repo,
        "priority": payload.priority.unwrap_or("medium".into()),
        "created_at": now,
    });

    db.execute(
        "INSERT INTO tasks (task_id, created_at, last_step, last_updated, parent_task_id) VALUES (?1, ?2, 'dispatch', ?2, ?3)",
        params![task_id, now, payload.parent_id],
    ).unwrap();

    db.execute(
        "INSERT INTO checkpoints (task_id, step, data_json, created_at) VALUES (?1, 'dispatch', ?2, ?3)",
        params![task_id, data.to_string(), now],
    ).unwrap();

    if let Some(ref parent) = payload.parent_id {
        // Add to parent's subtasks
        let existing: String = db
            .query_row("SELECT COALESCE(subtasks_json, '[]') FROM tasks WHERE task_id = ?1", params![parent], |r| r.get(0))
            .unwrap_or_else(|_| "[]".into());
        let mut subs: Vec<String> = serde_json::from_str(&existing).unwrap_or_default();
        subs.push(task_id.clone());
        db.execute(
            "UPDATE tasks SET subtasks_json = ?1 WHERE task_id = ?2",
            params![serde_json::to_string(&subs).unwrap(), parent],
        ).unwrap();
    }

    info!("📝 Task created: {} — {}", task_id, payload.title);

    (
        StatusCode::CREATED,
        Json(serde_json::json!({
            "ok": true,
            "id": task_id,
            "title": payload.title,
        })),
    )
}

async fn update_task(
    State(state): State<AppState>,
    Path(id): Path<String>,
    Json(payload): Json<UpdateTask>,
) -> impl IntoResponse {
    let db = state.db.lock().unwrap();
    let now = Utc::now().to_rfc3339();

    let step = payload.last_step.or(payload.status).unwrap_or("dispatch".into());

    db.execute(
        "UPDATE tasks SET last_step = ?1, last_updated = ?2 WHERE task_id = ?3",
        params![step, now, id],
    ).unwrap();

    db.execute(
        "INSERT INTO checkpoints (task_id, step, data_json, created_at) VALUES (?1, ?2, ?3, ?4)",
        params![id, step, serde_json::json!({"updated_via": "api"}).to_string(), now],
    ).unwrap();

    info!("📝 Task updated: {} → {}", id, step);
    Json(serde_json::json!({"ok": true, "task_id": id, "step": step}))
}

// ── Agents ────────────────────────────────────────────

async fn list_agents(State(state): State<AppState>) -> Json<Vec<Agent>> {
    let db = state.db.lock().unwrap();
    let mut stmt = db
        .prepare("SELECT agent_id, name, role, status, registered_at FROM agents ORDER BY registered_at DESC")
        .unwrap();
    let rows = stmt
        .query_map([], |row| {
            Ok(Agent {
                agent_id: row.get(0)?,
                name: row.get(1)?,
                role: row.get(2)?,
                status: row.get(3)?,
                registered_at: row.get(4)?,
            })
        })
        .unwrap()
        .filter_map(|r| r.ok())
        .collect();
    Json(rows)
}

async fn register_agent(
    State(state): State<AppState>,
    Json(payload): Json<RegisterAgent>,
) -> impl IntoResponse {
    let db = state.db.lock().unwrap();
    let agent_id = format!("agent-{}", uuid::Uuid::new_v4().to_string()[..8].to_string());
    let now = Utc::now().to_rfc3339();

    db.execute(
        "INSERT OR REPLACE INTO agents (agent_id, name, role, status, registered_at, last_seen) VALUES (?1, ?2, ?3, 'active', ?4, ?4)",
        params![agent_id, payload.name, payload.role.unwrap_or("worker".into()), now],
    ).unwrap();

    info!("🤖 Agent registered: {} ({})", payload.name, agent_id);

    (
        StatusCode::CREATED,
        Json(serde_json::json!({
            "ok": true,
            "agent_id": agent_id,
            "name": payload.name,
        })),
    )
}

// ── Blackboard ────────────────────────────────────────

async fn post_activity(
    State(state): State<AppState>,
    Json(payload): Json<PostActivity>,
) -> impl IntoResponse {
    let db = state.db.lock().unwrap();
    let now = Utc::now().to_rfc3339();

    db.execute(
        "INSERT INTO blackboard_activity (agent, team_id, task_id, message, created_at) VALUES (?1, ?2, ?3, ?4, ?5)",
        params![payload.agent, payload.team_id, payload.task_id, payload.message, now],
    ).unwrap();

    // Update agent last_seen
    db.execute(
        "UPDATE agents SET last_seen = ?1 WHERE name = ?2 OR agent_id = ?2",
        params![now, payload.agent],
    ).ok();

    info!("📢 [{}] {}", payload.agent, payload.message);
    Json(serde_json::json!({"ok": true}))
}

async fn get_blackboard_feed(
    State(state): State<AppState>,
    Query(q): Query<SearchQuery>,
) -> Json<Vec<BlackboardEntry>> {
    let db = state.db.lock().unwrap();
    let limit = q.limit.unwrap_or(50);

    let mut stmt = db
        .prepare(&format!(
            "SELECT agent, message, team_id, task_id, created_at FROM blackboard_activity ORDER BY created_at DESC LIMIT {}",
            limit
        ))
        .unwrap();

    let rows = stmt
        .query_map([], |row| {
            Ok(BlackboardEntry {
                agent: row.get(0)?,
                message: row.get(1)?,
                team_id: row.get(2)?,
                task_id: row.get(3)?,
                created_at: row.get(4)?,
            })
        })
        .unwrap()
        .filter_map(|r| r.ok())
        .collect();

    Json(rows)
}

// ── Knowledge ─────────────────────────────────────────

async fn search_knowledge(
    State(state): State<AppState>,
    Query(q): Query<SearchQuery>,
) -> Json<Vec<Knowledge>> {
    let db = state.db.lock().unwrap();
    let limit = q.limit.unwrap_or(20);

    // Try tasks.db knowledge table — but we use same DB for simplicity
    // In production, use separate connection to tasks.db
    let sql = format!(
        "SELECT id, agent, task_id, key, value, created_at FROM knowledge ORDER BY created_at DESC LIMIT {}",
        limit
    );

    let result = db.prepare(&sql);
    match result {
        Ok(mut stmt) => {
            let rows = stmt
                .query_map([], |row| {
                    Ok(Knowledge {
                        id: row.get(0)?,
                        agent: row.get(1)?,
                        task_id: row.get(2)?,
                        key: row.get(3)?,
                        value: row.get(4)?,
                        created_at: row.get(5)?,
                    })
                })
                .unwrap()
                .filter_map(|r| r.ok())
                .collect();
            Json(rows)
        }
        Err(_) => Json(vec![]),
    }
}

async fn save_knowledge_handler(
    State(state): State<AppState>,
    Json(payload): Json<SaveKnowledge>,
) -> impl IntoResponse {
    let db = state.db.lock().unwrap();
    let now = Utc::now().to_rfc3339();

    // Ensure knowledge table exists
    db.execute_batch(
        "CREATE TABLE IF NOT EXISTS knowledge (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent TEXT, task_id TEXT,
            key TEXT NOT NULL, value TEXT NOT NULL,
            embedding_hash TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )"
    ).ok();

    db.execute(
        "INSERT INTO knowledge (agent, task_id, key, value, created_at) VALUES (?1, ?2, ?3, ?4, ?5)",
        params![payload.agent, payload.task_id, payload.key, payload.value, now],
    ).unwrap();

    info!("🧠 Knowledge saved: {}", payload.key);
    (StatusCode::CREATED, Json(serde_json::json!({"ok": true, "key": payload.key})))
}

// ── Dashboard ─────────────────────────────────────────

async fn dashboard(State(state): State<AppState>) -> Html<String> {
    let db = state.db.lock().unwrap();

    let tasks_total: i64 = db.query_row("SELECT COUNT(*) FROM tasks", [], |r| r.get(0)).unwrap_or(0);
    let tasks_active: i64 = db.query_row(
        "SELECT COUNT(*) FROM tasks WHERE last_step NOT IN ('done','failed') OR last_step IS NULL", [], |r| r.get(0)
    ).unwrap_or(0);
    let agents_total: i64 = db.query_row("SELECT COUNT(*) FROM agents", [], |r| r.get(0)).unwrap_or(0);
    let bb_count: i64 = db.query_row("SELECT COUNT(*) FROM blackboard_activity", [], |r| r.get(0)).unwrap_or(0);

    // Recent tasks
    let mut stmt = db.prepare(
        "SELECT t.task_id, t.last_step, t.last_updated,
                (SELECT json_extract(c.data_json, '$.title') FROM checkpoints c WHERE c.task_id = t.task_id ORDER BY c.created_at DESC LIMIT 1) as title
         FROM tasks t ORDER BY t.last_updated DESC LIMIT 15"
    ).unwrap();
    let tasks: Vec<(String, String, String, String)> = stmt.query_map([], |row| {
        Ok((
            row.get::<_, String>(0).unwrap_or_default(),
            row.get::<_, String>(1).unwrap_or_else(|_| "—".into()),
            row.get::<_, String>(2).unwrap_or_else(|_| "—".into()),
            row.get::<_, String>(3).unwrap_or_else(|_| "Untitled".into()),
        ))
    }).unwrap().filter_map(|r| r.ok()).collect();

    let tasks_html: String = tasks.iter().map(|(id, step, updated, title)| {
        let badge = match step.as_str() {
            "done" => r#"<span class="badge done">done</span>"#,
            "failed" => r#"<span class="badge failed">failed</span>"#,
            "dispatch" => r#"<span class="badge dispatch">dispatch</span>"#,
            _ => &format!(r#"<span class="badge active">{}</span>"#, step),
        };
        format!(r#"<tr><td class="id">{}</td><td>{}</td><td>{}</td><td class="time">{}</td></tr>"#,
            &id[..id.len().min(16)], title, badge, &updated[..updated.len().min(19)])
    }).collect();

    // Recent agents
    let mut stmt2 = db.prepare("SELECT agent_id, name, role, status, registered_at FROM agents ORDER BY registered_at DESC LIMIT 10").unwrap();
    let agents: Vec<(String, String, String, String)> = stmt2.query_map([], |row| {
        Ok((
            row.get::<_, String>(0).unwrap_or_default(),
            row.get::<_, String>(1).unwrap_or_default(),
            row.get::<_, String>(2).unwrap_or_else(|_| "worker".into()),
            row.get::<_, String>(3).unwrap_or_else(|_| "active".into()),
        ))
    }).unwrap().filter_map(|r| r.ok()).collect();

    let agents_html: String = agents.iter().map(|(id, name, role, status)| {
        let badge = if status == "active" {
            r#"<span class="badge done">active</span>"#
        } else {
            r#"<span class="badge failed">offline</span>"#
        };
        format!(r#"<tr><td class="id">{}</td><td>{}</td><td>{}</td><td>{}</td></tr>"#,
            &id[..id.len().min(14)], name, role, badge)
    }).collect();

    Html(format!(r##"<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AgentForge Dashboard</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#0a0e17;color:#c9d1d9;font-family:'Inter','SF Pro',system-ui,sans-serif;min-height:100vh}}
.header{{background:linear-gradient(135deg,#161b22 0%,#0d1117 100%);border-bottom:1px solid #21262d;padding:20px 32px;display:flex;align-items:center;gap:16px}}
.header h1{{font-size:24px;font-weight:700;background:linear-gradient(90deg,#58a6ff,#bc8cff);-webkit-background-clip:text;-webkit-text-fill-color:transparent}}
.header .ver{{color:#484f58;font-size:13px}}
.stats{{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;padding:24px 32px}}
.stat{{background:#161b22;border:1px solid #21262d;border-radius:12px;padding:20px;text-align:center}}
.stat .num{{font-size:36px;font-weight:800;background:linear-gradient(135deg,#58a6ff,#3fb950);-webkit-background-clip:text;-webkit-text-fill-color:transparent}}
.stat .label{{color:#8b949e;font-size:13px;margin-top:4px;text-transform:uppercase;letter-spacing:1px}}
.panels{{display:grid;grid-template-columns:1fr 1fr;gap:16px;padding:0 32px 32px}}
.panel{{background:#161b22;border:1px solid #21262d;border-radius:12px;overflow:hidden}}
.panel h2{{padding:16px 20px;font-size:15px;color:#58a6ff;border-bottom:1px solid #21262d;font-weight:600}}
table{{width:100%;border-collapse:collapse}}
tr{{border-bottom:1px solid #21262d}}
tr:hover{{background:#1c2128}}
td{{padding:10px 16px;font-size:13px}}
.id{{color:#8b949e;font-family:monospace;font-size:12px}}
.time{{color:#484f58;font-size:12px}}
.badge{{display:inline-block;padding:2px 10px;border-radius:12px;font-size:11px;font-weight:600}}
.badge.done{{background:#0d2818;color:#3fb950}}
.badge.failed{{background:#2d1115;color:#f85149}}
.badge.dispatch{{background:#1c1d2e;color:#bc8cff}}
.badge.active{{background:#0c2d3e;color:#58a6ff}}
.footer{{text-align:center;padding:16px;color:#484f58;font-size:12px}}
@media(max-width:768px){{.stats{{grid-template-columns:repeat(2,1fr)}} .panels{{grid-template-columns:1fr}}}}
</style>
</head>
<body>
<div class="header">
  <h1>⚡ AgentForge</h1>
  <span class="ver">v{version} — erbox</span>
</div>
<div class="stats">
  <div class="stat"><div class="num">{tasks_total}</div><div class="label">Tasks Total</div></div>
  <div class="stat"><div class="num">{tasks_active}</div><div class="label">Active</div></div>
  <div class="stat"><div class="num">{agents_total}</div><div class="label">Agents</div></div>
  <div class="stat"><div class="num">{bb_count}</div><div class="label">Blackboard</div></div>
</div>
<div class="panels">
  <div class="panel">
    <h2>📋 Recent Tasks</h2>
    <table>{tasks_html}</table>
  </div>
  <div class="panel">
    <h2>🤖 Agents</h2>
    <table>{agents_html}</table>
  </div>
</div>
<div class="footer">AgentForge Gateway — Autonomous Agent Orchestration</div>
</body>
</html>"##,
        version = env!("CARGO_PKG_VERSION"),
        tasks_total = tasks_total,
        tasks_active = tasks_active,
        agents_total = agents_total,
        bb_count = bb_count,
        tasks_html = tasks_html,
        agents_html = agents_html,
    ))
}

// ═══════════════════════════════════════════════════════
//  Main
// ═══════════════════════════════════════════════════════

#[tokio::main]
async fn main() {
    dotenv::dotenv().ok();

    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "info".into()),
        )
        .init();

    let data_dir = std::env::var("AGENTFORGE_DATA")
        .unwrap_or_else(|_| {
            let home = std::env::var("HOME").unwrap_or_else(|_| ".".into());
            format!("{}/agentforge/data", home)
        });
    std::fs::create_dir_all(&data_dir).ok();

    let db_path = format!("{}/task_checkpoints.db", data_dir);
    info!("📂 Database: {}", db_path);

    let conn = Connection::open(&db_path).expect("Failed to open SQLite");
    init_db(&conn);

    let state = AppState {
        db: Arc::new(Mutex::new(conn)),
        data_dir: data_dir.clone(),
    };

    let app = Router::new()
        // Dashboard
        .route("/", get(dashboard))
        // Health
        .route("/api/health", get(health))
        // Tasks
        .route("/api/tasks", get(list_tasks).post(create_task))
        .route("/api/tasks/{id}", get(get_task).patch(update_task))
        .route("/tasks", get(list_tasks).post(create_task))
        .route("/tasks/{id}", get(get_task).patch(update_task))
        // Agents
        .route("/api/agents", get(list_agents))
        .route("/api/agents/register", post(register_agent))
        // Blackboard
        .route("/api/blackboard/activity", post(post_activity))
        .route("/api/blackboard/feed", get(get_blackboard_feed))
        .route("/blackboard/activity", post(post_activity))
        .route("/blackboard/feed", get(get_blackboard_feed))
        // Knowledge
        .route("/api/knowledge", post(save_knowledge_handler))
        .route("/api/knowledge/search", get(search_knowledge))
        .route("/knowledge", post(save_knowledge_handler))
        .route("/knowledge/search", get(search_knowledge))
        .layer(CorsLayer::permissive())
        .with_state(state);

    let port: u16 = std::env::var("PORT")
        .ok()
        .and_then(|p| p.parse().ok())
        .unwrap_or(8080);

    let addr = format!("0.0.0.0:{}", port);
    info!("🚀 AgentForge Gateway starting on http://{}", addr);
    info!("📊 Dashboard: http://localhost:{}", port);
    info!("📡 API: http://localhost:{}/api/health", port);

    let listener = tokio::net::TcpListener::bind(&addr).await.unwrap();
    axum::serve(listener, app).await.unwrap();
}
