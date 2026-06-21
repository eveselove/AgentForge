//! LanceDB-backed TaskStore implementation.
//!
//! This is the intended modern replacement for SQLite-based task storage.
//!
//! ## Usage
//! This module is only available when the `lancedb` feature is enabled:
//! ```toml
//! [dependencies]
//! agentforge-core = { ..., features = ["lancedb"] }
//! ```

use crate::task::{Task, TaskStatus, TaskStore};
use anyhow::Result;
use arrow_array::{Array, ArrayRef, BooleanArray, RecordBatch, RecordBatchIterator, StringArray};
use arrow_schema::{DataType, Field, Schema};
use lancedb::query::{ExecutableQuery, QueryBase};
use std::sync::atomic::{AtomicU32, Ordering};
use std::sync::Arc;
use tokio::sync::RwLock;

pub struct LanceTaskStore {
    db: lancedb::Connection,
    table_name: String,
    /// Кэш table handle — открываем таблицу один раз, не на каждый запрос.
    /// open_table() из LanceDB проверяет манифест на диске каждый раз (~2-5ms).
    /// При 10 воркерах × 3 open/update = 30 open_table/сек → 60-150ms overhead.
    cached_table: RwLock<Option<lancedb::Table>>,
    /// Счётчик операций записи — для автокомпакции фрагментов после N изменений
    update_count: Arc<AtomicU32>,
}

fn task_schema() -> Arc<Schema> {
    Arc::new(Schema::new(vec![
        Field::new("id", DataType::Utf8, false),
        Field::new("title", DataType::Utf8, false),
        Field::new("description", DataType::Utf8, true),
        Field::new("priority", DataType::Utf8, false),
        Field::new("complexity", DataType::Utf8, false),
        Field::new("preferred_agent", DataType::Utf8, true),
        Field::new("assigned_to", DataType::Utf8, true),
        Field::new("status", DataType::Utf8, false),
        Field::new("tags_json", DataType::Utf8, true),
        Field::new("requires_agent_review", DataType::Boolean, false),
        Field::new("created_at", DataType::Utf8, false),
        Field::new("updated_at", DataType::Utf8, false),
        Field::new("started_at", DataType::Utf8, true),
        Field::new("completed_at", DataType::Utf8, true),
        Field::new("metadata_json", DataType::Utf8, true),
        Field::new("result_json", DataType::Utf8, true),
    ]))
}

fn task_to_batch(task: &Task) -> Result<RecordBatch> {
    let tags_json = serde_json::to_string(&task.tags).unwrap_or("[]".into());
    let metadata_json = serde_json::to_string(&task.metadata).unwrap_or("{}".into());
    let result_json = task
        .result
        .as_ref()
        .map(|r| r.to_string())
        .unwrap_or_default();
    let status_str = format!("{:?}", task.status);

    RecordBatch::try_from_iter(vec![
        (
            "id",
            Arc::new(StringArray::from(vec![task.id.as_str()])) as ArrayRef,
        ),
        (
            "title",
            Arc::new(StringArray::from(vec![task.title.as_str()])) as ArrayRef,
        ),
        (
            "description",
            Arc::new(StringArray::from(vec![task.description.as_str()])) as ArrayRef,
        ),
        (
            "priority",
            Arc::new(StringArray::from(vec![task.priority.as_str()])) as ArrayRef,
        ),
        (
            "complexity",
            Arc::new(StringArray::from(vec![task.complexity.as_str()])) as ArrayRef,
        ),
        (
            "preferred_agent",
            Arc::new(StringArray::from(vec![task
                .preferred_agent
                .as_deref()
                .unwrap_or("")])) as ArrayRef,
        ),
        (
            "assigned_to",
            Arc::new(StringArray::from(vec![task
                .assigned_to
                .as_deref()
                .unwrap_or("")])) as ArrayRef,
        ),
        (
            "status",
            Arc::new(StringArray::from(vec![status_str.as_str()])) as ArrayRef,
        ),
        (
            "tags_json",
            Arc::new(StringArray::from(vec![tags_json.as_str()])) as ArrayRef,
        ),
        (
            "requires_agent_review",
            Arc::new(BooleanArray::from(vec![task.requires_agent_review])) as ArrayRef,
        ),
        (
            "created_at",
            Arc::new(StringArray::from(vec![task.created_at.as_str()])) as ArrayRef,
        ),
        (
            "updated_at",
            Arc::new(StringArray::from(vec![task.updated_at.as_str()])) as ArrayRef,
        ),
        (
            "started_at",
            Arc::new(StringArray::from(vec![task
                .started_at
                .as_deref()
                .unwrap_or("")])) as ArrayRef,
        ),
        (
            "completed_at",
            Arc::new(StringArray::from(vec![task
                .completed_at
                .as_deref()
                .unwrap_or("")])) as ArrayRef,
        ),
        (
            "metadata_json",
            Arc::new(StringArray::from(vec![metadata_json.as_str()])) as ArrayRef,
        ),
        (
            "result_json",
            Arc::new(StringArray::from(vec![result_json.as_str()])) as ArrayRef,
        ),
    ])
    .map_err(|e| anyhow::anyhow!(e))
}

