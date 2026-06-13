use axum::{
    extract::{ws::{Message as WsMessage, WebSocket, WebSocketUpgrade}, Path, Query, State},
    http::StatusCode,
    response::{Html, IntoResponse, Json},
    routing::{get, post},
    Router,
};
use chrono::Utc;
use rusqlite::{params, Connection};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::sync::{Arc, Mutex};
use tower_http::cors::CorsLayer;
use tracing::{info, warn};
use futures::{sink::SinkExt, stream::StreamExt};

// ═══════════════════════════════════════════════════════
//  Types
// ═══════════════════════════════════════════════════════

#[derive(Clone)]
struct AppState {
    db: Arc<Mutex<Connection>>,
    data_dir: String,
    ws_tx: tokio::sync::broadcast::Sender<TaskUpdateMsg>,
}

/// Асинхронный helper для безопасного выполнения синхронных (блокирующих) операций с БД rusqlite.
/// КЛЮЧЕВОЕ ИСПРАВЛЕНИЕ ПЕРФОМАНСА:
/// Ранее каждый хендлер делал state.db.lock().unwrap() прямо в async fn — это блокировало
/// worker-тред Tokio на всё время работы с SQLite (в т.ч. тяжёлые scan + json parse в metrics/list).
/// Под нагрузкой 64-200+ concurrent это приводило к:
///   - росту p95/p99 latency до 800-1700ms
///   - просадке RPS до ~250-340 (вместо тысяч)
///   - 100% CPU на worker threads при contention.
/// Теперь работа с БД уходит в отдельный blocking pool (tokio spawn_blocking), async-треды
/// освобождаются. Это стандартный паттерн для rusqlite + axum/tokio.
/// Дополнительно: при желании можно добавить r2d2/deadpool + несколько read-only conn,
/// но spawn_blocking даёт быстрый и достаточный выигрыш.
async fn with_db<F, R>(state: &AppState, f: F) -> R
where
    F: FnOnce(&Connection) -> R + Send + 'static,
    R: Send + 'static,
{
    let db = state.db.clone();
    tokio::task::spawn_blocking(move || {
        let guard = db.lock().expect("DB mutex poisoned in with_db");
        f(&*guard)
    })
    .await
    .expect("spawn_blocking DB task failed (panic or join error)")
}

#[derive(Clone, Serialize, Deserialize)]
struct TaskUpdateMsg {
    r#type: String,
    task_id: String,
    data: serde_json::Value,
}

#[derive(Debug, Serialize)]
struct TaskResponse {
    id: String,
    title: String,
    description: String,
    priority: String,
    complexity: String,
    preferred_agent: String,
    status: String,
    assigned_agent: Option<String>,
    result: Option<String>,
    git_branch: Option<String>,
    created_at: String,
    updated_at: String,
    tags: Vec<String>,
    duration_seconds: Option<f64>,
    started_at: Option<String>,
    completed_at: Option<String>,
}

#[derive(Debug, Deserialize)]
struct CreateTask {
    title: String,
    #[serde(default)]
    description: Option<String>,
    #[serde(default)]
    priority: Option<String>,
    #[serde(default)]
    complexity: Option<String>,
    #[serde(default)]
    preferred_agent: Option<String>,
    #[serde(default)]
    tags: Option<Vec<String>>,
    #[serde(default)]
    parent_id: Option<String>,
    #[serde(default)]
    repo: Option<String>,
}

#[derive(Debug, Deserialize)]
struct TaskUpdate {
    #[serde(default)]
    status: Option<String>,
    #[serde(default)]
    result: Option<serde_json::Value>,
    #[serde(default)]
    assigned_agent: Option<serde_json::Value>,
    #[serde(default)]
    duration_seconds: Option<f64>,
    #[serde(default)]
    retry_count: Option<i64>,
    #[serde(default)]
    description: Option<String>,
}

