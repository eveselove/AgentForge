/// In-memory task cache with TTL and Arc-based zero-copy reads.
///
/// ## Архитектура
///
/// Кэш хранит `Arc<Vec<Task>>` — читатели получают дешёвый clone Arc (1 atomic op)
/// вместо deep clone всего Vec<Task> (1493 задач × 10 String полей = ~15KB аллокаций).
///
/// Подход: read-through cache со stale-while-revalidate семантикой.
/// При мутациях (PATCH/POST) обновляем задачу in-place и создаём новый Arc.
/// Старые Arc остаются валидны для текущих читателей (lock-free reads).

use std::collections::HashMap;
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::sync::RwLock;

use agentforge_core::Task;

/// TTL кэша: данные считаются «свежими» 3 секунды.
pub const CACHE_TTL_SECS: u64 = 3;
/// Максимальный возраст данных при «stale» режиме: 300 секунд (5 мин).
pub const CACHE_STALE_SECS: u64 = 300;

#[derive(Clone)]
pub struct TaskCacheEntry {
    /// Arc-обёрнутый вектор — clone = 1 atomic increment (~1ns), не deep copy (~15μs)
    pub tasks: Arc<Vec<Task>>,
    pub updated_at: Option<Instant>,
}

impl Default for TaskCacheEntry {
    fn default() -> Self {
        Self {
            tasks: Arc::new(Vec::new()),
            updated_at: None,
        }
    }
}

impl TaskCacheEntry {
    pub fn is_fresh(&self) -> bool {
        self.updated_at
            .map(|t| t.elapsed() < Duration::from_secs(CACHE_TTL_SECS))
            .unwrap_or(false)
    }

    pub fn is_stale_ok(&self) -> bool {
        self.updated_at
            .map(|t| t.elapsed() < Duration::from_secs(CACHE_STALE_SECS))
            .unwrap_or(false)
    }

    /// Пометить кэш как "нужен фоновый рефреш" без потери данных.
    pub fn mark_stale(&mut self) {
        if self.updated_at.is_some() {
            self.updated_at = Some(Instant::now() - Duration::from_secs(CACHE_TTL_SECS + 1));
        }
    }
}

/// Глобальный кэш всех задач.
pub struct TaskCache {
    pub all: TaskCacheEntry,
    /// Флаг что обновление уже запущено в фоне
    pub refreshing: bool,
    /// O(1) lookup id -> index in the tasks vec. Rebuilt on set_tasks, updated on add/upsert.
    id_index: HashMap<String, usize>,
}

impl Default for TaskCache {
    fn default() -> Self {
        Self {
            all: TaskCacheEntry::default(),
            refreshing: false,
            id_index: HashMap::new(),
        }
    }
}

impl TaskCache {
    /// Обновить задачу in-place — создаёт новый Arc (старые читатели не затронуты).
    pub fn upsert_task(&mut self, task: &Task) {
        let mut tasks = (*self.all.tasks).clone(); // cow: clone-on-write
        if let Some(&pos) = self.id_index.get(&task.id) {
            tasks[pos] = task.clone();
        } else {
            let pos = tasks.len();
            tasks.push(task.clone());
            self.id_index.insert(task.id.clone(), pos);
        }
        self.all.tasks = Arc::new(tasks);
        self.all.mark_stale();
    }

    /// Добавить новую задачу.
    pub fn add_task(&mut self, task: &Task) {
        let mut tasks = (*self.all.tasks).clone();
        let pos = tasks.len();
        tasks.push(task.clone());
        self.id_index.insert(task.id.clone(), pos);
        self.all.tasks = Arc::new(tasks);
        self.all.mark_stale();
    }

    /// Заменить весь кэш данными из DB.
    pub fn set_tasks(&mut self, tasks: Vec<Task>) {
        let mut index = HashMap::with_capacity(tasks.len());
        for (i, t) in tasks.iter().enumerate() {
            index.insert(t.id.clone(), i);
        }
        self.all.tasks = Arc::new(tasks);
        self.all.updated_at = Some(Instant::now());
        self.id_index = index;
    }

    /// Дешёвый snapshot: Arc clone = 1 atomic op.
    pub fn snapshot(&self) -> Arc<Vec<Task>> {
        Arc::clone(&self.all.tasks)
    }

    /// Оптимистичный захват задачи в памяти.
    /// Возвращает обновленную задачу, если она была Pending и мы ее успешно захватили.
    pub fn try_claim(&mut self, task_id: &str, agent: &str) -> Option<Task> {
        let mut tasks = (*self.all.tasks).clone();
        if let Some(&pos) = self.id_index.get(task_id) {
            if tasks[pos].status == agentforge_core::TaskStatus::Pending {
                tasks[pos].status = agentforge_core::TaskStatus::InProgress;
                tasks[pos].assigned_to = Some(agent.to_string());
                let now = chrono::Utc::now().to_rfc3339();
                tasks[pos].started_at = Some(now.clone());
                tasks[pos].updated_at = now;
                
                let result = tasks[pos].clone();
                self.all.tasks = Arc::new(tasks);
                self.all.mark_stale();
                return Some(result);
            }
        }
        None
    }
}

pub type SharedTaskCache = Arc<RwLock<TaskCache>>;

pub fn new_task_cache() -> SharedTaskCache {
    Arc::new(RwLock::new(TaskCache::default()))
}
