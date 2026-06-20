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
use std::time::Instant;
use tower_http::cors::CorsLayer;
use tracing::{info, warn};
use futures::{sink::SinkExt, stream::StreamExt};
use rand::seq::SliceRandom;

// Re-export from agentforge-core
use agentforge_core::{LanceTaskStore, Task, TaskStatus, TaskStore};

mod task_cache;
use task_cache::{new_task_cache, SharedTaskCache};

// Кэш метрик с TTL — позволяет дашборду работать без зависания на Mutex<LanceTaskStore>.
// При 1490+ задачах list_all() занимает 24-30с (конкуренция grok-агентов за LanceDB).
// Кэш обновляется незаметно в фоне, читатели не блокируются.
const METRICS_CACHE_TTL_SECS: u64 = 3;

#[derive(Clone, Default)]
struct MetricsCache {
    payload: Option<serde_json::Value>,
    updated_at: Option<Instant>,
    refreshing: bool,
}

impl MetricsCache {
    fn is_fresh(&self) -> bool {
        self.updated_at
            .map(|t| t.elapsed().as_secs() < METRICS_CACHE_TTL_SECS)
            .unwrap_or(false)
    }
    fn is_usable(&self) -> bool {
        // Если есть хоть какие-то данные и им за 60с — всё равно отвечаем (как сталые данные пока DB занята)
        self.payload.is_some() && self.updated_at.map(|t| t.elapsed().as_secs() < 60).unwrap_or(false)
    }
}

// ═══════════════════════════════════════════════════════
//  Types
// ═══════════════════════════════════════════════════════

