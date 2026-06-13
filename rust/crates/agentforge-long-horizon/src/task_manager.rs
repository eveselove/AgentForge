//! LongTaskManager + checkpointing for Phase 3 long-horizon work.
//! Mirrors the Python reference in agentforge/long_horizon/task_manager.py

use agentforge_core::Outcome;
use agentforge_planning::{HierarchicalPlanner, Plan};
use agentforge_safety::PolicyEngine;
use chrono::Utc;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::PathBuf;
use uuid::Uuid;

#[allow(dead_code)]
const PERSISTENCE_DIR: &str = "~/.agentforge/long_horizon";

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Progress {
    pub percent: f64,
    pub completed_steps: u32,
    pub total_steps: u32,
    pub eta_seconds: Option<i64>,
    pub last_message: String,
    pub updated_at: String,
}

impl Default for Progress {
    fn default() -> Self {
        Self {
            percent: 0.0,
            completed_steps: 0,
            total_steps: 1,
            eta_seconds: None,
            last_message: String::new(),
            updated_at: Utc::now().to_rfc3339(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LongTask {
    pub id: String,
    pub goal: String,
    pub plan: Option<Plan>,
    pub progress: Progress,
    pub status: String, // running, paused, completed, failed
    /// Final execution outcome (canonical from core, for Phase 3 learning integration).
    #[serde(default)]
    pub final_outcome: Option<Outcome>,
    pub created_at: String,
    pub updated_at: String,
    pub checkpoint_path: Option<String>,
    pub metadata: HashMap<String, serde_json::Value>,
}

#[derive(Debug)]
pub struct LongTaskManager {
    persistence_dir: PathBuf,
    tasks: HashMap<String, LongTask>,
}

impl LongTaskManager {
    pub fn new() -> Self {
        let home = std::env::var("HOME").unwrap_or_else(|_| ".".to_string());
        let pdir = PathBuf::from(home).join(".agentforge/long_horizon");
        let _ = std::fs::create_dir_all(&pdir);
        Self {
            persistence_dir: pdir,
            tasks: HashMap::new(),
        }
    }

    pub fn start_long_task(&mut self, goal: &str, use_planning: bool) -> LongTask {
        let id = Uuid::new_v4().to_string()[..8].to_string();
        let plan = if use_planning {
            let planner = HierarchicalPlanner::new();
            Some(planner.decompose(goal))
        } else {
            None
        };

        let task = LongTask {
            id: id.clone(),
            goal: goal.to_string(),
            plan,
            progress: Progress::default(),
            status: "running".to_string(),
            final_outcome: None,
            created_at: Utc::now().to_rfc3339(),
            updated_at: Utc::now().to_rfc3339(),
            checkpoint_path: Some(
                self.persistence_dir
                    .join(format!("{}.json", id))
                    .to_string_lossy()
                    .to_string(),
            ),
            metadata: HashMap::new(),
        };

        self.tasks.insert(id.clone(), task.clone());
        let _ = self.save_checkpoint(&task);
        task
    }

    pub fn heartbeat(&mut self, task_id: &str, message: &str, pct: f64) {
        if let Some(t) = self.tasks.get_mut(task_id) {
            t.progress.percent = pct;
            t.progress.last_message = message.to_string();
            t.progress.updated_at = Utc::now().to_rfc3339();
            t.updated_at = t.progress.updated_at.clone();
            let path = t.checkpoint_path.clone();
            if let Some(p) = path {
                let _ = Self::write_checkpoint(&p, t);
            }
        }
    }

    pub fn pause(&mut self, task_id: &str) {
        if let Some(t) = self.tasks.get_mut(task_id) {
            t.status = "paused".to_string();
            let path = t.checkpoint_path.clone();
            if let Some(p) = path {
                let _ = Self::write_checkpoint(&p, t);
            }
        }
    }

    pub fn resume(&mut self, task_id: &str) -> Option<LongTask> {
        // Load from disk if not in memory
        let path = self.persistence_dir.join(format!("{}.json", task_id));
        if let Ok(data) = std::fs::read_to_string(&path) {
            if let Ok(mut task) = serde_json::from_str::<LongTask>(&data) {
                task.status = "running".to_string();
                self.tasks.insert(task_id.to_string(), task.clone());
                return Some(task);
            }
        }
        self.tasks.get(task_id).cloned()
    }

    fn write_checkpoint(path: &str, task: &LongTask) -> Result<(), String> {
        let json = serde_json::to_string_pretty(task).map_err(|e| e.to_string())?;
        std::fs::write(path, json).map_err(|e| e.to_string())?;
        Ok(())
    }

    fn save_checkpoint(&self, task: &LongTask) -> Result<(), String> {
        if let Some(p) = &task.checkpoint_path {
            Self::write_checkpoint(p, task)
        } else {
            Ok(())
        }
    }

    /// Example integration point: run one subtask safely using planning + safety.
    pub fn execute_subtask_safely(
        &self,
        task: &mut LongTask,
        subtask_id: &str,
        policy: &PolicyEngine,
    ) -> Result<String, String> {
        if let Some(plan) = &mut task.plan {
            if let Some(st) = plan.subtasks.iter_mut().find(|s| s.id == subtask_id) {
                let ctx = std::collections::HashMap::new();
                let decision = policy.evaluate("subtask_execution", &ctx);
                match decision.decision {
                    agentforge_safety::Decision::Block => {
                        return Err(format!("Blocked by policy: {}", decision.reason));
                    }
                    agentforge_safety::Decision::RequireApproval => {
                        return Err("Requires human approval".into());
                    }
                    _ => {}
                }
                st.status = agentforge_planning::SubtaskStatus::Running;
                // Real work would happen here via executor callback
                st.status = agentforge_planning::SubtaskStatus::Done;
                st.result = Some("completed under safety+checkpoint".into());
                return Ok(st.result.clone().unwrap());
            }
        }
        Err("subtask not found".into())
    }
}

impl Default for LongTaskManager {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn long_task_manager_start_and_heartbeat() {
        let mut mgr = LongTaskManager::new();
        let task = mgr.start_long_task("Test long goal for rust port", true);
        assert!(!task.id.is_empty());
        assert_eq!(task.status, "running");
        assert!(task.plan.is_some());

        mgr.heartbeat(&task.id, "halfway", 0.5);
        // since in-mem updated
        if let Some(t) = mgr.tasks.get(&task.id) {
            assert_eq!(t.progress.percent, 0.5);
        }
    }

    #[test]
    fn long_task_pause_resume_stub() {
        let mut mgr = LongTaskManager::new();
        let task = mgr.start_long_task("pause test", false);
        mgr.pause(&task.id);
        // note: in mem status changed
        assert_eq!(mgr.tasks.get(&task.id).unwrap().status, "paused");
    }
}