fn batch_to_tasks(batch: &RecordBatch) -> Vec<Task> {
    let ids = batch
        .column_by_name("id")
        .and_then(|c| c.as_any().downcast_ref::<StringArray>());
    let titles = batch
        .column_by_name("title")
        .and_then(|c| c.as_any().downcast_ref::<StringArray>());
    let descs = batch
        .column_by_name("description")
        .and_then(|c| c.as_any().downcast_ref::<StringArray>());
    let priorities = batch
        .column_by_name("priority")
        .and_then(|c| c.as_any().downcast_ref::<StringArray>());
    let complexities = batch
        .column_by_name("complexity")
        .and_then(|c| c.as_any().downcast_ref::<StringArray>());
    let pref_agents = batch
        .column_by_name("preferred_agent")
        .and_then(|c| c.as_any().downcast_ref::<StringArray>());
    let assigned = batch
        .column_by_name("assigned_to")
        .and_then(|c| c.as_any().downcast_ref::<StringArray>());
    let statuses = batch
        .column_by_name("status")
        .and_then(|c| c.as_any().downcast_ref::<StringArray>());
    let tags = batch
        .column_by_name("tags_json")
        .and_then(|c| c.as_any().downcast_ref::<StringArray>());
    let requires_review = batch
        .column_by_name("requires_agent_review")
        .and_then(|c| c.as_any().downcast_ref::<BooleanArray>());
    let created = batch
        .column_by_name("created_at")
        .and_then(|c| c.as_any().downcast_ref::<StringArray>());
    let updated = batch
        .column_by_name("updated_at")
        .and_then(|c| c.as_any().downcast_ref::<StringArray>());
    let started = batch
        .column_by_name("started_at")
        .and_then(|c| c.as_any().downcast_ref::<StringArray>());
    let completed = batch
        .column_by_name("completed_at")
        .and_then(|c| c.as_any().downcast_ref::<StringArray>());
    let meta = batch
        .column_by_name("metadata_json")
        .and_then(|c| c.as_any().downcast_ref::<StringArray>());
    let results = batch
        .column_by_name("result_json")
        .and_then(|c| c.as_any().downcast_ref::<StringArray>());

    let n = batch.num_rows();
    let mut tasks = Vec::with_capacity(n);

    for i in 0..n {
        let get_str = |arr: Option<&StringArray>| -> String {
            arr.and_then(|a| (!a.is_null(i)).then(|| a.value(i).to_string()))
                .unwrap_or_default()
        };
        let get_opt = |arr: Option<&StringArray>| -> Option<String> {
            arr.and_then(|a| (!a.is_null(i)).then(|| a.value(i)))
                .filter(|s| !s.is_empty())
                .map(|s| s.to_string())
        };

        let status_str = get_str(statuses);
        let status = match status_str.as_str() {
            "Pending" => TaskStatus::Pending,
            "Dispatched" => TaskStatus::Dispatched,
            "InProgress" => TaskStatus::InProgress,
            "Review" => TaskStatus::Review,
            "Done" => TaskStatus::Done,
            "Failed" => TaskStatus::Failed,
            "Cancelled" => TaskStatus::Cancelled,
            _ => TaskStatus::Pending,
        };

        let tags_vec: Vec<String> = serde_json::from_str(&get_str(tags)).unwrap_or_default();
        let requires_agent_review = requires_review
            .and_then(|a| (!a.is_null(i)).then(|| a.value(i)))
            .unwrap_or(false);
        let metadata_map = serde_json::from_str(&get_str(meta)).unwrap_or_default();
        let result_val = get_opt(results).and_then(|s| serde_json::from_str(&s).ok());

        tasks.push(Task {
            id: get_str(ids),
            title: get_str(titles),
            description: get_str(descs),
            priority: get_str(priorities),
            complexity: get_str(complexities),
            preferred_agent: get_opt(pref_agents),
            assigned_to: get_opt(assigned),
            status,
            tags: tags_vec,
            requires_agent_review,
            created_at: get_str(created),
            updated_at: get_str(updated),
            started_at: get_opt(started),
            completed_at: get_opt(completed),
            metadata: metadata_map,
            result: result_val,
        });
    }

    tasks
}