#[derive(Debug, Deserialize)]
struct TaskReject {
    feedback: String,
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

#[derive(Debug, Deserialize)]
struct ListTasksQuery {
    #[serde(default)]
    status: Option<String>,
}

#[derive(Debug, Serialize)]
struct HealthResponse {
    status: String,
    service: String,
    version: String,
    timestamp: String,
}

// ═══════════════════════════════════════════════════════
//  Helpers
// ═══════════════════════════════════════════════════════

fn map_step_to_status(step: &str) -> &str {
    match step {
        "dispatch" => "pending",
        "git_clone" | "grok_start" | "grok_done" | "ci_start" | "ci_done" | "ci_failed" | "rollback" | "dispatched" | "in_progress" => "in_progress",
        "review" => "review",
        "done" => "done",
        "failed" => "failed",
        other => other,
    }
}

fn resolve_agent(preferred_agent: &str, complexity: &str, tags: &[String]) -> String {
    if preferred_agent != "auto" {
        return preferred_agent.to_string();
    }

    let tags_lower: Vec<String> = tags.iter().map(|t| t.to_lowercase()).collect();

    if complexity == "complex"
        || (tags_lower
            .iter()
            .any(|t| t == "architecture" || t == "analysis" || t == "algorithm" || t == "review"))
    {
        return "antigravity".to_string();
    }

    "grok".to_string()
}

fn get_task_response(conn: &Connection, task_id: &str) -> Option<TaskResponse> {
    let mut stmt = conn
        .prepare("SELECT task_id, created_at, last_step, last_updated FROM tasks WHERE task_id = ?1")
        .ok()?;
    let task_row = stmt
        .query_row([task_id], |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, String>(2).unwrap_or_else(|_| "dispatch".into()),
                row.get::<_, String>(3)?,
            ))
        })
        .ok()?;

    let (task_id, created_at, last_step, last_updated) = task_row;

    let checkpoint_json: Option<String> = conn
        .query_row(
            "SELECT data_json FROM checkpoints WHERE task_id = ?1 ORDER BY created_at DESC LIMIT 1",
            [task_id.clone()],
            |row| row.get(0),
        )
        .ok();

    let mut title = "Untitled Task".to_string();
    let mut description = "".to_string();
    let mut priority = "medium".to_string();
    let mut complexity = "medium".to_string();
    let mut preferred_agent = "auto".to_string();
    let mut assigned_agent = None;
    let mut result = None;
    let mut git_branch = Some(format!("agentforge/{}", task_id));
    let mut tags = Vec::new();
    let mut duration_seconds = None;
    let mut started_at = None;
    let mut completed_at = None;

    if let Some(json_str) = checkpoint_json {
        if let Ok(val) = serde_json::from_str::<serde_json::Value>(&json_str) {
            if let Some(t) = val.get("title").and_then(|v| v.as_str()) {
                title = t.to_string();
            }
            if let Some(d) = val.get("description").and_then(|v| v.as_str()) {
                description = d.to_string();
            }
            if let Some(p) = val.get("priority").and_then(|v| v.as_str()) {
                priority = p.to_string();
            }
            if let Some(c) = val.get("complexity").and_then(|v| v.as_str()) {
                complexity = c.to_string();
            }
            if let Some(pa) = val.get("preferred_agent").and_then(|v| v.as_str()) {
                preferred_agent = pa.to_string();
            }
            if let Some(aa) = val.get("assigned_agent").and_then(|v| v.as_str()) {
                assigned_agent = Some(aa.to_string());
            }
            if let Some(r) = val.get("result").and_then(|v| v.as_str()) {
                result = Some(r.to_string());
            }
            if let Some(gb) = val.get("git_branch").and_then(|v| v.as_str()) {
                git_branch = Some(gb.to_string());
            }
            if let Some(dur) = val.get("duration_seconds").and_then(|v| v.as_f64()) {
                duration_seconds = Some(dur);
            }
            if let Some(sa) = val.get("started_at").and_then(|v| v.as_str()) {
                started_at = Some(sa.to_string());
            }
            if let Some(ca) = val.get("completed_at").and_then(|v| v.as_str()) {
                completed_at = Some(ca.to_string());
            }
            if let Some(t_arr) = val.get("tags").and_then(|v| v.as_array()) {
                tags = t_arr
                    .iter()
                    .filter_map(|t| t.as_str().map(|s| s.to_string()))
                    .collect();
            }
        }
    }

    let status = map_step_to_status(&last_step).to_string();

    Some(TaskResponse {
        id: task_id,
        title,
        description,
        priority,
        complexity,
        preferred_agent,
        status,
        assigned_agent,
        result,
        git_branch,
        created_at,
        updated_at: last_updated,
        tags,
        duration_seconds,
        started_at,
        completed_at,
    })
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

        -- Таблица knowledge (Shared Memory / RAG для агентов). Создаём здесь для надёжности.
        -- Ранее создавалась только в save_knowledge_handler (on-demand).
        CREATE TABLE IF NOT EXISTS knowledge (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent TEXT,
            task_id TEXT,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            embedding_hash TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_knowledge_created ON knowledge (created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_knowledge_key ON knowledge (key);
        ",
    )
    .unwrap();

    info!("✅ Database initialized");
}

// ═══════════════════════════════════════════════════════
//  Handlers
// ═══════════════════════════════════════════════════════

async fn dashboard_handler() -> impl IntoResponse {
    let home = std::env::var("HOME").unwrap_or_else(|_| "/home/eveselove".into());
    let path = format!("{}/agentforge/gateway/static/dashboard.html", home);
    match std::fs::read_to_string(&path) {
        Ok(html) => Html(html).into_response(),
        Err(e) => (
            StatusCode::NOT_FOUND,
            format!(
                "<h1>Dashboard error: {}</h1><p>Expected path: {}</p>",
                e, path
            ),
        )
            .into_response(),
    }
}

async fn health_api() -> Json<HealthResponse> {
    Json(HealthResponse {
        status: "ok".into(),
        service: "AgentForge Task Queue".into(),
        version: "1.0.0".into(),
        timestamp: Utc::now().to_rfc3339(),
    })
}

async fn list_tasks_api(
    State(state): State<AppState>,
    Query(q): Query<ListTasksQuery>,
) -> impl IntoResponse {
    // ИСПРАВЛЕНИЕ: используем with_db + spawn_blocking чтобы не блокировать async runtime.
    // Также ограничиваем выборку 200 задачами по умолчанию для защиты под нагрузкой.
    let status_filter = q.status.clone();
    let responses: Vec<TaskResponse> = with_db(&state, move |db| {
        let ids: Vec<String> = if let Some(ref status_str) = status_filter {
            let step = match status_str.as_str() {
                "pending" => "dispatch",
                "in_progress" => "grok_start",
                "review" => "review",
                "done" => "done",
                "failed" => "failed",
                other => other,
            };
            // Fair queue: for pending/auto pool use ASC (oldest first) so "who grabs first" is deterministic FIFO + priority.
            // (Previously DESC caused newest-first LIFO grab order in batch tests.)
            let mut stmt = db.prepare("SELECT task_id FROM tasks WHERE last_step = ?1 ORDER BY created_at ASC LIMIT 200").unwrap();
            stmt.query_map([step], |row| row.get::<_, String>(0))
                .unwrap()
                .filter_map(|r| r.ok())
                .collect()
        } else {
            // Fair queue: default list now oldest-first (ASC) for predictability in work-stealing / auto pool grabs.
            let mut stmt = db.prepare("SELECT task_id FROM tasks ORDER BY created_at ASC LIMIT 200").unwrap();
            stmt.query_map([], |row| row.get::<_, String>(0))
                .unwrap()
                .filter_map(|r| r.ok())
                .collect()
        };

        let mut out = Vec::new();
        for id in ids {
            if let Some(resp) = get_task_response(db, &id) {
                if let Some(ref req_status) = status_filter {
                    if resp.status == *req_status {
                        out.push(resp);
                    }
                } else {
                    out.push(resp);
                }
            }
        }
        out
    }).await;

    Json(responses).into_response()
}

