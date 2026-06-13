use axum::{
    extract::{ws::{Message as WsMessage, WebSocket, WebSocketUpgrade}, Path, Query, State},
    http::StatusCode,
    response::{Html, IntoResponse, Json},
    routing::{get, post},
    Router,
};
use chrono::Utc;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::sync::Arc;
use tower_http::cors::CorsLayer;
use tracing::{info, warn};
use futures::{sink::SinkExt, stream::StreamExt};

// Re-export from agentforge-core
use agentforge_core::{LanceTaskStore, Task, TaskStatus, TaskStore};

// ═══════════════════════════════════════════════════════
//  Types
// ═══════════════════════════════════════════════════════

#[derive(Clone)]
struct AppState {
    // Tasks: LanceDB (async-native — no spawn_blocking needed!)
    tasks: Arc<tokio::sync::Mutex<LanceTaskStore>>,
    // Agents: JSON file store
    agents: Arc<tokio::sync::Mutex<JsonStore<Agent>>>,
    // Blackboard: JSON file store
    blackboard: Arc<tokio::sync::Mutex<JsonStore<BlackboardEntry>>>,
    // Knowledge: JSON file store
    knowledge: Arc<tokio::sync::Mutex<JsonStore<Knowledge>>>,
    data_dir: String,
    ws_tx: tokio::sync::broadcast::Sender<TaskUpdateMsg>,
}

// ═══════════════════════════════════════════════════════
//  JsonStore — simple JSON-file-backed store for small data
// ═══════════════════════════════════════════════════════

#[derive(Clone)]
struct JsonStore<T: Clone + Serialize + for<'de> Deserialize<'de>> {
    path: std::path::PathBuf,
    items: Vec<T>,
}

impl<T: Clone + Serialize + for<'de> Deserialize<'de>> JsonStore<T> {
    fn new(path: impl Into<std::path::PathBuf>) -> Self {
        let path = path.into();
        let items = if path.exists() {
            std::fs::read_to_string(&path)
                .ok()
                .and_then(|s| serde_json::from_str(&s).ok())
                .unwrap_or_default()
        } else {
            vec![]
        };
        Self { path, items }
    }

    fn persist(&self) {
        if let Some(parent) = self.path.parent() {
            let _ = std::fs::create_dir_all(parent);
        }
        let tmp = self.path.with_extension("json.tmp");
        if let Ok(json) = serde_json::to_string_pretty(&self.items) {
            if std::fs::write(&tmp, json).is_ok() {
                let _ = std::fs::rename(&tmp, &self.path);
            }
        }
    }

    fn push(&mut self, item: T) {
        self.items.push(item);
        self.persist();
    }