impl LanceTaskStore {
    /// Connect to local LanceDB and open/create tasks table.
    pub async fn new_local(path: Option<impl Into<std::path::PathBuf>>) -> Result<Self> {
        let path = path
            .map(|p| p.into())
            .unwrap_or_else(|| std::path::PathBuf::from("./data/lance_tasks"));

        std::fs::create_dir_all(&path)?;

        let db = lancedb::connect(path.to_str().unwrap()).execute().await?;

        // Create table if not exists
        let table_name = "tasks".to_string();
        let table_names = db.table_names().execute().await?;
        if !table_names.contains(&table_name) {
            let schema = task_schema();
            let empty = RecordBatch::new_empty(schema.clone());
            let batches = RecordBatchIterator::new(vec![Ok(empty)], schema);
            db.create_table(&table_name, Box::new(batches))
                .execute()
                .await?;
        }

        let store = Self {
            db,
            table_name,
            cached_table: RwLock::new(None),
            update_count: Arc::new(AtomicU32::new(0)),
        };
        // Pre-warm table handle
        let _ = store.open_table().await;

        // === Schema migration: добавляем колонки, которых нет в старой таблице ===
        // LanceDB не поддерживает append/merge_insert с полями, отсутствующими в таблице.
        // Если таблица создана до добавления requires_agent_review — добавляем колонку.
        if let Ok(table) = store.open_table().await {
            if let Ok(schema) = table.schema().await {
                if schema.column_with_name("requires_agent_review").is_none() {
                    eprintln!("[LanceDB] Schema migration: adding 'requires_agent_review' column");
                    let result = table
                        .add_columns(
                            lancedb::table::NewColumnTransform::SqlExpressions(vec![(
                                "requires_agent_review".to_string(),
                                "false".to_string(),
                            )]),
                            None,
                        )
                        .await;
                    match result {
                        Ok(_) => {
                            eprintln!("[LanceDB] Schema migration OK: requires_agent_review added")
                        }
                        Err(e) => eprintln!("[LanceDB] Schema migration error: {}", e),
                    }
                    // Инвалидируем кэш после миграции — манифест изменился
                    store.invalidate_table_cache().await;
                }
            }
        }

        // Scalar indices: ускоряют merge_insert (id lookup) и count_by_status (status filter)
        // BTree на id: merge_insert O(log N) вместо O(N) full scan
        // BTree на status: count_rows с фильтром ~0.1ms вместо ~1ms
        if let Ok(table) = store.open_table().await {
            // Индексы идемпотентны — ошибка "already exists" игнорируется
            let _ = table
                .create_index(&["id"], lancedb::index::Index::BTree(Default::default()))
                .execute()
                .await;
            let _ = table
                .create_index(
                    &["status"],
                    lancedb::index::Index::BTree(Default::default()),
                )
                .execute()
                .await;
        }
        Ok(store)
    }

    /// Открывает таблицу с кэшированием handle.
    /// Первый вызов: ~5ms (чтение манифеста). Последующие: <0.01ms (из памяти).
    /// Инвалидация: после compact_if_needed() или при ошибке.
    async fn open_table(&self) -> Result<lancedb::Table> {
        // Быстрый путь: read lock, проверяем кэш
        {
            let cached = self.cached_table.read().await;
            if let Some(ref table) = *cached {
                return Ok(table.clone());
            }
        }
        // Медленный путь: открываем и кэшируем
        let table = self.db.open_table(&self.table_name).execute().await?;
        {
            let mut cached = self.cached_table.write().await;
            *cached = Some(table.clone());
        }
        Ok(table)
    }

    /// Инвалидировать кэш table handle (после compaction или при ошибках)
    async fn invalidate_table_cache(&self) {
        let mut cached = self.cached_table.write().await;
        *cached = None;
    }

