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
use arrow_array::{Array, ArrayRef, RecordBatch, RecordBatchIterator, StringArray};
use arrow_schema::{DataType, Field, Schema};
use lancedb::query::{ExecutableQuery, QueryBase};
use std::sync::Arc;

pub struct LanceTaskStore {
    db: lancedb::Connection,
    table_name: String,
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
    let result_json = task.result.as_ref().map(|r| r.to_string()).unwrap_or_default();
    let status_str = format!("{:?}", task.status);

    RecordBatch::try_from_iter(vec![
        ("id", Arc::new(StringArray::from(vec![task.id.as_str()])) as ArrayRef),
        ("title", Arc::new(StringArray::from(vec![task.title.as_str()])) as ArrayRef),
        ("description", Arc::new(StringArray::from(vec![task.description.as_str()])) as ArrayRef),
        ("priority", Arc::new(StringArray::from(vec![task.priority.as_str()])) as ArrayRef),
        ("complexity", Arc::new(StringArray::from(vec![task.complexity.as_str()])) as ArrayRef),
        ("preferred_agent", Arc::new(StringArray::from(vec![task.preferred_agent.as_deref().unwrap_or("")])) as ArrayRef),
        ("assigned_to", Arc::new(StringArray::from(vec![task.assigned_to.as_deref().unwrap_or("")])) as ArrayRef),
        ("status", Arc::new(StringArray::from(vec![status_str.as_str()])) as ArrayRef),
        ("tags_json", Arc::new(StringArray::from(vec![tags_json.as_str()])) as ArrayRef),
        ("created_at", Arc::new(StringArray::from(vec![task.created_at.as_str()])) as ArrayRef),
        ("updated_at", Arc::new(StringArray::from(vec![task.updated_at.as_str()])) as ArrayRef),
        ("started_at", Arc::new(StringArray::from(vec![task.started_at.as_deref().unwrap_or("")])) as ArrayRef),
        ("completed_at", Arc::new(StringArray::from(vec![task.completed_at.as_deref().unwrap_or("")])) as ArrayRef),
        ("metadata_json", Arc::new(StringArray::from(vec![metadata_json.as_str()])) as ArrayRef),
        ("result_json", Arc::new(StringArray::from(vec![result_json.as_str()])) as ArrayRef),
    ]).map_err(|e| anyhow::anyhow!(e))
}

fn batch_to_tasks(batch: &RecordBatch) -> Vec<Task> {
    let ids = batch.column_by_name("id").and_then(|c| c.as_any().downcast_ref::<StringArray>());
    let titles = batch.column_by_name("title").and_then(|c| c.as_any().downcast_ref::<StringArray>());
    let descs = batch.column_by_name("description").and_then(|c| c.as_any().downcast_ref::<StringArray>());
    let priorities = batch.column_by_name("priority").and_then(|c| c.as_any().downcast_ref::<StringArray>());
    let complexities = batch.column_by_name("complexity").and_then(|c| c.as_any().downcast_ref::<StringArray>());
    let pref_agents = batch.column_by_name("preferred_agent").and_then(|c| c.as_any().downcast_ref::<StringArray>());
    let assigned = batch.column_by_name("assigned_to").and_then(|c| c.as_any().downcast_ref::<StringArray>());
    let statuses = batch.column_by_name("status").and_then(|c| c.as_any().downcast_ref::<StringArray>());
    let tags = batch.column_by_name("tags_json").and_then(|c| c.as_any().downcast_ref::<StringArray>());
    let created = batch.column_by_name("created_at").and_then(|c| c.as_any().downcast_ref::<StringArray>());
    let updated = batch.column_by_name("updated_at").and_then(|c| c.as_any().downcast_ref::<StringArray>());
    let started = batch.column_by_name("started_at").and_then(|c| c.as_any().downcast_ref::<StringArray>());
    let completed = batch.column_by_name("completed_at").and_then(|c| c.as_any().downcast_ref::<StringArray>());
    let meta = batch.column_by_name("metadata_json").and_then(|c| c.as_any().downcast_ref::<StringArray>());
    let results = batch.column_by_name("result_json").and_then(|c| c.as_any().downcast_ref::<StringArray>());

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

        let db = lancedb::connect(path.to_str().unwrap())
            .execute()
            .await?;

        // Create table if not exists
        let table_name = "tasks".to_string();
        let table_names = db.table_names().execute().await?;
        if !table_names.contains(&table_name) {
            let schema = task_schema();
            let empty = RecordBatch::new_empty(schema.clone());
            let batches = RecordBatchIterator::new(
                vec![Ok(empty)],
                schema,
            );
            db.create_table(&table_name, Box::new(batches))
                .execute()
                .await?;
        }

        Ok(Self { db, table_name })
    }

    async fn open_table(&self) -> Result<lancedb::Table> {
        Ok(self.db.open_table(&self.table_name).execute().await?)
    }

    async fn query_all_tasks(&self, filter: Option<&str>) -> Vec<Task> {
        let table = match self.open_table().await {
            Ok(t) => t,
            Err(_) => return vec![],
        };

        let batches = if let Some(f) = filter {
            match table.query().only_if(f).execute().await {
                Ok(stream) => {
                    use futures::TryStreamExt;
                    stream.try_collect::<Vec<_>>().await.unwrap_or_default()
                }
                Err(_) => return vec![],
            }
        } else {
            match table.query().execute().await {
                Ok(stream) => {
                    use futures::TryStreamExt;
                    stream.try_collect::<Vec<_>>().await.unwrap_or_default()
                }
                Err(_) => return vec![],
            }
        };

        batches.iter().flat_map(|b| batch_to_tasks(b)).collect()
    }
}

#[async_trait::async_trait]
impl TaskStore for LanceTaskStore {
    async fn create(&mut self, mut task: Task) -> Result<Task, String> {
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
                "critical" => 0, "high" => 1, "medium" => 2, _ => 3,
            };
            prio(&a.priority).cmp(&prio(&b.priority))
        });
        tasks
    }

    async fn list_all(&self) -> Vec<Task> {
        let mut tasks = self.query_all_tasks(None).await;
        tasks.sort_by_key(|t| t.created_at.clone());
        tasks
    }

    async fn update_status(&mut self, id: &str, status: TaskStatus) -> Result<(), String> {
        if let Some(mut task) = self.get(id).await {
            task.status = status;
            task.updated_at = chrono::Utc::now().to_rfc3339();
            self.update(task).await
        } else {
            Err(format!("Task {} not found", id))
        }
    }

    async fn update(&mut self, mut task: Task) -> Result<(), String> {
        task.updated_at = chrono::Utc::now().to_rfc3339();
        let _ = self.delete(&task.id).await;
        self.create(task).await.map(|_| ())
    }

    async fn delete(&mut self, id: &str) -> Result<(), String> {
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

    async fn claim(&mut self, id: &str, agent: &str) -> Result<Task, String> {
        if let Some(mut task) = self.get(id).await {
            if task.status != TaskStatus::Pending {
                return Err(format!("Task {} is not pending ({:?})", id, task.status));
            }
            if task.assigned_to.is_some() {
                return Err(format!("Task {} already assigned to {:?}", id, task.assigned_to));
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
