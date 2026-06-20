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
    hb_counters: HashMap<String, u32>,
}

impl LongTaskManager {
    pub fn new() -> Self {
        let home = std::env::var("HOME").unwrap_or_else(|_| ".".to_string());
        let pdir = PathBuf::from(home).join(".agentforge/long_horizon");
        let _ = std::fs::create_dir_all(&pdir);
        let mut mgr = Self {
            persistence_dir: pdir,
            tasks: HashMap::new(),
            hb_counters: HashMap::new(),
        };
        mgr.load_all();
        mgr
    }

    fn load_all(&mut self) {
        // Load persisted tasks on startup (mirrors Python _load_all for cross-restart resumability).
        // Silently skip corrupt files (don't crash manager).
        if let Ok(entries) = std::fs::read_dir(&self.persistence_dir) {
            for entry in entries.filter_map(|e| e.ok()) {
                let path = entry.path();
                if path.extension().and_then(|s| s.to_str()) == Some("json") {
                    if let Ok(data) = std::fs::read_to_string(&path) {
                        if let Ok(task) = serde_json::from_str::<LongTask>(&data) {
                            let id = task.id.clone();
                            self.tasks.insert(id.clone(), task);
                            self.hb_counters.insert(id, 0);
                        }
                    }
                }
            }
        }
    }

    pub fn start_long_task(&mut self, goal: &str, use_planning: bool) -> LongTask {
        // Safe slice (avoid potential panic on str byte index); 8 hex chars for id.
        let full = Uuid::new_v4().to_string();
        let id: String = full.chars().take(8).collect();
        let (plan, progress) = if use_planning {
            let planner = HierarchicalPlanner::new();
            let p = planner.decompose(goal);
            let pr = Progress {
                total_steps: p.subtasks.len() as u32,
                percent: 0.0,
                ..Default::default()
            };
            (Some(p), pr)
        } else {
            (None, Progress::default())
        };

        let task = LongTask {
            id: id.clone(),
            goal: goal.to_string(),
            plan,
            progress,
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
        self.hb_counters.insert(id.clone(), 0);
        let _ = self.save_checkpoint(&task);
        // Mirror Python: emit initial heartbeat (updates mem + may write; count will be 1 so writes).
        self.heartbeat(&id, "Task started", 0.0);
        task
    }

    pub fn heartbeat(&mut self, task_id: &str, message: &str, pct: f64) {
        // Only write every ~5 heartbeats (or first) to reduce I/O bottleneck on hot path for long tasks.
        // Sequential borrows: compute do_write in block so hb_counters borrow drops before tasks borrow.
        let do_write = if self.tasks.contains_key(task_id) {
            let count = self.hb_counters.entry(task_id.to_string()).or_insert(0);
            *count += 1;
            *count == 1 || (*count).is_multiple_of(5)
        } else {
            false
        };
        if let Some(t) = self.tasks.get_mut(task_id) {
            let pct = pct.clamp(0.0, 100.0);
            t.progress.percent = pct;
            t.progress.last_message = message.to_string();
            t.progress.updated_at = Utc::now().to_rfc3339();
            t.updated_at = t.progress.updated_at.clone();
            if do_write {
                if let Some(p) = t.checkpoint_path.clone() {
                    let _ = Self::write_checkpoint(&p, t);
                }
            }
        }
    }

    pub fn pause(&mut self, task_id: &str) {
        if let Some(t) = self.tasks.get_mut(task_id) {
            t.status = "paused".to_string();
            t.updated_at = Utc::now().to_rfc3339();
            // Reset hb counter on explicit state change; always persist pause (important transition).
            self.hb_counters.insert(task_id.to_string(), 0);
            if let Some(p) = t.checkpoint_path.clone() {
                let _ = Self::write_checkpoint(&p, t);
            }
        }
    }

    pub fn resume(&mut self, task_id: &str) -> Option<LongTask> {
        // Prefer in-memory (fast path). Only force running + persist if it was paused.
        if let Some(t) = self.tasks.get_mut(task_id) {
            if t.status == "paused" {
                t.status = "running".to_string();
                t.updated_at = Utc::now().to_rfc3339();
                self.hb_counters.insert(task_id.to_string(), 0);
                if let Some(p) = t.checkpoint_path.clone() {
                    let _ = Self::write_checkpoint(&p, t);
                }
            }
            return Some(t.clone());
        }
        // Cold load from disk (cross-process/reboot). Only flip paused -> running.
        let path = self.persistence_dir.join(format!("{}.json", task_id));
        if let Ok(data) = std::fs::read_to_string(&path) {
            if let Ok(mut task) = serde_json::from_str::<LongTask>(&data) {
                let was_paused = task.status == "paused";
                if was_paused {
                    task.status = "running".to_string();
                    task.updated_at = Utc::now().to_rfc3339();
                }
                let key = task_id.to_string();
                self.tasks.insert(key.clone(), task.clone());
                self.hb_counters.insert(key, 0);
                if was_paused {
                    // Persist the resume transition (original missed this -> status on disk stale).
                    let _ = Self::write_checkpoint(path.to_string_lossy().as_ref(), &task);
                }
                return Some(task);
            }
        }
        self.tasks.get(task_id).cloned()
    }

    fn write_checkpoint(path: &str, task: &LongTask) -> Result<(), String> {
        // Compact (not pretty) for lower CPU/IO in hot checkpoint path; atomic rename prevents
        // partial-write corruption races (reader sees old complete JSON or new complete, never torn).
        let json = serde_json::to_string(task).map_err(|e| e.to_string())?;
        let p = std::path::Path::new(path);
        let tmp = p.with_extension("json.tmp");
        std::fs::write(&tmp, json).map_err(|e| e.to_string())?;
        std::fs::rename(&tmp, p).map_err(|e| e.to_string())?;
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
                // Type must be explicit for HashMap (inference fails on bare let + later use in call).
                let ctx: HashMap<String, String> = HashMap::new();
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

    #[test]
    fn long_task_resume_from_disk_and_persist() {
        // Exercises load_all on new(), resume cold-path, and that resume persists "running" to disk.
        let mut mgr = LongTaskManager::new();
        let task = mgr.start_long_task("resume disk audit test", false);
        let tid = task.id.clone();
        mgr.pause(&tid);
        assert_eq!(mgr.tasks.get(&tid).unwrap().status, "paused");

        // "restart": fresh manager loads from disk via load_all
        let mut mgr2 = LongTaskManager::new();
        assert!(
            mgr2.tasks.contains_key(&tid),
            "load_all must populate from persisted json"
        );
        let resumed = mgr2.resume(&tid).expect("should resume");
        assert_eq!(resumed.status, "running");

        // Verify persisted: third manager sees the status=running from resume's write
        let mgr3 = LongTaskManager::new();
        let t3 = mgr3
            .tasks
            .get(&tid)
            .expect("task must still be loadable after resume");
        assert_eq!(
            t3.status, "running",
            "resume must have persisted status flip to disk"
        );
    }
}
