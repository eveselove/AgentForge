//! Task model and basic operations for the Rust-native task system.
//!
//! This is the foundation for replacing the Python task_queue + mcp_server.
//! Goal: Allow creating, queuing, and dispatching tasks without Python.

use serde::{Deserialize, Serialize};
use std::collections::HashMap;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub enum TaskStatus {
    Pending,
    Dispatched,
    InProgress,
    Review,
    Done,
    Failed,
    Cancelled,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Task {
    pub id: String,
    pub title: String,
    pub description: String,
    pub priority: String,           // "low" | "medium" | "high" | "critical"
    pub complexity: String,         // "trivial" | "simple" | "medium" | "complex"
    pub preferred_agent: Option<String>, // "grok" | "antigravity" | "auto"
    pub assigned_to: Option<String>,     // кто реально взял задачу в работу
    pub status: TaskStatus,
    pub tags: Vec<String>,
    pub created_at: String,
    pub updated_at: String,
    pub started_at: Option<String>,
    pub completed_at: Option<String>,

    // Extension points for future
    pub metadata: HashMap<String, serde_json::Value>,
    pub result: Option<serde_json::Value>,
}

impl Task {
    pub fn new(id: impl Into<String>, title: impl Into<String>, description: impl Into<String>) -> Self {
        let now = chrono::Utc::now().to_rfc3339();
        Self {
            id: id.into(),
            title: title.into(),
            description: description.into(),
            priority: "medium".to_string(),
            complexity: "medium".to_string(),
            preferred_agent: None,
            assigned_to: None,
            status: TaskStatus::Pending,
            tags: vec![],
            created_at: now.clone(),
            updated_at: now,
            started_at: None,
            completed_at: None,
            metadata: HashMap::new(),
            result: None,
        }
    }

    pub fn with_priority(mut self, priority: impl Into<String>) -> Self {
        self.priority = priority.into();
        self
    }

    pub fn with_preferred_agent(mut self, agent: impl Into<String>) -> Self {
        self.preferred_agent = Some(agent.into());
        self
    }

    pub fn with_tags(mut self, tags: Vec<String>) -> Self {
        self.tags = tags;
        self
    }
}

// Core Task storage API.
// This is the "normal" interface we will build the full Rust task system on top of.
pub trait TaskStore {
    fn create(&mut self, task: Task) -> Result<Task, String>;
    fn get(&self, id: &str) -> Option<Task>;
    fn list_pending(&self) -> Vec<Task>;
    fn list_all(&self) -> Vec<Task>;
    fn update_status(&mut self, id: &str, status: TaskStatus) -> Result<(), String>;
    fn update(&mut self, task: Task) -> Result<(), String>;
    fn delete(&mut self, id: &str) -> Result<(), String>;
    fn count(&self) -> usize;

    /// Пометить задачу как взятую в работу данным агентом.
    /// Возвращает ошибку, если задача уже взята или не в Pending.
    fn claim(&mut self, id: &str, agent: &str) -> Result<Task, String>;
}

/// Simple in-memory implementation of TaskStore.
/// This is the first concrete step toward a Rust-native task system.
#[derive(Default, Debug)]
pub struct InMemoryTaskStore {
    tasks: std::collections::HashMap<String, Task>,
}

impl InMemoryTaskStore {
    pub fn new() -> Self {
        Self {
            tasks: std::collections::HashMap::new(),
        }
    }
}

impl TaskStore for InMemoryTaskStore {
    fn create(&mut self, mut task: Task) -> Result<Task, String> {
        if self.tasks.contains_key(&task.id) {
            return Err(format!("Task with id {} already exists", task.id));
        }

        // Ensure timestamps are set
        if task.created_at.is_empty() {
            task.created_at = chrono::Utc::now().to_rfc3339();
        }
        task.updated_at = chrono::Utc::now().to_rfc3339();

        if task.status == TaskStatus::Pending && task.created_at.is_empty() {
            // already handled above
        }

        let id = task.id.clone();
        self.tasks.insert(id, task.clone());
        Ok(task)
    }

    fn get(&self, id: &str) -> Option<Task> {
        self.tasks.get(id).cloned()
    }

    fn list_pending(&self) -> Vec<Task> {
        let mut pending: Vec<Task> = self
            .tasks
            .values()
            .filter(|t| t.status == TaskStatus::Pending)
            .cloned()
            .collect();

        // Sort by priority (very rough for now)
        pending.sort_by(|a, b| {
            let prio_order = |p: &str| match p {
                "critical" => 0,
                "high" => 1,
                "medium" => 2,
                _ => 3,
            };
            prio_order(&a.priority).cmp(&prio_order(&b.priority))
        });

        pending
    }

    fn update_status(&mut self, id: &str, status: TaskStatus) -> Result<(), String> {
        if let Some(task) = self.tasks.get_mut(id) {
            task.status = status;
            task.updated_at = chrono::Utc::now().to_rfc3339();
            Ok(())
        } else {
            Err(format!("Task {} not found", id))
        }
    }

    fn list_all(&self) -> Vec<Task> {
        let mut all: Vec<Task> = self.tasks.values().cloned().collect();
        all.sort_by_key(|t| t.created_at.clone());
        all
    }

    fn update(&mut self, mut task: Task) -> Result<(), String> {
        if !self.tasks.contains_key(&task.id) {
            return Err(format!("Task {} not found", task.id));
        }
        task.updated_at = chrono::Utc::now().to_rfc3339();
        self.tasks.insert(task.id.clone(), task);
        Ok(())
    }

    fn delete(&mut self, id: &str) -> Result<(), String> {
        if self.tasks.remove(id).is_some() {
            Ok(())
        } else {
            Err(format!("Task {} not found", id))
        }
    }

    fn count(&self) -> usize {
        self.tasks.len()
    }

    fn claim(&mut self, id: &str, agent: &str) -> Result<Task, String> {
        match self.tasks.get_mut(id) {
            Some(task) => {
                if task.status != TaskStatus::Pending {
                    return Err(format!("Task {} is not pending (current status: {:?})", id, task.status));
                }
                if task.assigned_to.is_some() {
                    return Err(format!("Task {} is already assigned to {:?}", id, task.assigned_to));
                }

                task.assigned_to = Some(agent.to_string());
                task.status = TaskStatus::InProgress;
                task.started_at = Some(chrono::Utc::now().to_rfc3339());
                task.updated_at = chrono::Utc::now().to_rfc3339();

                // Note: InMemoryTaskStore does not persist (unlike JsonFileTaskStore)
                Ok(task.clone())
            }
            None => Err(format!("Task {} not found", id)),
        }
    }
}

/// A more serious, persistent implementation of TaskStore.
/// Stores tasks in a JSON file with atomic writes.
/// This is the main storage we will use during the migration to Rust-only.
///
/// NOTE: We are actively migrating away from both JSON and SQLite toward
/// LanceDB (see docs/LANCE_TASK_STORE_MIGRATION_PLAN.md).
/// New persistent storage work should target `LanceTaskStore`.
#[derive(Debug)]
pub struct JsonFileTaskStore {
    path: std::path::PathBuf,
    tasks: std::collections::HashMap<String, Task>,
}

impl JsonFileTaskStore {
    /// Creates a store. Default path: `data/tasks.json` relative to project root.
    pub fn new(path: Option<impl Into<std::path::PathBuf>>) -> Self {
        let path = path
            .map(|p| p.into())
            .unwrap_or_else(|| std::path::PathBuf::from("data/tasks.json"));

        let tasks = if path.exists() {
            std::fs::read_to_string(&path)
                .ok()
                .and_then(|content| serde_json::from_str::<Vec<Task>>(&content).ok())
                .map(|vec| vec.into_iter().map(|t| (t.id.clone(), t)).collect())
                .unwrap_or_default()
        } else {
            std::collections::HashMap::new()
        };

        Self { path, tasks }
    }

    fn persist(&self) {
        if let Some(parent) = self.path.parent() {
            let _ = std::fs::create_dir_all(parent);
        }

        let tasks_vec: Vec<&Task> = self.tasks.values().collect();

        // Atomic write (write to .tmp then rename)
        let tmp_path = self.path.with_extension("json.tmp");
        if let Ok(json) = serde_json::to_string_pretty(&tasks_vec) {
            if std::fs::write(&tmp_path, json).is_ok() {
                let _ = std::fs::rename(&tmp_path, &self.path);
            }
        }
    }

    pub fn path(&self) -> &std::path::Path {
        &self.path
    }
}

impl TaskStore for JsonFileTaskStore {
    fn create(&mut self, mut task: Task) -> Result<Task, String> {
        if self.tasks.contains_key(&task.id) {
            return Err(format!("Task with id {} already exists", task.id));
        }

        if task.created_at.is_empty() {
            task.created_at = chrono::Utc::now().to_rfc3339();
        }
        task.updated_at = chrono::Utc::now().to_rfc3339();

        let id = task.id.clone();
        self.tasks.insert(id, task.clone());
        self.persist();
        Ok(task)
    }

    fn get(&self, id: &str) -> Option<Task> {
        self.tasks.get(id).cloned()
    }

    fn list_pending(&self) -> Vec<Task> {
        let mut pending: Vec<Task> = self
            .tasks
            .values()
            .filter(|t| t.status == TaskStatus::Pending)
            .cloned()
            .collect();

        pending.sort_by(|a, b| {
            let prio_order = |p: &str| match p {
                "critical" => 0,
                "high" => 1,
                "medium" => 2,
                _ => 3,
            };
            prio_order(&a.priority).cmp(&prio_order(&b.priority))
        });

        pending
    }

    fn list_all(&self) -> Vec<Task> {
        let mut all: Vec<Task> = self.tasks.values().cloned().collect();
        all.sort_by_key(|t| t.created_at.clone());
        all
    }

    fn update_status(&mut self, id: &str, status: TaskStatus) -> Result<(), String> {
        if let Some(task) = self.tasks.get_mut(id) {
            task.status = status;
            task.updated_at = chrono::Utc::now().to_rfc3339();
            self.persist();
            Ok(())
        } else {
            Err(format!("Task {} not found", id))
        }
    }

    fn update(&mut self, mut task: Task) -> Result<(), String> {
        if !self.tasks.contains_key(&task.id) {
            return Err(format!("Task {} not found", task.id));
        }
        task.updated_at = chrono::Utc::now().to_rfc3339();
        self.tasks.insert(task.id.clone(), task);
        self.persist();
        Ok(())
    }

    fn delete(&mut self, id: &str) -> Result<(), String> {
        if self.tasks.remove(id).is_some() {
            self.persist();
            Ok(())
        } else {
            Err(format!("Task {} not found", id))
        }
    }

    fn count(&self) -> usize {
        self.tasks.len()
    }

    fn claim(&mut self, id: &str, agent: &str) -> Result<Task, String> {
        match self.tasks.get_mut(id) {
            Some(task) => {
                if task.status != TaskStatus::Pending {
                    return Err(format!("Task {} is not pending (current status: {:?})", id, task.status));
                }
                if task.assigned_to.is_some() {
                    return Err(format!("Task {} is already assigned to {:?}", id, task.assigned_to));
                }

                task.assigned_to = Some(agent.to_string());
                task.status = TaskStatus::InProgress;
                task.started_at = Some(chrono::Utc::now().to_rfc3339());
                task.updated_at = chrono::Utc::now().to_rfc3339();

                Ok(task.clone())
            }
            None => Err(format!("Task {} not found", id)),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_task_creation() {
        let task = Task::new("test-1", "Do something", "Detailed description")
            .with_priority("high")
            .with_preferred_agent("grok");

        assert_eq!(task.id, "test-1");
        assert_eq!(task.priority, "high");
        assert_eq!(task.preferred_agent, Some("grok".to_string()));
        assert_eq!(task.status, TaskStatus::Pending);
    }
}