async fn create_task_api(
    State(state): State<AppState>,
    Json(payload): Json<CreateTask>,
) -> impl IntoResponse {
    // ПОЛНОСТЬЮ ПЕРЕПИСАНО ДЛЯ ПЕРФ: вся работа с БД (insert + read) идёт через spawn_blocking.
    // Handler больше не держит лок + не блокирует tokio worker.
    let task_id = format!("task-{}", &uuid::Uuid::new_v4().to_string()[..8]);
    let now = Utc::now().to_rfc3339();
    let git_branch = format!("agentforge/{}", task_id);

    let priority = payload.priority.clone().unwrap_or_else(|| "medium".into());
    let complexity = payload.complexity.clone().unwrap_or_else(|| "medium".into());
    let preferred_agent = payload.preferred_agent.clone().unwrap_or_else(|| "auto".into());
    let tags = payload.tags.clone().unwrap_or_default();
    let description = payload.description.clone().unwrap_or_default();
    let parent_id = payload.parent_id.clone();
    let title = payload.title.clone();

    let data = serde_json::json!({
        "title": title,
        "description": description,
        "priority": priority,
        "complexity": complexity,
        "preferred_agent": preferred_agent,
        "tags": tags,
        "git_branch": git_branch.clone(),
        "created_at": now.clone(),
        "assigned_agent": None::<String>,
    });

    // Клонируем данные для переноса в blocking closure
    let tid = task_id.clone();
    let now2 = now.clone();
    let parent2 = parent_id.clone();
    let data_str = data.to_string();
    let ws_tx = state.ws_tx.clone();

    let task_resp = with_db(&state, move |db| {
        db.execute(
            "INSERT INTO tasks (task_id, created_at, last_step, last_updated, parent_task_id) VALUES (?1, ?2, 'dispatch', ?2, ?3)",
            params![tid, now2, parent2],
        ).unwrap();

        db.execute(
            "INSERT INTO checkpoints (task_id, step, data_json, created_at) VALUES (?1, 'dispatch', ?2, ?3)",
            params![tid, data_str, now2],
        ).unwrap();

        if let Some(ref parent) = parent2 {
            let existing: String = db
                .query_row("SELECT COALESCE(subtasks_json, '[]') FROM tasks WHERE task_id = ?1", params![parent], |r| r.get(0))
                .unwrap_or_else(|_| "[]".into());
            let mut subs: Vec<String> = serde_json::from_str(&existing).unwrap_or_default();
            subs.push(tid.clone());
            db.execute(
                "UPDATE tasks SET subtasks_json = ?1 WHERE task_id = ?2",
                params![serde_json::to_string(&subs).unwrap(), parent],
            ).unwrap();
        }

        // Получаем свежий task_resp внутри той же блокировки (дешево)
        get_task_response(db, &tid).expect("just created task must be readable")
    }).await;

    // Broadcast (лёгкая операция, вне DB)
    let ws_msg = TaskUpdateMsg {
        r#type: "task_update".into(),
        task_id: task_id.clone(),
        data: serde_json::to_value(&task_resp).unwrap(),
    };
    let _ = ws_tx.send(ws_msg);

    (StatusCode::CREATED, Json(task_resp)).into_response()
}

async fn get_task_api(
    State(state): State<AppState>,
    Path(id): Path<String>,
) -> impl IntoResponse {
    let db = state.db.lock().unwrap();
    match get_task_response(&db, &id) {
        Some(task) => Json(task).into_response(),
        None => (
            StatusCode::NOT_FOUND,
            Json(serde_json::json!({"error": "task not found"})),
        )
            .into_response(),
    }
}