    async fn query_all_tasks(&self, filter: Option<&str>) -> Vec<Task> {
        let table = match self.open_table().await {
            Ok(t) => t,
            Err(_) => return vec![],
        };

        let batches = if let Some(f) = filter {
            match table.query().only_if(f).limit(100000).execute().await {
                Ok(stream) => {
                    use futures::TryStreamExt;
                    stream.try_collect::<Vec<_>>().await.unwrap_or_default()
                }
                Err(_) => return vec![],
            }
        } else {
            match table.query().limit(100000).execute().await {
                Ok(stream) => {
                    use futures::TryStreamExt;
                    stream.try_collect::<Vec<_>>().await.unwrap_or_default()
                }
                Err(_) => return vec![],
            }
        };

        batches.iter().flat_map(|b| batch_to_tasks(b)).collect()
    }

    /// Быстрый пуш-даун фильтр по статусу внутри LanceDB.
    /// Не загружает все задачи перед фильтрацией — DB фильтрует сама на уровне фрагментов.
    pub async fn list_by_status(&self, status: &TaskStatus) -> Vec<Task> {
        let status_str = format!("{:?}", status); // формат: "Pending", "Done" и т.д.
        let filter = format!("status = '{}'", status_str);
        self.query_all_tasks(Some(&filter)).await
    }

    /// Мгновенный подсчёт через count_rows() — не загружает данные.
    pub async fn count_by_status(&self, status: &TaskStatus) -> usize {
        let table = match self.open_table().await {
            Ok(t) => t,
            Err(_) => return 0,
        };
        let filter = format!("status = '{:?}'", status);
        table.count_rows(Some(filter)).await.unwrap_or(0) as usize
    }

    /// Реальная компакция LanceDB: объединяет мелкие фрагменты от update/delete.
    /// При 1500 задачах и 10 воркерах = ~100 фрагментов/5мин.
    /// После компакции: query ~1ms вместо ~5ms (меньше файлов для чтения).
    pub async fn compact_if_needed(&self) {
        let count = self.update_count.fetch_add(1, Ordering::Relaxed);
        // Компакция каждые 50 операций записи
        if count % 50 != 0 && count > 0 {
            return;
        }
        if let Ok(table) = self.open_table().await {
            match table.optimize(lancedb::table::OptimizeAction::All).await {
                Ok(stats) => {
                    eprintln!("[LanceDB] Compaction OK: {:?}", stats.compaction);
                }
                Err(e) => {
                    eprintln!("[LanceDB] Compaction error: {}", e);
                }
            }
        }
        // Инвалидируем кэш — после компакции манифест изменился
        self.invalidate_table_cache().await;
    }

    /// Batch count: один open_table() вместо 7 отдельных.
    /// Для /api/metrics — 7x быстрее чем 7 отдельных count_by_status().
    pub async fn count_all_statuses(&self) -> std::collections::HashMap<String, usize> {
        let table = match self.open_table().await {
            Ok(t) => t,
            Err(_) => return std::collections::HashMap::new(),
        };
        let statuses = [
            "Pending",
            "Dispatched",
            "InProgress",
            "Review",
            "Done",
            "Failed",
            "Cancelled",
        ];
        let mut result = std::collections::HashMap::new();
        // Параллельно 7 count_rows на том же table handle (не открываем заново)
        let futures: Vec<_> = statuses
            .iter()
            .map(|s| {
                let t = table.clone();
                let filter = format!("status = '{}'", s);
                async move {
                    let count = t.count_rows(Some(filter)).await.unwrap_or(0) as usize;
                    (s.to_string(), count)
                }
            })
            .collect();
        let counts = futures::future::join_all(futures).await;
        for (status, count) in counts {
            result.insert(status, count);
        }
        result
    }
}

#[async_trait::async_trait]
impl TaskStore for LanceTaskStore {
    async fn create(&self, mut task: Task) -> Result<Task, String> {
        let now = chrono::Utc::now().to_rfc3339();
        if task.created_at.is_empty() {
            task.created_at = now.clone();
        }
        task.updated_at = now;

        let batch = task_to_batch(&task).map_err(|e| e.to_string())?;
        let table = self.open_table().await.map_err(|e| e.to_string())?;

        let schema = task_schema();
        let batches = RecordBatchIterator::new(vec![Ok(batch)], schema);
        table
            .add(Box::new(batches))
            .execute()
            .await
            .map_err(|e| e.to_string())?;

        Ok(task)
    }

    async fn get(&self, id: &str) -> Option<Task> {
        let tasks = self.query_all_tasks(Some(&format!("id = '{}'", id))).await;
        tasks.into_iter().next()
    }

    async fn list_pending(&self) -> Vec<Task> {
        let mut tasks = self.query_all_tasks(Some("status = 'Pending'")).await;
        tasks.sort_by(|a, b| {
            let prio = |p: &str| match p {
                "critical" => 0,
                "high" => 1,
                "medium" => 2,
                _ => 3,
            };
            prio(&a.priority).cmp(&prio(&b.priority))
        });
        tasks
    }

