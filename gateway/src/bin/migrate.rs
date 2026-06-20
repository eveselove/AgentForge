use rusqlite::Connection;
use agentforge_core::{LanceTaskStore, Task, TaskStatus, TaskStore};
use std::collections::HashMap;

#[tokio::main]
async fn main() {
    let home = std::env::var("HOME").unwrap_or_else(|_| "/home/eveselove".into());
    let sqlite_path = format!("{}/agentforge/tasks.db", home);
    let data_dir = format!("{}/agentforge/data", home);
    let lance_path = format!("{}/lance_tasks", data_dir);

    println!("Reading tasks from SQLite: {}...", sqlite_path);
    let conn = Connection::open(&sqlite_path).expect("Failed to open SQLite database");

    // Backup existing LanceDB directory
    let lance_dir = std::path::Path::new(&lance_path);
    if lance_dir.exists() {
        let bak_path = format!("{}.bak", lance_path);
        println!("Backing up existing LanceDB dir to {}...", bak_path);
        let _ = std::fs::remove_dir_all(&bak_path);
        std::fs::rename(lance_dir, &bak_path).expect("Failed to backup LanceDB");
    }

    println!("Initializing LanceDB at {}...", lance_path);
    let mut store = LanceTaskStore::new_local(Some(&lance_path))
        .await
        .expect("Failed to initialize LanceDB store");

    let mut stmt = conn
        .prepare("SELECT id, title, description, priority, complexity, preferred_agent, status, assigned_agent, result, git_branch, created_at, updated_at, tags, duration_seconds, started_at, completed_at, retry_count FROM tasks")
        .expect("Failed to prepare statement");

    let rows = stmt
        .query_map([], |row| {
            let tags_raw: String = row.get(12).unwrap_or_else(|_| "[]".to_string());
            let tags: Vec<String> = serde_json::from_str(&tags_raw).unwrap_or_default();

            let mut metadata = HashMap::new();
            if let Ok(branch) = row.get::<_, String>(9) {
                metadata.insert("git_branch".to_string(), serde_json::json!(branch));
            }
            if let Ok(dur) = row.get::<_, f64>(13) {
                metadata.insert("duration_seconds".to_string(), serde_json::json!(dur));
            }
            if let Ok(rc) = row.get::<_, i64>(16) {
                metadata.insert("retry_count".to_string(), serde_json::json!(rc));
            }

            let result_raw: Option<String> = row.get(8).ok();
            let result = result_raw.and_then(|r| serde_json::from_str::<serde_json::Value>(&r).ok().or_else(|| Some(serde_json::json!(r))));

            let status_str: String = row.get(6).unwrap_or_else(|_| "pending".to_string());
            let status = match status_str.to_lowercase().as_str() {
                "pending" | "dispatch" => TaskStatus::Pending,
                "dispatched" => TaskStatus::Dispatched,
                "in_progress" | "grok_start" | "grok_done" | "ci_start" | "ci_done" | "ci_failed" | "rollback" => TaskStatus::InProgress,
                "review" => TaskStatus::Review,
                "done" => TaskStatus::Done,
                "failed" => TaskStatus::Failed,
                "cancelled" => TaskStatus::Cancelled,
                _ => TaskStatus::Pending,
            };

            Ok(Task {
                id: row.get(0)?,
                title: row.get(1)?,
                description: row.get(2).unwrap_or_default(),
                priority: row.get(3).unwrap_or_else(|_| "medium".to_string()),
                complexity: row.get(4).unwrap_or_else(|_| "medium".to_string()),
                preferred_agent: row.get(5).ok(),
                assigned_to: row.get(7).ok(),
                status,
                tags,
                created_at: row.get(10)?,
                updated_at: row.get(11)?,
                started_at: row.get(14).ok(),
                completed_at: row.get(15).ok(),
                metadata,
                result,
                requires_agent_review: false,
            })
        })
        .expect("Failed to query tasks");

    let mut count = 0;
    for task in rows {
        if let Ok(t) = task {
            store.create(t).await.expect("Failed to insert task to LanceDB");
            count += 1;
        }
    }

    println!("Successfully migrated {} tasks to LanceDB!", count);
}