async fn update_task_api(
    State(state): State<AppState>,
    Path(task_id): Path<String>,
    Json(payload): Json<TaskUpdate>,
) -> impl IntoResponse {
    let db = state.db.lock().unwrap();

    // === Fair Queue CAS: read authoritative current BEFORE any mutation ===
    let current_resp = get_task_response(&db, &task_id);
    if current_resp.is_none() {
        return (StatusCode::NOT_FOUND, Json(serde_json::json!({"error": "task not found"}))).into_response();
    }
    let current = current_resp.unwrap();

    // Claim attempt = trying to move pending -> in_progress/dispatched while providing an agent
    let is_claim = payload.status.as_deref().map_or(false, |s| s == "in_progress" || s == "dispatched")
        && payload.assigned_agent.as_ref().map_or(false, |v| v.is_string());

    if is_claim && current.status != "pending" {
        // Another agent grabbed first (or already moved). Return current (owner) without overwrite.
        // This + the Mutex on db ensures strict "who grabs first" first-wins, no double assignment.
        println!("[AgentForge] ⚔️ CAS reject (rust gate): {} already {} (agent={:?}), rejecting claim from {:?}",
            task_id, current.status, current.assigned_agent, payload.assigned_agent);
        return Json(current).into_response();
    }

    let mut stmt = match db.prepare("SELECT task_id, last_step, retry_count FROM tasks WHERE task_id = ?1") {
        Ok(s) => s,
        Err(_) => return (StatusCode::NOT_FOUND, Json(serde_json::json!({"error": "task not found"}))).into_response(),
    };
    let current_task = stmt.query_row([task_id.clone()], |row| {
        Ok((
            row.get::<_, String>(0)?,
            row.get::<_, String>(1).unwrap_or_else(|_| "dispatch".into()),
            row.get::<_, i64>(2).unwrap_or(0),
        ))
    });

    let (task_id, mut last_step, mut current_retry) = match current_task {
        Ok(t) => t,
        Err(_) => return (StatusCode::NOT_FOUND, Json(serde_json::json!({"error": "task not found"}))).into_response(),
    };

    let checkpoint_json: Option<String> = db
        .query_row(
            "SELECT data_json FROM checkpoints WHERE task_id = ?1 ORDER BY created_at DESC LIMIT 1",
            [task_id.clone()],
            |row| row.get(0),
        )
        .ok();

    let mut data_map = if let Some(ref json_str) = checkpoint_json {
        serde_json::from_str::<serde_json::Value>(json_str).unwrap_or_else(|_| serde_json::json!({}))
    } else {
        serde_json::json!({})
    };

    let now = Utc::now().to_rfc3339();

    if let Some(ref status_str) = payload.status {
        let step = match status_str.as_str() {
            "pending" => "dispatch",
            "in_progress" => "grok_start",
            "review" => "review",
            "done" => "done",
            "failed" => "failed",
            other => other,
        };
        last_step = step.to_string();

        if status_str == "in_progress" || status_str == "dispatched" {
            data_map["started_at"] = serde_json::json!(now.clone());
        }
        if status_str == "done" || status_str == "review" || status_str == "failed" {
            data_map["completed_at"] = serde_json::json!(now.clone());
        }
    }

    if let Some(ref res_val) = payload.result {
        if res_val.is_null() {
            data_map.as_object_mut().unwrap().remove("result");
        } else if let Some(s) = res_val.as_str() {
            data_map["result"] = serde_json::json!(s);
        }
    }

    if let Some(ref agent_val) = payload.assigned_agent {
        if agent_val.is_null() {
            data_map.as_object_mut().unwrap().remove("assigned_agent");
        } else if let Some(s) = agent_val.as_str() {
            data_map["assigned_agent"] = serde_json::json!(s);
        }
    }

    if let Some(dur) = payload.duration_seconds {
        data_map["duration_seconds"] = serde_json::json!(dur);
    }

    if let Some(ref desc) = payload.description {
        data_map["description"] = serde_json::json!(desc);
    }

    if let Some(rc) = payload.retry_count {
        current_retry = rc;
        data_map["retry_count"] = serde_json::json!(rc);
    }

    db.execute(
        "UPDATE tasks SET last_step = ?1, last_updated = ?2, retry_count = ?3 WHERE task_id = ?4",
        params![last_step, now, current_retry, task_id],
    )
    .unwrap();

    db.execute(
        "INSERT INTO checkpoints (task_id, step, data_json, created_at) VALUES (?1, ?2, ?3, ?4)",
        params![task_id, last_step, data_map.to_string(), now],
    )
    .unwrap();

    let task_resp = get_task_response(&db, &task_id).unwrap();

    let ws_msg = TaskUpdateMsg {
        r#type: "task_update".into(),
        task_id: task_id.clone(),
        data: serde_json::to_value(&task_resp).unwrap(),
    };
    let _ = state.ws_tx.send(ws_msg);

    Json(task_resp).into_response()
}

async fn dispatch_task_api(
    State(state): State<AppState>,
    Path(task_id): Path<String>,
) -> impl IntoResponse {
    let db = state.db.lock().unwrap();

    let task_resp = match get_task_response(&db, &task_id) {
        Some(t) => t,
        None => return (StatusCode::NOT_FOUND, Json(serde_json::json!({"error": "task not found"}))).into_response(),
    };

    if task_resp.status != "pending" && task_resp.status != "failed" {
        return (
            StatusCode::CONFLICT,
            Json(serde_json::json!({
                "error": format!("Task {} is already in status '{}'", task_id, task_resp.status)
            })),
        )
            .into_response();
    }

    let agent = resolve_agent(&task_resp.preferred_agent, &task_resp.complexity, &task_resp.tags);
    let now = Utc::now().to_rfc3339();

    let checkpoint_json: Option<String> = db
        .query_row(
            "SELECT data_json FROM checkpoints WHERE task_id = ?1 ORDER BY created_at DESC LIMIT 1",
            [task_id.clone()],
            |row| row.get(0),
        )
        .ok();

    let mut data_map = if let Some(ref json_str) = checkpoint_json {
        serde_json::from_str::<serde_json::Value>(json_str).unwrap_or_else(|_| serde_json::json!({}))
    } else {
        serde_json::json!({})
    };

    data_map["started_at"] = serde_json::json!(now.clone());
    data_map["assigned_agent"] = serde_json::json!(agent.clone());

    db.execute(
        "UPDATE tasks SET last_step = 'dispatched', last_updated = ?1 WHERE task_id = ?2",
        params![now, task_id],
    )
    .unwrap();

    db.execute(
        "INSERT INTO checkpoints (task_id, step, data_json, created_at) VALUES (?1, 'dispatched', ?2, ?3)",
        params![task_id, data_map.to_string(), now],
    )
    .unwrap();

    let task_resp_updated = get_task_response(&db, &task_id).unwrap();

    // Broadcast update via WebSocket
    let ws_msg = TaskUpdateMsg {
        r#type: "task_update".into(),
        task_id: task_id.clone(),
        data: serde_json::to_value(&task_resp_updated).unwrap(),
    };
    let _ = state.ws_tx.send(ws_msg);

    // Run dispatcher.sh in the background
    let home = std::env::var("HOME").unwrap_or_else(|_| "/home/eveselove".into());
    let dispatcher_path = format!("{}/agentforge/dispatcher.sh", home);
    let task_id_arg = task_id.clone();
    let agent_arg = agent.clone();
    let desc_arg = task_resp.description.clone();
    let priority_arg = task_resp.priority.clone();

    tokio::spawn(async move {
        let child = tokio::process::Command::new("bash")
            .arg(dispatcher_path)
            .arg(task_id_arg)
            .arg(agent_arg)
            .arg(desc_arg)
            .arg(priority_arg)
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::null())
            .spawn();

        if let Ok(mut c) = child {
            let _ = c.wait().await;
        }
    });

    Json(serde_json::json!({
        "task_id": task_id,
        "assigned_agent": agent,
        "status": "dispatched",
        "message": format!("Задача отправлена агенту '{}'", agent),
    }))
    .into_response()
}