#[derive(Clone)]
struct AppState {
    // Tasks: LanceDB (встроенная поддержка конкурентной записи/чтения, глобальный лок больше не нужен)
    tasks: Arc<LanceTaskStore>,
    // Внутренний кэш всех задач с TTL и фоновым обновлением
    task_cache: SharedTaskCache,
    // Кэш метрик: читатели используют RwLock — не блокируют друг друга
    metrics_cache: Arc<tokio::sync::RwLock<MetricsCache>>,
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
    requires_agent_review: bool,
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
            requires_agent_review: t.requires_agent_review,
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
    requires_agent_review: Option<bool>,
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

/// Query params для POST /tasks/claim — атомарный захват задачи
#[derive(Debug, Deserialize)]
struct ClaimQuery {
    /// ID воркера (обязательно)
    agent: String,
    /// Фильтр по preferred_agent (опционально, default: берём auto/grok/пустые)
    #[serde(default)]
    preferred: Option<String>,
    /// Сколько задач забрать батчем (для снижения HTTP roundtrips). Default 1.
    #[serde(default)]
    count: Option<u32>,
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
    /// Ограничение количества возвращаемых задач (для пагинации)
    #[serde(default)]
    limit: Option<usize>,
    /// Смещение (для пагинации)
    #[serde(default)]
    offset: Option<usize>,
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
    // Jules-specific routing removed (JULES CLEANUP Task 3). See AGENTS.md: Jules writes code + opens PRs externally.
    // No aliases or special checks for "jules" remain here; unknown preferred falls through to default.
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

async fn get_tasks_cached(state: &AppState) -> Arc<Vec<Task>> {
    // === read path: never block caller on LanceDB under load ===
    {
        let cache = state.task_cache.read().await;
        let has_data = !cache.all.tasks.is_empty();
        if cache.all.is_fresh() || (cache.all.is_stale_ok() && has_data) {
            // kick background refresh if not fresh (stale-while-revalidate)
            if !cache.all.is_fresh() && !cache.refreshing {
                let state_clone = state.clone();
                tokio::spawn(async move {
                    refresh_tasks_cache(&state_clone).await;
                });
            }
            return cache.snapshot(); // Arc clone = 1 atomic op
        }
        if cache.refreshing && has_data {
            return cache.snapshot();
        }
    }

    // Cold start: sync fetch
    refresh_tasks_cache(state).await
}

async fn refresh_tasks_cache(state: &AppState) -> Arc<Vec<Task>> {
    {
        let mut c = state.task_cache.write().await;
        if c.refreshing {
            if !c.all.tasks.is_empty() {
                return c.snapshot();
            }
        }
        c.refreshing = true;
    }

    let tasks = {
        state.tasks.list_all().await
    };

    let snapshot = {
        let mut c = state.task_cache.write().await;
        c.set_tasks(tasks);
        c.refreshing = false;
        c.snapshot()
    };
    snapshot
}

async fn list_tasks_api(
    State(state): State<AppState>,
    Query(q): Query<ListTasksQuery>,
    headers: axum::http::HeaderMap,
) -> axum::response::Response {
    let all_tasks_arc = get_tasks_cached(&state).await;

    // ETag: cheap cache version = Arc pointer address + len (changes on every set_tasks)
    let etag = format!("\"{:p}-{}\"", Arc::as_ptr(&all_tasks_arc), all_tasks_arc.len());
    if let Some(inm) = headers.get(axum::http::header::IF_NONE_MATCH) {
        if inm.as_bytes() == etag.as_bytes() {
            return StatusCode::NOT_MODIFIED.into_response();
        }
    }

    // Фильтруем по индексам — не клонируем Task до последнего момента
    let mut indices: Vec<usize> = (0..all_tasks_arc.len())
        .filter(|&i| {
            if let Some(ref status_str) = q.status {
                let target = status_str_to_enum(status_str);
                all_tasks_arc[i].status == target
            } else {
                true
            }
        })
        .collect();

    let total_count = indices.len();

    // Сортируем индексы по updated_at (новые вначале)
    indices.sort_by(|&a, &b| all_tasks_arc[b].updated_at.cmp(&all_tasks_arc[a].updated_at));

    // Пагинация
    let offset = q.offset.unwrap_or(0);
    let limit = q.limit.unwrap_or(2000);

    // Создаём TaskResponse только для финального среза (200 из 1493)
    let responses: Vec<TaskResponse> = indices.into_iter()
        .skip(offset)
        .take(limit)
        .map(|i| TaskResponse::from(&all_tasks_arc[i]))
        .collect();

    let mut resp = Json(responses).into_response();
    resp.headers_mut().insert("X-Total-Count", total_count.to_string().parse().unwrap());
    resp.headers_mut().insert("X-Offset", offset.to_string().parse().unwrap());
    resp.headers_mut().insert("X-Limit", limit.to_string().parse().unwrap());
    resp.headers_mut().insert(axum::http::header::ETAG, etag.parse().unwrap());
    resp.headers_mut().insert(
        axum::http::header::ACCESS_CONTROL_EXPOSE_HEADERS,
        "X-Total-Count, X-Offset, X-Limit, ETag".parse().unwrap(),
    );
    resp
}

/// POST /tasks/claim — атомарный захват случайной pending задачи.
/// Один HTTP запрос вместо GET all + parse + PATCH.
/// Воркеру не нужно скачивать 186KB JSON — получает ровно одну задачу.
async fn claim_task_api(
    State(state): State<AppState>,
    Json(payload): Json<ClaimQuery>,
) -> axum::response::Response {
    let cached_tasks = get_tasks_cached(&state).await;

    // Собираем ID подходящих pending задач (клонируем чтобы не держать borrow)
    let mut candidate_ids: Vec<String> = cached_tasks
        .iter()
        .filter(|t| t.status == TaskStatus::Pending)
        .filter(|t| {
            let pref = t.preferred_agent.as_deref().unwrap_or("").to_lowercase();
            if let Some(ref wanted) = payload.preferred {
                pref.is_empty() || pref == "auto" || pref == wanted.to_lowercase()
            } else {
                pref.is_empty() || pref == "auto" || pref == "grok" || pref == "antigravity"
            }
        })
        .filter(|t| {
            let tags_lower: Vec<String> = t.tags.iter().map(|s| s.to_lowercase()).collect();
            !tags_lower.contains(&"build".to_string()) && !tags_lower.contains(&"compile".to_string())
        })
        .map(|t| t.id.clone())
        .collect();
    drop(cached_tasks); // освобождаем

    if candidate_ids.is_empty() {
        return (StatusCode::NO_CONTENT, Json(serde_json::json!({"error": "no pending tasks available"}))).into_response();
    }

    // Случайный выбор — предотвращает thundering herd
    candidate_ids.shuffle(&mut rand::rng());

    let n = payload.count.filter(|&c| c > 0).unwrap_or(1) as usize;

    // Пробуем захватить до N задач (батч) или 1 для обратной совместимости.
    // Для count=1 возвращаем объект как раньше; для count>1 — массив.
    let mut claimed: Vec<TaskResponse> = Vec::new();
    for task_id in candidate_ids.iter() {
        if claimed.len() >= n { break; }
        // Optimistic CAS: try to claim in-memory first
        let claimed_task = {
            let mut cache = state.task_cache.write().await;
            cache.try_claim(task_id, &payload.agent)
        };

        if let Some(task) = claimed_task {
            // Memory claim succeeded! We own this task now.
            // Asynchronously update LanceDB without any global lock
            let _ = state.tasks.update(task.clone()).await;

            let resp = TaskResponse::from(&task);
            let ws_msg = TaskUpdateMsg {
                r#type: "task_update".into(),
                task_id: task_id.clone(),
                data: serde_json::to_value(&resp).unwrap(),
            };
            let _ = state.ws_tx.send(ws_msg);

            claimed.push(resp);
        }
    }

    if claimed.is_empty() {
        // Все попытки провалились (высокий contention) или не смогли
        return (StatusCode::CONFLICT, Json(serde_json::json!({"error": "could not claim task, try again"}))).into_response();
    }

    if n <= 1 {
        Json(claimed.into_iter().next().unwrap()).into_response()
    } else {
        Json(claimed).into_response()
    }
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
        .with_tags(tags)
        .with_requires_agent_review(payload.requires_agent_review.unwrap_or(false));

    task.complexity = complexity;
    task.preferred_agent = Some(preferred_agent);
    task.metadata.insert("git_branch".into(), serde_json::json!(git_branch));

    if let Some(ref parent) = payload.parent_id {
        task.metadata.insert("parent_id".into(), serde_json::json!(parent));
    }
    if let Some(ref repo) = payload.repo {
        task.metadata.insert("repo".into(), serde_json::json!(repo));
    }

    let created = match state.tasks.create(task).await {
        Ok(t) => t,
        Err(e) => {
            eprintln!("Failed to create task in LanceDB: {}", e);
            return (
                StatusCode::INTERNAL_SERVER_ERROR,
                format!("Failed to create task: {}", e),
            ).into_response();
        }
    };
    let resp = TaskResponse::from(&created);

    // Update cache in-place (no invalidation — prevents thundering herd)
    {
        let mut cache = state.task_cache.write().await;
        cache.add_task(&created);
    }

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
    // Fast path via list cache (stale-while-revalidate 3s); fallback to direct Lance point-query (id filter)
    {
        let cached = get_tasks_cached(&state).await;
        if let Some(task) = cached.iter().find(|t| t.id == id) {
            return Json(TaskResponse::from(task)).into_response();
        }
    }
    // Fallback (e.g. brand new task before next refresh, or id not exist)
    match state.tasks.get(&id).await {
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
    let mut task = match state.tasks.get(&task_id).await {
        Some(t) => t,
        None => return (StatusCode::NOT_FOUND, Json(serde_json::json!({"error": "task not found"}))).into_response(),
    };

    // Fair Queue CAS: claim attempt = trying to move pending -> in_progress while providing agent
    let is_claim = payload.status.as_deref().map_or(false, |s| s == "in_progress" || s == "dispatched")
        && payload.assigned_agent.as_ref().map_or(false, |v| v.is_string());

    if is_claim && task.status != TaskStatus::Pending {
        warn!(task_id = %task_id, current_status = ?task.status, current_agent = ?task.assigned_to, rejected_agent = ?payload.assigned_agent, "CAS reject: task already claimed");
        return Json(TaskResponse::from(&task)).into_response();
    }

    let now = Utc::now().to_rfc3339();

    if let Some(ref status_str) = payload.status {
        let new_status = status_str_to_enum(status_str);

        if (new_status == TaskStatus::Review || new_status == TaskStatus::Done) 
            && task.status != new_status 
            && task.requires_agent_review 
        {
            // Auto-create review task
            let review_id = format!("task-{}", &uuid::Uuid::new_v4().to_string()[..8]);
            let review_title = format!("agent-review: {} {:.50}", task_id, task.description);
            let review_desc = format!(
                "MANDATORY agent-review for task {}.\nOriginal branch: agentforge/{}",
                task_id, task_id
            );
            
            let mut review_task = Task::new(&review_id, &review_title, &review_desc)
                .with_priority("high")
                .with_tags(vec!["agent-review".into(), "followup".into(), task_id.clone()]);
            review_task.preferred_agent = Some("auto".into());
            
            // We ignore errors here as it's best-effort auto-creation
            let _ = state.tasks.create(review_task).await;
        }

        task.status = new_status;

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
        } else {
            // Принимаем любой JSON (строки, объекты, массивы) — BUG-11 fix
            task.result = Some(res_val.clone());
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
    let _ = state.tasks.update(task.clone()).await;
    // compact_if_needed() moved to background timer — don't hold write lock on hot path

    // Update cache in-place (no invalidation — prevents thundering herd)
    {
        let mut cache = state.task_cache.write().await;
        cache.upsert_task(&task);
    }

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
    let mut task = {
        let c = get_tasks_cached(&state).await;
        match c.iter().find(|t| t.id == task_id).cloned() {
            Some(t) => t,
            None => return (StatusCode::NOT_FOUND, Json(serde_json::json!({"error": "task not found"}))).into_response(),
        }
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
    let _ = state.tasks.update(task.clone()).await;

    // Update cache in-place (no invalidation — prevents thundering herd)
    {
        let mut cache = state.task_cache.write().await;
        cache.upsert_task(&task);
    }

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
    let mut task = if let Some(t) = get_tasks_cached(&state).await.iter().find(|t| t.id == task_id).cloned() {
        t
    } else {
        match state.tasks.get(&task_id).await {
            Some(t) => t,
            None => return (StatusCode::NOT_FOUND, Json(serde_json::json!({"error": "task not found"}))).into_response(),
        }
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
    let _ = state.tasks.update(task.clone()).await;

    // Update cache in-place (no invalidation — prevents thundering herd)
    {
        let mut cache = state.task_cache.write().await;
        cache.upsert_task(&task);
    }

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
    // Используем кэш для получения списка, не держим write-lock всё время.
    let all = get_tasks_cached(&state).await;
    let review_ids: Vec<String> = all
        .iter()
        .filter(|t| t.status == TaskStatus::Review)
        .map(|t| t.id.clone())
        .collect();

    let mut results = Vec::new();
    for id in review_ids {
        if let Some(mut task) = state.tasks.get(&id).await {
            let result_str = task.result.as_ref().and_then(|v| v.as_str()).unwrap_or("").to_string();
            let mut issues: Vec<String> = Vec::new();
            if result_str.is_empty() { issues.push("No result".into()); }
            if result_str.to_lowercase().contains("fail") { issues.push("CI failed".into()); }

            if issues.is_empty() {
                task.status = TaskStatus::Done;
                let comment = format!("{} | Guardian: approved ✅", result_str);
                task.result = Some(serde_json::json!(comment));
                task.updated_at = Utc::now().to_rfc3339();
                let _ = state.tasks.update(task).await;
                results.push(serde_json::json!({"task_id": id, "verdict": "approved"}));
            } else {
                results.push(serde_json::json!({"task_id": id, "verdict": "needs_attention", "issues": issues}));
            }
        }
    }

    // Mark cache stale after bulk review (tasks already updated in LanceDB)
    {
        let mut cache = state.task_cache.write().await;
        cache.all.mark_stale();
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
    let mut task = match state.tasks.get(&task_id).await {
        Some(t) => t,
        None => return (StatusCode::NOT_FOUND, Json(serde_json::json!({"error": "task not found"}))).into_response(),
    };

    let feedback_msg = format!("[HITL Отклонено]: {}", payload.feedback);
    task.status = TaskStatus::Pending;
    task.result = Some(serde_json::json!(feedback_msg));
    task.assigned_to = None;
    task.updated_at = Utc::now().to_rfc3339();

    let _ = state.tasks.update(task.clone()).await;

    // Update cache in-place (no invalidation — prevents thundering herd)
    {
        let mut cache = state.task_cache.write().await;
        cache.upsert_task(&task);
    }

    let resp = TaskResponse::from(&task);
    let ws_msg = TaskUpdateMsg {
        r#type: "task_update".into(),
        task_id: task_id.clone(),
        data: serde_json::to_value(&resp).unwrap(),
    };
    let _ = state.ws_tx.send(ws_msg);

    Json(resp).into_response()
}

/// DELETE /tasks/{id} — удаление одной задачи
async fn delete_task_api(
    State(state): State<AppState>,
    Path(task_id): Path<String>,
) -> impl IntoResponse {
    // Удаляем из LanceDB
    match state.tasks.delete(&task_id).await {
        Ok(_) => {
            // Удаляем из кэша
            {
                let mut cache = state.task_cache.write().await;
                let mut tasks = (*cache.all.tasks).clone();
                tasks.retain(|t| t.id != task_id);
                cache.all.tasks = Arc::new(tasks);
                cache.all.mark_stale();
            }
            Json(serde_json::json!({"ok": true, "deleted": task_id})).into_response()
        }
        Err(e) => (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(serde_json::json!({"error": e})),
        ).into_response(),
    }
}

/// POST /tasks/purge — массовое удаление done/cancelled/failed задач
async fn purge_tasks_api(
    State(state): State<AppState>,
) -> impl IntoResponse {
    let cached = get_tasks_cached(&state).await;
    let to_delete: Vec<String> = cached.iter()
        .filter(|t| matches!(t.status, TaskStatus::Done | TaskStatus::Cancelled | TaskStatus::Failed))
        .map(|t| t.id.clone())
        .collect();
    
    let total = to_delete.len();
    let mut deleted = 0;
    
    for id in &to_delete {
        if state.tasks.delete(id).await.is_ok() {
            deleted += 1;
        }
    }
    
    // Обновляем кэш — оставляем только active
    {
        let mut cache = state.task_cache.write().await;
        let mut tasks = (*cache.all.tasks).clone();
        tasks.retain(|t| !matches!(t.status, TaskStatus::Done | TaskStatus::Cancelled | TaskStatus::Failed));
        cache.all.tasks = Arc::new(tasks);
        cache.all.mark_stale();
    }

    info!("🧹 Purge: deleted {}/{} tasks", deleted, total);
    Json(serde_json::json!({"purged": deleted, "total_found": total})).into_response()
}

async fn metrics_api(State(state): State<AppState>) -> impl IntoResponse {
    // === Кэш: мгновенный ответ если данные свежие ===
    {
        let cache = state.metrics_cache.read().await;
        if cache.is_fresh() {
            if let Some(ref v) = cache.payload {
                return Json(v.clone()).into_response();
            }
        }
        if cache.refreshing && cache.is_usable() {
            if let Some(ref v) = cache.payload {
                return Json(v.clone()).into_response();
            }
        }
    }
    { let mut c = state.metrics_cache.write().await; c.refreshing = true; }

    // === count_all_statuses() — один open_table() + 7 параллельных count_rows ===
    // Было: 7 отдельных count_by_status (7 × open_table = ~35ms).
    // Стало: 1 × open_table + 7 параллельных count_rows (~5ms).
    let counts = state.tasks.count_all_statuses().await;

    let n_pending = *counts.get("Pending").unwrap_or(&0);
    let n_dispatched = *counts.get("Dispatched").unwrap_or(&0);
    let n_inprog = *counts.get("InProgress").unwrap_or(&0);
    let n_review = *counts.get("Review").unwrap_or(&0);
    let n_done = *counts.get("Done").unwrap_or(&0);
    let n_failed = *counts.get("Failed").unwrap_or(&0);
    let n_cancelled = *counts.get("Cancelled").unwrap_or(&0);

    let total = n_pending + n_dispatched + n_inprog + n_review + n_done + n_failed + n_cancelled;

    let result = serde_json::json!({
        "total_tasks": total,
        "by_status": {
            "pending":    n_pending,
            "dispatched": n_dispatched,
            "inprogress": n_inprog,
            "review":     n_review,
            "done":       n_done,
            "failed":     n_failed,
            "cancelled":  n_cancelled,
        },
        "timestamp": Utc::now().to_rfc3339()
    });

    {
        let mut cache = state.metrics_cache.write().await;
        cache.payload = Some(result.clone());
        cache.updated_at = Some(Instant::now());
        cache.refreshing = false;
    }

    Json(result).into_response()
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
        if let Some(task) = state.tasks.get(&task_id).await {
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

    // Send current pending tasks (via cache to avoid extra Lance scan + contention)
    {
        let all = get_tasks_cached(&state).await;
        let mut pending: Vec<_> = all.iter()
            .filter(|t| t.status == TaskStatus::Pending)
            .cloned()
            .collect();
        pending.sort_by(|a, b| {
            let prio = |p: &str| match p {
                "critical" => 0,
                "high" => 1,
                "medium" => 2,
                _ => 3,
            };
            prio(&a.priority).cmp(&prio(&b.priority))
        });
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
        tasks: Arc::new(task_store),
        task_cache: new_task_cache(),
        metrics_cache: Arc::new(tokio::sync::RwLock::new(MetricsCache::default())),
        agents: Arc::new(tokio::sync::Mutex::new(agents_store)),
        blackboard: Arc::new(tokio::sync::Mutex::new(blackboard_store)),
        knowledge: Arc::new(tokio::sync::Mutex::new(knowledge_store)),
        data_dir: data_dir.clone(),
        ws_tx,
    };

    // Pre-warm task list cache in background so first /tasks requests are never cold (no 25s delay on restart)
    {
        let state_prewarm = state.clone();
        tokio::spawn(async move {
            // fire and forget; ignore result
            let _ = get_tasks_cached(&state_prewarm).await;
            // also touch metrics (uses fast counts)
            let _ = metrics_api(State(state_prewarm)).await;
        });
    }

    // ── Background LanceDB compaction (every 5 min) ──
    {
        let state_compact = state.clone();
        tokio::spawn(async move {
            loop {
                tokio::time::sleep(std::time::Duration::from_secs(300)).await;
                state_compact.tasks.compact_if_needed().await;
                info!("🗜️ Background compaction tick");
            }
        });
    }

    // ── Background zombie reclaimer for stuck in_progress (FIX-01) ──
    // Problem: worker death (OOM, rate-limit, network) leaves task in InProgress forever -> leakage.
    // Solution: bg tokio::spawn (placed next to compaction) that returns stale in_progress -> pending.
    {
        let state_zombie = state.clone();
        tokio::spawn(async move {
            let timeout_mins: i64 = std::env::var("ZOMBIE_TIMEOUT_MINUTES")
                .ok()
                .and_then(|s| s.parse().ok())
                .unwrap_or(25);
            let timeout_secs = timeout_mins * 60;
            loop {
                tokio::time::sleep(std::time::Duration::from_secs(60)).await;
                let inprog = state_zombie.tasks.list_by_status(&TaskStatus::InProgress).await;
                if inprog.is_empty() {
                    continue;
                }
                let now = Utc::now();
                for mut t in inprog {
                    if let Ok(updated) = chrono::DateTime::parse_from_rfc3339(&t.updated_at) {
                        let age = now.timestamp() - updated.timestamp();
                        if age > timeout_secs {
                            warn!(
                                task_id = %t.id,
                                assigned = ?t.assigned_to,
                                age_min = age / 60,
                                timeout = timeout_mins,
                                "FIX-01 zombie: returning stuck in_progress task to pending"
                            );
                            t.status = TaskStatus::Pending;
                            t.assigned_to = None;
                            let rc = t.metadata.get("retry_count")
                                .and_then(|v| v.as_i64())
                                .unwrap_or(0) + 1;
                            t.metadata.insert("retry_count".into(), serde_json::json!(rc));
                            t.metadata.insert("zombie_reclaimed".into(), serde_json::json!(true));
                            t.metadata.insert("reclaimed_at".into(), serde_json::json!(now.to_rfc3339()));
                            t.updated_at = now.to_rfc3339();
                            if let Err(e) = state_zombie.tasks.update(t.clone()).await {
                                warn!(task_id = %t.id, "zombie update err: {}", e);
                            } else {
                                // keep cache coherent
                                let mut c = state_zombie.task_cache.write().await;
                                c.upsert_task(&t);
                            }
                        }
                    }
                }
            }
        });
    }

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
        .route("/claim", post(claim_task_api))
        .route("/api/claim", post(claim_task_api))
        .route("/tasks/{id}", get(get_task_api).patch(update_task_api).delete(delete_task_api))
        .route("/api/tasks/{id}", get(get_task_api).patch(update_task_api).delete(delete_task_api))
        .route("/tasks/{id}/dispatch", post(dispatch_task_api))
        .route("/api/tasks/{id}/dispatch", post(dispatch_task_api))
        .route("/tasks/{id}/review", post(review_task_api))
        .route("/api/tasks/{id}/review", post(review_task_api))
        .route("/tasks/{id}/reject", post(reject_task_api))
        .route("/api/tasks/{id}/reject", post(reject_task_api))
        .route("/review/all", post(review_all_tasks_api))
        .route("/api/review/all", post(review_all_tasks_api))
        .route("/tasks/purge", post(purge_tasks_api))
        .route("/api/tasks/purge", post(purge_tasks_api))
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