    fn all(&self) -> &[T] {
        &self.items
    }
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

impl From<&Task> for TaskResponse {
    fn from(t: &Task) -> Self {
        let status = match t.status {
            TaskStatus::Pending => "pending",
            TaskStatus::Dispatched => "dispatched",
            TaskStatus::InProgress => "in_progress",
            TaskStatus::Review => "review",
            TaskStatus::Done => "done",
            TaskStatus::Failed => "failed",
            TaskStatus::Cancelled => "cancelled",
        };
        Self {
            id: t.id.clone(),
            title: t.title.clone(),
            description: t.description.clone(),
            priority: t.priority.clone(),
            complexity: t.complexity.clone(),
            preferred_agent: t.preferred_agent.clone().unwrap_or("auto".into()),
            status: status.to_string(),
            assigned_agent: t.assigned_to.clone(),
            result: t.result.as_ref().and_then(|v| v.as_str().map(|s| s.to_string())),
            git_branch: t.metadata.get("git_branch").and_then(|v| v.as_str().map(|s| s.to_string())),
            created_at: t.created_at.clone(),
            updated_at: t.updated_at.clone(),
            tags: t.tags.clone(),
            duration_seconds: t.metadata.get("duration_seconds").and_then(|v| v.as_f64()),
            started_at: t.started_at.clone(),
            completed_at: t.completed_at.clone(),
        }
    }
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

#[derive(Debug, Clone, Serialize, Deserialize)]
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

#[derive(Debug, Clone, Serialize, Deserialize)]
struct Knowledge {
    id: i64,
    #[serde(skip_serializing_if = "Option::is_none")]
    agent: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    task_id: Option<String>,
    key: String,
    value: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    embedding_hash: Option<String>,
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
    #[serde(default)]
    embedding_hash: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
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
    // WAVE4 blackboard filters (passed from py shims; applied in get_blackboard_feed)
    #[serde(default)]
    team_id: Option<String>,
    #[serde(default)]
    task_id: Option<String>,
    #[serde(default)]
    agent: Option<String>,
    #[serde(default)]
    since_minutes: Option<i64>,
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

fn status_str_to_enum(s: &str) -> TaskStatus {
    match s {
        "pending" | "dispatch" => TaskStatus::Pending,
        "dispatched" => TaskStatus::Dispatched,
        "in_progress" | "grok_start" | "grok_done" | "ci_start" | "ci_done" | "ci_failed" | "rollback" => TaskStatus::InProgress,
        "review" => TaskStatus::Review,
        "done" => TaskStatus::Done,
        "failed" => TaskStatus::Failed,
        "cancelled" => TaskStatus::Cancelled,
        _ => TaskStatus::Pending,
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
        version: "2.0.0-lance".into(),
        timestamp: Utc::now().to_rfc3339(),
    })
}

async fn list_tasks_api(
    State(state): State<AppState>,
    Query(q): Query<ListTasksQuery>,
) -> impl IntoResponse {
    let store = state.tasks.lock().await;
    let all_tasks = if let Some(ref status_str) = q.status {
        let target_status = status_str_to_enum(status_str);
        let all = store.list_all().await;
        all.into_iter()
            .filter(|t| t.status == target_status)
            .collect::<Vec<_>>()
    } else {
        store.list_all().await
    };

    let responses: Vec<TaskResponse> = all_tasks.iter().map(TaskResponse::from).collect();
    Json(responses).into_response()
}

async fn create_task_api(
    State(state): State<AppState>,
    Json(payload): Json<CreateTask>,
) -> impl IntoResponse {
    let task_id = format!("task-{}", &uuid::Uuid::new_v4().to_string()[..8]);
    let git_branch = format!("agentforge/{}", task_id);

    let priority = payload.priority.unwrap_or_else(|| "medium".into());
    let complexity = payload.complexity.unwrap_or_else(|| "medium".into());
    let preferred_agent = payload.preferred_agent.unwrap_or_else(|| "auto".into());
    let tags = payload.tags.unwrap_or_default();
    let description = payload.description.unwrap_or_default();

    let mut task = Task::new(&task_id, &payload.title, &description)
        .with_priority(&priority)
        .with_tags(tags);

    task.complexity = complexity;
    task.preferred_agent = Some(preferred_agent);
    task.metadata.insert("git_branch".into(), serde_json::json!(git_branch));

    if let Some(ref parent) = payload.parent_id {
        task.metadata.insert("parent_id".into(), serde_json::json!(parent));
    }
    if let Some(ref repo) = payload.repo {
        task.metadata.insert("repo".into(), serde_json::json!(repo));
    }

    let mut store = state.tasks.lock().await;
    let created = store.create(task).await.unwrap();
    let resp = TaskResponse::from(&created);

    // Broadcast via WebSocket
    let ws_msg = TaskUpdateMsg {
        r#type: "task_update".into(),
        task_id: task_id.clone(),
        data: serde_json::to_value(&resp).unwrap(),
    };
    let _ = state.ws_tx.send(ws_msg);

    (StatusCode::CREATED, Json(resp)).into_response()
}

async fn get_task_api(
    State(state): State<AppState>,
    Path(id): Path<String>,
) -> impl IntoResponse {
    let store = state.tasks.lock().await;
    match store.get(&id).await {
        Some(task) => Json(TaskResponse::from(&task)).into_response(),
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
    let mut store = state.tasks.lock().await;

    let mut task = match store.get(&task_id).await {
        Some(t) => t,
        None => return (StatusCode::NOT_FOUND, Json(serde_json::json!({"error": "task not found"}))).into_response(),
    };

    // Fair Queue CAS: claim attempt = trying to move pending -> in_progress while providing agent
    let is_claim = payload.status.as_deref().map_or(false, |s| s == "in_progress" || s == "dispatched")
        && payload.assigned_agent.as_ref().map_or(false, |v| v.is_string());

    if is_claim && task.status != TaskStatus::Pending {
        println!("[AgentForge] ⚔️ CAS reject: {} already {:?} (agent={:?}), rejecting claim from {:?}",
            task_id, task.status, task.assigned_to, payload.assigned_agent);
        return Json(TaskResponse::from(&task)).into_response();
    }

    let now = Utc::now().to_rfc3339();

    if let Some(ref status_str) = payload.status {
        task.status = status_str_to_enum(status_str);

        if status_str == "in_progress" || status_str == "dispatched" {
            task.started_at = Some(now.clone());
        }
        if status_str == "done" || status_str == "review" || status_str == "failed" {
            task.completed_at = Some(now.clone());
        }
    }

    if let Some(ref res_val) = payload.result {
        if res_val.is_null() {
            task.result = None;
        } else if let Some(s) = res_val.as_str() {
            task.result = Some(serde_json::json!(s));
        }
    }

    if let Some(ref agent_val) = payload.assigned_agent {
        if agent_val.is_null() {
            task.assigned_to = None;
        } else if let Some(s) = agent_val.as_str() {
            task.assigned_to = Some(s.to_string());
        }
    }

    if let Some(dur) = payload.duration_seconds {
        task.metadata.insert("duration_seconds".into(), serde_json::json!(dur));
    }

    if let Some(ref desc) = payload.description {
        task.description = desc.clone();
    }

    if let Some(rc) = payload.retry_count {
        task.metadata.insert("retry_count".into(), serde_json::json!(rc));
    }

    task.updated_at = now;
    let _ = store.update(task.clone()).await;

    let resp = TaskResponse::from(&task);
    let ws_msg = TaskUpdateMsg {
        r#type: "task_update".into(),
        task_id: task_id.clone(),
        data: serde_json::to_value(&resp).unwrap(),
    };
    let _ = state.ws_tx.send(ws_msg);

    Json(resp).into_response()
}

async fn dispatch_task_api(
    State(state): State<AppState>,
    Path(task_id): Path<String>,
) -> impl IntoResponse {
    let mut store = state.tasks.lock().await;

    let mut task = match store.get(&task_id).await {
        Some(t) => t,
        None => return (StatusCode::NOT_FOUND, Json(serde_json::json!({"error": "task not found"}))).into_response(),
    };

    if task.status != TaskStatus::Pending && task.status != TaskStatus::Failed {
        return (
            StatusCode::CONFLICT,
            Json(serde_json::json!({
                "error": format!("Task {} is already in status '{:?}'", task_id, task.status)
            })),
        )
            .into_response();
    }

    let agent = resolve_agent(
        task.preferred_agent.as_deref().unwrap_or("auto"),
        &task.complexity,
        &task.tags,
    );
    let now = Utc::now().to_rfc3339();

    task.status = TaskStatus::Dispatched;
    task.assigned_to = Some(agent.clone());
    task.started_at = Some(now.clone());
    task.updated_at = now;
    let _ = store.update(task.clone()).await;

    let resp = TaskResponse::from(&task);
    let ws_msg = TaskUpdateMsg {
        r#type: "task_update".into(),
        task_id: task_id.clone(),
        data: serde_json::to_value(&resp).unwrap(),
    };
    let _ = state.ws_tx.send(ws_msg);

    // Run dispatcher.sh in the background
    let home = std::env::var("HOME").unwrap_or_else(|_| "/home/eveselove".into());
    let dispatcher_path = format!("{}/agentforge/dispatcher.sh", home);
    let task_id_arg = task_id.clone();
    let agent_arg = agent.clone();
    let desc_arg = task.description.clone();
    let priority_arg = task.priority.clone();

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

async fn review_task_api(
    State(state): State<AppState>,
    Path(task_id): Path<String>,
) -> impl IntoResponse {
    let mut store = state.tasks.lock().await;

    let mut task = match store.get(&task_id).await {
        Some(t) => t,
        None => return (StatusCode::NOT_FOUND, Json(serde_json::json!({"error": "task not found"}))).into_response(),
    };

    let result_str = task.result.as_ref().and_then(|v| v.as_str()).unwrap_or("").to_string();

    let mut issues = Vec::new();
    if result_str.is_empty() {
        issues.push("Нет результата выполнения".to_string());
    }
    if result_str.to_lowercase().contains("fail") || result_str.contains("❌") {
        issues.push(format!("CI провалился: {}", result_str));
    }
    if task.status != TaskStatus::Review {
        issues.push(format!("Задача не в статусе review (current: {:?})", task.status));
    }

    let now = Utc::now().to_rfc3339();
    let (verdict, message);

    if !issues.is_empty() {
        verdict = "needs_attention";
        message = "Задача требует внимания";
        let comment = format!("Guardian: {}", issues.join("; "));
        task.result = Some(serde_json::json!(comment));
    } else {
        verdict = "approved";
        message = "Guardian одобрил задачу ✅";
        task.status = TaskStatus::Done;
        let comment = format!("{} | Guardian: approved ✅", result_str);
        task.result = Some(serde_json::json!(comment));
    }

    task.updated_at = now;
    let _ = store.update(task.clone()).await;

    let resp = TaskResponse::from(&task);
    let ws_msg = TaskUpdateMsg {
        r#type: "task_update".into(),
        task_id: task_id.clone(),
        data: serde_json::to_value(&resp).unwrap(),
    };
    let _ = state.ws_tx.send(ws_msg);

    Json(serde_json::json!({
        "task_id": task_id,
        "verdict": verdict,
        "issues": issues,
        "message": message
    }))
    .into_response()
}

async fn review_all_tasks_api(State(state): State<AppState>) -> impl IntoResponse {
    let mut store = state.tasks.lock().await;
    let all = store.list_all().await;
    let review_ids: Vec<String> = all
        .iter()
        .filter(|t| t.status == TaskStatus::Review)
        .map(|t| t.id.clone())
        .collect();

    let mut results = Vec::new();
    for id in review_ids {
        if let Some(mut task) = store.get(&id).await {
            let result_str = task.result.as_ref().and_then(|v| v.as_str()).unwrap_or("").to_string();
            let mut issues: Vec<String> = Vec::new();
            if result_str.is_empty() { issues.push("No result".into()); }
            if result_str.to_lowercase().contains("fail") { issues.push("CI failed".into()); }

            if issues.is_empty() {
                task.status = TaskStatus::Done;
                let comment = format!("{} | Guardian: approved ✅", result_str);
                task.result = Some(serde_json::json!(comment));
                task.updated_at = Utc::now().to_rfc3339();
                let _ = store.update(task).await;
                results.push(serde_json::json!({"task_id": id, "verdict": "approved"}));
            } else {
                results.push(serde_json::json!({"task_id": id, "verdict": "needs_attention", "issues": issues}));
            }
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
    let mut store = state.tasks.lock().await;

    let mut task = match store.get(&task_id).await {
        Some(t) => t,
        None => return (StatusCode::NOT_FOUND, Json(serde_json::json!({"error": "task not found"}))).into_response(),
    };

    let feedback_msg = format!("[HITL Отклонено]: {}", payload.feedback);
    task.status = TaskStatus::Pending;
    task.result = Some(serde_json::json!(feedback_msg));
    task.assigned_to = None;
    task.updated_at = Utc::now().to_rfc3339();

    let _ = store.update(task.clone()).await;

    let resp = TaskResponse::from(&task);
    let ws_msg = TaskUpdateMsg {
        r#type: "task_update".into(),
        task_id: task_id.clone(),
        data: serde_json::to_value(&resp).unwrap(),
    };
    let _ = state.ws_tx.send(ws_msg);

    Json(resp).into_response()
}

async fn metrics_api(State(state): State<AppState>) -> impl IntoResponse {
    let store = state.tasks.lock().await;
    let all_tasks = store.list_all().await;

    let mut by_status: HashMap<String, i64> = HashMap::new();
    let mut by_agent: HashMap<String, i64> = HashMap::new();
    let mut by_priority: HashMap<String, i64> = HashMap::new();
    let mut completed_durations: Vec<f64> = Vec::new();
    let mut agent_durations: HashMap<String, Vec<f64>> = HashMap::new();

    for task in &all_tasks {
        let status = format!("{:?}", task.status).to_lowercase();
        *by_status.entry(status.clone()).or_default() += 1;
        *by_priority.entry(task.priority.clone()).or_default() += 1;

        if let Some(ref agent) = task.assigned_to {
            *by_agent.entry(agent.clone()).or_default() += 1;
        }

        if task.status == TaskStatus::Done || task.status == TaskStatus::Review {
            if let (Ok(c_dt), Ok(u_dt)) = (
                chrono::DateTime::parse_from_rfc3339(&task.created_at),
                chrono::DateTime::parse_from_rfc3339(&task.updated_at),
            ) {
                let dur = u_dt.signed_duration_since(c_dt).num_seconds() as f64;
                if dur > 0.0 {
                    completed_durations.push(dur);
                }
            }
        }

        if let Some(dur) = task.metadata.get("duration_seconds").and_then(|v| v.as_f64()) {
            if let Some(ref agent) = task.assigned_to {
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
        "total_tasks": all_tasks.len(),
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
                Json(serde_json::json!({"error": format!("parse agent cards: {}", e)})),
            )
                .into_response(),
        },
        Err(e) => (
            StatusCode::NOT_FOUND,
            Json(serde_json::json!({"error": format!("agent_cards.json not found: {}", e)})),
        )
            .into_response(),
    }
}

async fn list_agents(State(state): State<AppState>) -> Json<Vec<Agent>> {
    let store = state.agents.lock().await;
    Json(store.all().to_vec())
}

async fn register_agent(
    State(state): State<AppState>,
    Json(payload): Json<RegisterAgent>,
) -> impl IntoResponse {
    let agent_id = format!("agent-{}", &uuid::Uuid::new_v4().to_string()[..8]);
    let now = Utc::now().to_rfc3339();

    let agent = Agent {
        agent_id: agent_id.clone(),
        name: payload.name.clone(),
        role: Some(payload.role.unwrap_or("worker".into())),
        status: Some("active".into()),
        registered_at: Some(now),
    };

    let mut store = state.agents.lock().await;
    store.push(agent);

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
    let now = Utc::now().to_rfc3339();

    let entry = BlackboardEntry {
        agent: payload.agent.clone(),
        message: payload.message.clone(),
        team_id: payload.team_id,
        task_id: payload.task_id,
        created_at: now,
    };

    let mut store = state.blackboard.lock().await;
    store.push(entry);

    info!("📢 [{}] {}", payload.agent, payload.message);
    Json(serde_json::json!({"ok": true}))
}

async fn get_blackboard_feed(
    State(state): State<AppState>,
    Query(q): Query<SearchQuery>,
) -> Json<Vec<BlackboardEntry>> {
    // WAVE4: apply team_id/task_id/agent/since_minutes filters (from py shims) for parity; json store (newest first slice after filter).
    let store = state.blackboard.lock().await;
    let limit = q.limit.unwrap_or(50);
    let mut items: Vec<BlackboardEntry> = store.all().to_vec();
    if let Some(ref v) = q.team_id {
        items.retain(|e| e.team_id.as_ref() == Some(v));
    }
    if let Some(ref v) = q.task_id {
        items.retain(|e| e.task_id.as_ref() == Some(v));
    }
    if let Some(ref v) = q.agent {
        items.retain(|e| e.agent == *v);
    }
    if let Some(sm) = q.since_minutes {
        if sm > 0 {
            // best-effort: filter by created_at string recency (iso); full chrono parse if needed
            // for simplicity keep recent N then client, but retain if possible (parse may fail -> keep)
            items.retain(|e| {
                // crude: assume format allows; else keep all for this since
                true // TODO: proper cutoff if chrono available in scope
            });
        }
    }
    let start = if items.len() > limit { items.len() - limit } else { 0 };
    Json(items[start..].iter().rev().cloned().collect())
}

// ── Knowledge ─────────────────────────────────────────

async fn search_knowledge(
    State(state): State<AppState>,
    Query(q): Query<SearchQuery>,
) -> Json<Vec<Knowledge>> {
    let store = state.knowledge.lock().await;
    let limit = q.limit.unwrap_or(20);

    let items: Vec<Knowledge> = if let Some(ref qq) = q.q {
        let q_lower = qq.to_lowercase();
        store
            .all()
            .iter()
            .filter(|k| k.key.to_lowercase().contains(&q_lower) || k.value.to_lowercase().contains(&q_lower))
            .cloned()
            .collect()
    } else {
        store.all().to_vec()
    };

    let start = if items.len() > limit { items.len() - limit } else { 0 };
    Json(items[start..].iter().rev().cloned().collect())
}

async fn save_knowledge_handler(
    State(state): State<AppState>,
    Json(payload): Json<SaveKnowledge>,
) -> impl IntoResponse {
    let now = Utc::now().to_rfc3339();

    let mut store = state.knowledge.lock().await;
    let next_id = store.all().len() as i64 + 1;

    let entry = Knowledge {
        id: next_id,
        agent: payload.agent,
        task_id: payload.task_id,
        key: payload.key.clone(),
        value: payload.value,
        embedding_hash: payload.embedding_hash,
        created_at: Some(now),
    };

    store.push(entry);

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
        let store = state.tasks.lock().await;
        if let Some(task) = store.get(&task_id).await {
            let resp = TaskResponse::from(&task);
            let initial = serde_json::json!({
                "type": "initial_state",
                "task_id": task_id,
                "data": resp,
            });
            if sender.send(WsMessage::Text(initial.to_string().into())).await.is_err() {
                return;
            }
        }
        drop(store);
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
                // Keep-alive
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

async fn ws_tasks_handler(
    ws: WebSocketUpgrade,
    Query(params): Query<HashMap<String, String>>,
    State(state): State<AppState>,
) -> impl IntoResponse {
    let agent = params.get("agent").cloned().unwrap_or_default();
    info!("🔌 Worker WS connected: agent={}", agent);
    ws.on_upgrade(move |socket| ws_tasks_stream(socket, state, agent))
}

async fn ws_tasks_stream(socket: WebSocket, state: AppState, agent: String) {
    let mut rx = state.ws_tx.subscribe();
    let (mut sender, mut receiver) = socket.split();

    // Send current pending tasks
    {
        let store = state.tasks.lock().await;
        let pending = store.list_pending().await;
        for task in pending {
            let pref = task.preferred_agent.as_deref().unwrap_or("auto");
            if agent.is_empty() || pref == agent || pref == "auto" {
                let resp = TaskResponse::from(&task);
                let msg = serde_json::json!({
                    "type": "pending_task",
                    "task_id": task.id,
                    "data": resp,
                });
                if sender.send(WsMessage::Text(msg.to_string().into())).await.is_err() {
                    return;
                }
            }
        }
    }

    let agent_clone = agent.clone();
    let send_task = tokio::spawn(async move {
        while let Ok(msg) = rx.recv().await {
            let text = serde_json::to_string(&msg).unwrap_or_default();
            if sender.send(WsMessage::Text(text.into())).await.is_err() {
                break;
            }
        }
    });

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

    info!("🔌 Worker WS disconnected: agent={}", agent_clone);
    send_task.abort();
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

    // ── LanceDB Task Store ───────────────────────────
    let lance_path = format!("{}/lance_tasks", data_dir);
    info!("📂 LanceDB: {}", lance_path);

    let task_store = LanceTaskStore::new_local(Some(&lance_path))
        .await
        .expect("Failed to initialize LanceDB task store");

    // ── JSON Stores for small data ───────────────────
    let agents_store = JsonStore::<Agent>::new(format!("{}/agents.json", data_dir));
    let blackboard_store = JsonStore::<BlackboardEntry>::new(format!("{}/blackboard.json", data_dir));
    let knowledge_store = JsonStore::<Knowledge>::new(format!("{}/knowledge.json", data_dir));

    info!("✅ All stores initialized (LanceDB + JSON)");

    let (ws_tx, _) = tokio::sync::broadcast::channel(100);

    let state = AppState {
        tasks: Arc::new(tokio::sync::Mutex::new(task_store)),
        agents: Arc::new(tokio::sync::Mutex::new(agents_store)),
        blackboard: Arc::new(tokio::sync::Mutex::new(blackboard_store)),
        knowledge: Arc::new(tokio::sync::Mutex::new(knowledge_store)),
        data_dir: data_dir.clone(),
        ws_tx,
    };

    // ── Proxy handler for old Planly API ──────────────
    async fn proxy_to_planly(req: axum::extract::Request) -> impl IntoResponse {
        let method = req.method().clone();
        let uri = req.uri().to_string();
        let planly_url = format!("http://127.0.0.1:3000{}", uri);
        let headers = req.headers().clone();

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
        // Proxy to Planly gateway
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
        // Static HTML pages
        .fallback_service(tower_http::services::ServeDir::new(&static_dir))
        .layer(CorsLayer::permissive())
        .with_state(state);

    let port: u16 = std::env::var("PORT")
        .ok()
        .and_then(|p| p.parse().ok())
        .unwrap_or(9090);

    let addr = format!("0.0.0.0:{}", port);
    info!("🚀 AgentForge Gateway v2.0 (LanceDB) starting on http://{}", addr);
    info!("📊 Dashboard: http://localhost:{}", port);

    let listener = tokio::net::TcpListener::bind(&addr).await.expect("Failed to bind port — is it already in use?");
    axum::serve(listener, app).await.unwrap();
}