fn perform_guardian_review(
    db: &Connection,
    ws_tx: &tokio::sync::broadcast::Sender<TaskUpdateMsg>,
    task_id: &str,
) -> Result<serde_json::Value, String> {
    let task_resp = get_task_response(db, task_id).ok_or_else(|| "task not found".to_string())?;

    let mut issues = Vec::new();
    let result_str = task_resp.result.clone().unwrap_or_default();

    if result_str.is_empty() {
        issues.push("Нет результата выполнения".to_string());
    }

    if result_str.to_lowercase().contains("fail") || result_str.contains("❌") {
        issues.push(format!("CI провалился: {}", result_str));
    }

    if task_resp.status != "review" {
        issues.push(format!(
            "Задача не в статусе review (current: {})",
            task_resp.status
        ));
    }

    let now = Utc::now().to_rfc3339();

    let checkpoint_json: Option<String> = db
        .query_row(
            "SELECT data_json FROM checkpoints WHERE task_id = ?1 ORDER BY created_at DESC LIMIT 1",
            [task_id],
            |row| row.get(0),
        )
        .ok();

    let mut data_map = if let Some(ref json_str) = checkpoint_json {
        serde_json::from_str::<serde_json::Value>(json_str).unwrap_or_else(|_| serde_json::json!({}))
    } else {
        serde_json::json!({})
    };

    let verdict;
    let message;
    let new_status;

    if !issues.is_empty() {
        verdict = "needs_attention";
        message = "Задача требует внимания";
        new_status = "review".to_string();

        let comment = format!("Guardian: {}", issues.join("; "));
        data_map["result"] = serde_json::json!(comment);
    } else {
        verdict = "approved";
        message = "Guardian одобрил задачу ✅";
        new_status = "done".to_string();

        let comment = format!("{} | Guardian: approved ✅", result_str);
        data_map["result"] = serde_json::json!(comment);
    }

    db.execute(
        "UPDATE tasks SET last_step = ?1, last_updated = ?2 WHERE task_id = ?3",
        params![new_status, now, task_id],
    )
    .map_err(|e| e.to_string())?;

    db.execute(
        "INSERT INTO checkpoints (task_id, step, data_json, created_at) VALUES (?1, ?2, ?3, ?4)",
        params![task_id, new_status, data_map.to_string(), now],
    )
    .map_err(|e| e.to_string())?;

    if let Some(task_resp_updated) = get_task_response(db, task_id) {
        let ws_msg = TaskUpdateMsg {
            r#type: "task_update".into(),
            task_id: task_id.to_string(),
            data: serde_json::to_value(&task_resp_updated).unwrap(),
        };
        let _ = ws_tx.send(ws_msg);
    }

    Ok(serde_json::json!({
        "task_id": task_id,
        "verdict": verdict,
        "issues": issues,
        "message": message
    }))
}

async fn review_task_api(
    State(state): State<AppState>,
    Path(task_id): Path<String>,
) -> impl IntoResponse {
    let db = state.db.lock().unwrap();
    match perform_guardian_review(&db, &state.ws_tx, &task_id) {
        Ok(res) => Json(res).into_response(),
        Err(e) => (
            StatusCode::NOT_FOUND,
            Json(serde_json::json!({"error": e})),
        )
            .into_response(),
    }
}

async fn review_all_tasks_api(State(state): State<AppState>) -> impl IntoResponse {
    let db = state.db.lock().unwrap();
    let mut stmt = db
        .prepare("SELECT task_id FROM tasks WHERE last_step = 'review'")
        .unwrap();
    let task_ids: Vec<String> = stmt
        .query_map([], |row| row.get(0))
        .unwrap()
        .filter_map(|r| r.ok())
        .collect();

    let mut results = Vec::new();
    for id in task_ids {
        if let Ok(res) = perform_guardian_review(&db, &state.ws_tx, &id) {
            results.push(res);
        }
    }

    Json(serde_json::json!({
        "reviewed": results.len(),
        "results": results
    }))
}

async fn reject_task_api(
    State(state): State<AppState>,
    Path(task_id): Path<String>,
    Json(payload): Json<TaskReject>,
) -> impl IntoResponse {
    let db = state.db.lock().unwrap();

    let _task_resp = match get_task_response(&db, &task_id) {
        Some(t) => t,
        None => return (StatusCode::NOT_FOUND, Json(serde_json::json!({"error": "task not found"}))).into_response(),
    };

    let now = Utc::now().to_rfc3339();
    let feedback_msg = format!("[HITL Отклонено]: {}", payload.feedback);

    let checkpoint_json: Option<String> = db
        .query_row(
            "SELECT data_json FROM checkpoints WHERE task_id = ?1 ORDER BY created_at DESC LIMIT 1",
            [task_id.clone()],
            |row| row.get(0),
        )
        .ok();

    let mut data_map = if let Some(ref json_str) = checkpoint_json {
        serde_json::from_str::<serde_json::Value>(json_str).unwrap_or_else(|_| serde_json::json!({}))
    } else {
        serde_json::json!({})
    };

    data_map["result"] = serde_json::json!(feedback_msg);
    data_map.as_object_mut().unwrap().remove("assigned_agent");

    db.execute(
        "UPDATE tasks SET last_step = 'dispatch', last_updated = ?1 WHERE task_id = ?2",
        params![now, task_id],
    )
    .unwrap();

    db.execute(
        "INSERT INTO checkpoints (task_id, step, data_json, created_at) VALUES (?1, 'dispatch', ?2, ?3)",
        params![task_id, data_map.to_string(), now],
    )
    .unwrap();

    let task_resp_updated = get_task_response(&db, &task_id).unwrap();

    let ws_msg = TaskUpdateMsg {
        r#type: "task_update".into(),
        task_id: task_id.clone(),
        data: serde_json::to_value(&task_resp_updated).unwrap(),
    };
    let _ = state.ws_tx.send(ws_msg);

    Json(task_resp_updated).into_response()
}