    async fn list_all(&self) -> Vec<Task> {
        // Сортировка убрана (BUG-6): list_tasks_api пересортирует по updated_at.
        // Лишний O(N log N) на 1881+ задачах = ~2ms wasted на каждый refresh.
        self.query_all_tasks(None).await
    }

    async fn update_status(&self, id: &str, status: TaskStatus) -> Result<(), String> {
        if let Some(mut task) = self.get(id).await {
            task.status = status;
            task.updated_at = chrono::Utc::now().to_rfc3339();
            self.update(task).await
        } else {
            Err(format!("Task {} not found", id))
        }
    }

    async fn update(&self, mut task: Task) -> Result<(), String> {
        task.updated_at = chrono::Utc::now().to_rfc3339();

        // merge_insert (upsert) по ключу id: один вызов вместо delete + create.
        // Под конкуренцией воркеров LanceDB может вернуть "Conflicting Transaction"
        // (оптимистичная блокировка коммита) — это транзиентно. Повторяем, сбрасывая
        // кэш table handle, чтобы переоткрыть таблицу на свежем манифесте и не
        // конфликтовать с тем же устаревшим снапшотом снова.
        const MAX_ATTEMPTS: u32 = 5;
        let mut last_err = String::new();
        for attempt in 0..MAX_ATTEMPTS {
            if attempt > 0 {
                // на повторе перечитываем последнюю закоммиченную версию таблицы
                self.invalidate_table_cache().await;
            }
            let table = self.open_table().await.map_err(|e| e.to_string())?;
            // batch + iterator потребляются execute() — строим заново на каждой попытке
            let batch = task_to_batch(&task).map_err(|e| e.to_string())?;
            let schema = task_schema();
            let batches = RecordBatchIterator::new(vec![Ok(batch)], schema);

            let mut builder = table.merge_insert(&["id"]);
            builder.when_matched_update_all(None);
            builder.when_not_matched_insert_all();

            match builder.execute(Box::new(batches)).await {
                Ok(_) => return Ok(()),
                Err(e) => {
                    last_err = e.to_string();
                    eprintln!(
                        "[LanceDB] merge_insert attempt {}/{} failed ({})",
                        attempt + 1,
                        MAX_ATTEMPTS,
                        last_err
                    );
                }
            }
        }

        // Fallback: delete+create. КРИТИЧНО не глотать ошибку delete — если строку
        // не удалось удалить, create() создал бы ДУБЛИКАТ (исторический корень
        // дублирования). Поэтому create только при успешном delete; иначе возвращаем
        // ошибку, и вызывающий повторит позже. delete по предикату id убирает и
        // возможные легаси-дубли, оставляя ровно одну строку.
        eprintln!(
            "[LanceDB] merge_insert exhausted {} attempts ({}), falling back to delete+create",
            MAX_ATTEMPTS, last_err
        );
        self.invalidate_table_cache().await;
        match self.delete(&task.id).await {
            Ok(_) => self.create(task).await.map(|_| ()),
            Err(del_err) => Err(format!(
                "update failed for {}: merge_insert={}; delete={}",
                task.id, last_err, del_err
            )),
        }
    }

    async fn delete(&self, id: &str) -> Result<(), String> {
        let table = self.open_table().await.map_err(|e| e.to_string())?;
        table
            .delete(&format!("id = '{}'", id))
            .await
            .map_err(|e| e.to_string())
    }

    async fn count(&self) -> usize {
        let table = match self.open_table().await {
            Ok(t) => t,
            Err(_) => return 0,
        };
        table.count_rows(None).await.unwrap_or(0) as usize
    }

    async fn claim(&self, id: &str, agent: &str) -> Result<Task, String> {
        if let Some(mut task) = self.get(id).await {
            if task.status != TaskStatus::Pending {
                return Err(format!("Task {} is not pending ({:?})", id, task.status));
            }
            if task.assigned_to.is_some() {
                return Err(format!(
                    "Task {} already assigned to {:?}",
                    id, task.assigned_to
                ));
            }

            task.assigned_to = Some(agent.to_string());
            task.status = TaskStatus::InProgress;
            task.started_at = Some(chrono::Utc::now().to_rfc3339());
            task.updated_at = chrono::Utc::now().to_rfc3339();

            self.update(task.clone()).await?;
            Ok(task)
        } else {
            Err(format!("Task {} not found", id))
        }
    }
}