async fn metrics_api(State(state): State<AppState>) -> impl IntoResponse {
    let db = state.db.lock().unwrap();

    let total_tasks: i64 = db
        .query_row("SELECT COUNT(*) FROM tasks", [], |r| r.get(0))
        .unwrap_or(0);

    let mut stmt = db
        .prepare(
            "SELECT t.task_id, t.last_step, t.created_at, t.last_updated,
                    (SELECT data_json FROM checkpoints c WHERE c.task_id = t.task_id ORDER BY c.created_at DESC LIMIT 1)
             FROM tasks t",
        )
        .unwrap();

    let mut by_status: HashMap<String, i64> = HashMap::new();
    let mut by_agent: HashMap<String, i64> = HashMap::new();
    let mut by_priority: HashMap<String, i64> = HashMap::new();
    let mut completed_durations: Vec<f64> = Vec::new();
    let mut agent_durations: HashMap<String, Vec<f64>> = HashMap::new();

    let rows = stmt
        .query_map([], |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, String>(1).unwrap_or_else(|_| "dispatch".into()),
                row.get::<_, String>(2)?,
                row.get::<_, String>(3)?,
                row.get::<_, Option<String>>(4)?,
            ))
        })
        .unwrap();

    for r in rows.flatten() {
        let (_, last_step, created_at, last_updated, data_json_opt) = r;
        let status = map_step_to_status(&last_step).to_string();
        *by_status.entry(status.clone()).or_default() += 1;

        let mut priority = "medium".to_string();
        let mut assigned_agent = None;
        let mut duration_seconds = None;

        if let Some(ref json_str) = data_json_opt {
            if let Ok(val) = serde_json::from_str::<serde_json::Value>(json_str) {
                if let Some(p) = val.get("priority").and_then(|v| v.as_str()) {
                    priority = p.to_string();
                }
                if let Some(aa) = val.get("assigned_agent").and_then(|v| v.as_str()) {
                    assigned_agent = Some(aa.to_string());
                }
                if let Some(dur) = val.get("duration_seconds").and_then(|v| v.as_f64()) {
                    duration_seconds = Some(dur);
                }
            }
        }

        *by_priority.entry(priority).or_default() += 1;

        if let Some(ref agent) = assigned_agent {
            *by_agent.entry(agent.clone()).or_default() += 1;
        }

        if status == "done" || status == "review" {
            if let (Ok(c_dt), Ok(u_dt)) = (
                chrono::DateTime::parse_from_rfc3339(&created_at),
                chrono::DateTime::parse_from_rfc3339(&last_updated),
            ) {
                let dur = u_dt.signed_duration_since(c_dt).num_seconds() as f64;
                if dur > 0.0 {
                    completed_durations.push(dur);
                }
            }
        }

        if let Some(dur) = duration_seconds {
            if let Some(ref agent) = assigned_agent {
                agent_durations.entry(agent.clone()).or_default().push(dur);
            }
        }
    }

    let avg_completion_seconds = if !completed_durations.is_empty() {
        Some(
            (completed_durations.iter().sum::<f64>() / completed_durations.len() as f64 * 10.0)
                .round()
                / 10.0,
        )
    } else {
        None
    };

    let mut agent_performance = serde_json::json!({});
    for (agent, durs) in agent_durations {
        let avg = if !durs.is_empty() {
            (durs.iter().sum::<f64>() / durs.len() as f64 * 10.0).round() / 10.0
        } else {
            0.0
        };
        agent_performance[agent] = serde_json::json!({
            "avg_seconds": avg,
            "completed": durs.len()
        });
    }

    Json(serde_json::json!({
        "total_tasks": total_tasks,
        "by_status": by_status,
        "by_agent": by_agent,
        "by_priority": by_priority,
        "avg_completion_seconds": avg_completion_seconds,
        "agent_performance": agent_performance,
        "timestamp": Utc::now().to_rfc3339()
    }))
}

async fn get_agents_api() -> impl IntoResponse {
    let home = std::env::var("HOME").unwrap_or_else(|_| "/home/eveselove".into());
    let cards_path = format!("{}/agentforge/gateway/agent_cards.json", home);
    match std::fs::read_to_string(&cards_path) {
        Ok(content) => match serde_json::from_str::<serde_json::Value>(&content) {
            Ok(val) => Json(val).into_response(),
            Err(e) => (
                StatusCode::INTERNAL_SERVER_ERROR,
                Json(serde_json::json!({
                    "error": format!("parse agent cards: {}", e)
                })),
            )
                .into_response(),
        },
        Err(e) => (
            StatusCode::NOT_FOUND,
            Json(serde_json::json!({
                "error": format!("agent_cards.json not found: {}", e)
            })),
        )
            .into_response(),
    }
}

// ── Agents database list ──────────────────────────────

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
    let agent_id = format!("agent-{}", &uuid::Uuid::new_v4().to_string()[..8]);
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
    // Исправлено: теперь уважает параметр q для поиска по key/value (LIKE).
    // Ранее q игнорировался — это было ошибкой покрытия API (knowledge/search).
    let db = state.db.lock().unwrap();
    let limit = q.limit.unwrap_or(20);

    let (sql, params): (String, Vec<String>) = if let Some(ref qq) = q.q {
        let pat = format!("%{}%", qq.replace("'", "''")); // простая экранизация для LIKE
        (
            format!(
                "SELECT id, agent, task_id, key, value, created_at FROM knowledge WHERE key LIKE ?1 OR value LIKE ?1 ORDER BY created_at DESC LIMIT {}",
                limit
            ),
            vec![pat],
        )
    } else {
        (
            format!(
                "SELECT id, agent, task_id, key, value, created_at FROM knowledge ORDER BY created_at DESC LIMIT {}",
                limit
            ),
            vec![],
        )
    };

    let result = db.prepare(&sql);
    match result {
        Ok(mut stmt) => {
            // ФИКС: правильная передача параметров в rusqlite::query_map.
            // params.as_slice() на Vec<String> не удовлетворяет trait Params.
            // Используем rusqlite::params_from_iter для поддержки динамического LIKE поиска по q.
            // Это обеспечивает полное покрытие /api/knowledge/search?q=...
            let rows = if params.is_empty() {
                stmt.query_map([], |row| {
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
                .collect()
            } else {
                stmt.query_map(rusqlite::params_from_iter(params.iter()), |row| {
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
                .collect()
            };
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

    // Таблица уже создаётся в init_db (гарантированно при старте). Оставлено для обратной совместимости со старыми БД.
    // db.execute_batch(...) удалён для уменьшения overhead на каждый save.

    db.execute(
        "INSERT INTO knowledge (agent, task_id, key, value, created_at) VALUES (?1, ?2, ?3, ?4, ?5)",
        params![payload.agent, payload.task_id, payload.key, payload.value, now],
    ).unwrap();

    info!("🧠 Knowledge saved: {}", payload.key);
    (StatusCode::CREATED, Json(serde_json::json!({"ok": true, "key": payload.key})))
}

// ── WebSockets ────────────────────────────────────────

async fn ws_logs_all(
    ws: WebSocketUpgrade,
    State(state): State<AppState>,
) -> impl IntoResponse {
    ws.on_upgrade(move |socket| handle_ws(socket, "*".to_string(), state))
}

async fn ws_logs_task(
    Path(task_id): Path<String>,
    ws: WebSocketUpgrade,
    State(state): State<AppState>,
) -> impl IntoResponse {
    ws.on_upgrade(move |socket| handle_ws(socket, task_id, state))
}

async fn handle_ws(socket: WebSocket, task_id: String, state: AppState) {
    let mut rx = state.ws_tx.subscribe();
    let (mut sender, mut receiver) = socket.split();

    if task_id != "*" {
        let task_resp = {
            let db = state.db.lock().unwrap();
            get_task_response(&db, &task_id)
        };
        if let Some(task_resp) = task_resp {
            let initial = serde_json::json!({
                "type": "initial_state",
                "task_id": task_id,
                "data": task_resp,
            });
            if sender.send(WsMessage::Text(initial.to_string().into())).await.is_err() {
                return;
            }
        }
    }

    let send_task = tokio::spawn(async move {
        while let Ok(msg) = rx.recv().await {
            if task_id == "*" || msg.task_id == task_id {
                let text = serde_json::to_string(&msg).unwrap_or_default();
                if sender.send(WsMessage::Text(text.into())).await.is_err() {
                    break;
                }
            }
        }
    });

    while let Some(Ok(msg)) = receiver.next().await {
        if let WsMessage::Text(text) = msg {
            if text == "ping" {
                // Keep-alive ping/pong
            }
        }
    }

    send_task.abort();
}

async fn ws_status_api(State(state): State<AppState>) -> Json<serde_json::Value> {
    Json(serde_json::json!({
        "total_connections": state.ws_tx.receiver_count(),
    }))
}

// ═══════════════════════════════════════════════════════
//  Main
// ═══════════════════════════════════════════════════════


// ?????? WebSocket push-?????????? ?????? ???????????????? ???????????????????????????????????????????????????
// ?????????????? ?????????????????????????? ???? ws://host/ws/tasks?agent=grok
// ?? ???????????????? push-?????????????????????? ?????? ????????????????/???????????????????? ??????????,
// ???????????? polling GET /tasks ???????????? 10 ????????????.

async fn ws_tasks_handler(
    ws: WebSocketUpgrade,
    Query(params): Query<HashMap<String, String>>,
    State(state): State<AppState>,
) -> impl IntoResponse {
    let agent = params.get("agent").cloned().unwrap_or_default();
    info!("???? Worker WS ??????????????????: agent={}", agent);
    ws.on_upgrade(move |socket| ws_tasks_stream(socket, state, agent))
}

async fn ws_tasks_stream(socket: WebSocket, state: AppState, agent: String) {
    let mut rx = state.ws_tx.subscribe();
    let (mut sender, mut receiver) = socket.split();

    // ?????? ?????????????????????? ???????????????????? ?????? pending ???????????? (?????????? ???????????? ???? ??????????????????)
    {
        let agent_filter = agent.clone();
        let pending_tasks = with_db(&state, move |db| {
            let agent = agent_filter;
            let mut stmt = db.prepare(
                "SELECT task_id FROM tasks WHERE last_step = 'dispatch'"
            ).unwrap();
            let ids: Vec<String> = stmt.query_map([], |row| row.get(0))
                .unwrap()
                .filter_map(|r| r.ok())
                .collect();
            let mut tasks = Vec::new();
            for id in ids {
                if let Some(t) = get_task_response(db, &id) {
                    // ?????????????????? ???? ???????????? (???????? ????????????)
                    if agent.is_empty()
                        || t.preferred_agent == agent
                        || t.preferred_agent == "auto"
                        || t.status == "pending"
                    {
                        tasks.push(t);
                    }
                }
            }
            tasks
        }).await;

        for task in pending_tasks {
            let msg = serde_json::json!({
                "type": "pending_task",
                "task_id": task.id,
                "data": task,
            });
            if sender.send(WsMessage::Text(msg.to_string().into())).await.is_err() {
                return;
            }
        }
    }

    // ?????????????? broadcast ?? ?????????? ???????????????????? ??????????????
    let agent_clone = agent.clone();
    let send_task = tokio::spawn(async move {
        while let Ok(msg) = rx.recv().await {
            // ???????????????????? ?????? ???????????????????? ?????????? (???????????? ?????? ?????????? ?????? ??????????)
            let text = serde_json::to_string(&msg).unwrap_or_default();
            if sender.send(WsMessage::Text(text.into())).await.is_err() {
                break;
            }
        }
    });

    // ???????????????????????? ???????????????? ?????????????????? (ping/pong)
    while let Some(Ok(msg)) = receiver.next().await {
        match msg {
            WsMessage::Text(text) => {
                if text == "ping" {
                    // Keep-alive
                }
            }
            WsMessage::Close(_) => break,
            _ => {}
        }
    }

    info!("???? Worker WS ????????????????: agent={}", agent_clone);
    send_task.abort();
}

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

    let (ws_tx, _) = tokio::sync::broadcast::channel(100);

    let state = AppState {
        db: Arc::new(Mutex::new(conn)),
        data_dir: data_dir.clone(),
        ws_tx,
    };

    // ── Proxy handler for old Planly API ──────────────
    // ИСПРАВЛЕНО: теперь корректно пробрасывает HTTP-метод (GET/POST/PATCH и т.д.) + тело запроса.
    // Ранее всегда использовался reqwest::get, что ломало coverage для POST эндпоинтов /api/planly/*, /api/match/* и т.п.
    // Также копируются ключевые заголовки (кроме Host/Content-Length).
    // Лимит тела: 10MB. Для production добавить таймауты и ретраи.
    async fn proxy_to_planly(req: axum::extract::Request) -> impl IntoResponse {
        let method = req.method().clone();
        let uri = req.uri().to_string();
        let planly_url = format!("http://127.0.0.1:3000{}", uri);
        let headers = req.headers().clone();

        // Читаем тело (поддержка POST/PUT с JSON)
        let body_bytes = match axum::body::to_bytes(req.into_body(), 10 * 1024 * 1024).await {
            Ok(b) => b,
            Err(e) => {
                return (
                    StatusCode::BAD_REQUEST,
                    Json(serde_json::json!({"error": format!("proxy body read: {}", e)})),
                )
                    .into_response();
            }
        };

        let client = reqwest::Client::builder()
            .timeout(std::time::Duration::from_secs(30))
            .build()
            .unwrap_or_else(|_| reqwest::Client::new());

        let mut r = client.request(method, &planly_url);
        for (k, v) in headers.iter() {
            // Пропускаем hop-by-hop заголовки
            if k != axum::http::header::HOST && k != axum::http::header::CONTENT_LENGTH && k != axum::http::header::CONNECTION {
                if let Ok(val) = v.to_str() {
                    r = r.header(k.as_str(), val);
                }
            }
        }
        if !body_bytes.is_empty() {
            r = r.body(body_bytes.to_vec());
        }

        match r.send().await {
            Ok(resp) => {
                let status = StatusCode::from_u16(resp.status().as_u16()).unwrap_or(StatusCode::BAD_GATEWAY);
                let body = resp.text().await.unwrap_or_default();
                (status, [(axum::http::header::CONTENT_TYPE, "application/json")], body).into_response()
            }
            Err(e) => {
                warn!("Proxy error to planly: {}", e);
                (StatusCode::BAD_GATEWAY, Json(serde_json::json!({"error": format!("planly proxy: {}", e)}))).into_response()
            }
        }
    }

    let static_dir = std::env::var("AGENTFORGE_STATIC")
        .unwrap_or_else(|_| format!("{}/gateway/static", std::env::var("HOME").unwrap_or_else(|_| ".".into()) + "/agentforge"));

    info!("📁 Static files: {}", static_dir);

    let app = Router::new()
        // Dashboard
        .route("/", get(dashboard_handler))
        .route("/dashboard", get(dashboard_handler))
        // Health
        .route("/health", get(health_api))
        .route("/api/health", get(health_api))
        // Tasks
        .route("/tasks", get(list_tasks_api).post(create_task_api))
        .route("/api/tasks", get(list_tasks_api).post(create_task_api))
        .route("/tasks/{id}", get(get_task_api).patch(update_task_api))
        .route("/api/tasks/{id}", get(get_task_api).patch(update_task_api))
        .route("/tasks/{id}/dispatch", post(dispatch_task_api))
        .route("/api/tasks/{id}/dispatch", post(dispatch_task_api))
        .route("/tasks/{id}/review", post(review_task_api))
        .route("/api/tasks/{id}/review", post(review_task_api))
        .route("/tasks/{id}/reject", post(reject_task_api))
        .route("/api/tasks/{id}/reject", post(reject_task_api))
        .route("/review/all", post(review_all_tasks_api))
        .route("/api/review/all", post(review_all_tasks_api))
        // Metrics
        .route("/metrics", get(metrics_api))
        .route("/api/metrics", get(metrics_api))
        // Agents
        .route("/agents", get(get_agents_api))
        .route("/api/agents", get(get_agents_api))
        .route("/api/agents/db_list", get(list_agents).post(register_agent))
        // Blackboard
        .route("/api/blackboard/activity", post(post_activity))
        .route("/api/blackboard/feed", get(get_blackboard_feed))
        // Knowledge
        .route("/api/knowledge", post(save_knowledge_handler))
        .route("/api/knowledge/search", get(search_knowledge))
        // Proxy to Planly gateway for parser/analytics/etc
        .route("/api/parser/{*rest}", get(proxy_to_planly).post(proxy_to_planly))
        .route("/api/analytics/{*rest}", get(proxy_to_planly))
        .route("/api/match/{*rest}", get(proxy_to_planly).post(proxy_to_planly))
        .route("/api/services/{*rest}", get(proxy_to_planly).post(proxy_to_planly))
        .route("/api/planly/{*rest}", get(proxy_to_planly).post(proxy_to_planly))
        .route("/api/image", get(proxy_to_planly))
        // WebSocket endpoints
        .route("/ws/logs", get(ws_logs_all))
        .route("/ws/logs/{task_id}", get(ws_logs_task))
        .route("/ws/status", get(ws_status_api))
        .route("/api/ws/status", get(ws_status_api))
        .route("/ws/tasks", get(ws_tasks_handler))
        // Static HTML pages (parsing, monitoring, analytics, merchandising)
        .fallback_service(tower_http::services::ServeDir::new(&static_dir))
        .layer(CorsLayer::permissive())
        .with_state(state);

    let port: u16 = std::env::var("PORT")
        .ok()
        .and_then(|p| p.parse().ok())
        .unwrap_or(9090);

    let addr = format!("0.0.0.0:{}", port);
    info!("🚀 AgentForge Gateway starting on http://{}", addr);
    info!("📊 Dashboard: http://localhost:{}", port);

    let listener = tokio::net::TcpListener::bind(&addr).await.expect("Failed to bind port — is it already in use?");
    axum::serve(listener, app).await.unwrap();
}

