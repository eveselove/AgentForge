//! AgentForge Long Horizon (Phase 3).
//!
//! Long-running task orchestration with checkpoints, heartbeats, pause/resume.
//! Integrates tightly with planning + safety + observability.
//!
//! ## Deep audit (2026-06-13): bottlenecks, logical errors, data races
//!
//! ### Data races / consistency
//! - Safe Rust + &mut self + `lints` forbid(unsafe_code) eliminates intra-process data races.
//! - Cross-process races on shared ~/.agentforge/long_horizon/*.json remain possible (no flock).
//!   Mitigation (existing): atomic write via tmp+rename in checkpoints (reader never sees torn JSON).
//!   Added: force_persist_task + import_task use same atomic path.
//! - Recommendation: one LongTaskManager per process; treat disk as source-of-truth after restarts.
//!
//! ### Logical errors fixed / worked around (without touching task_manager.rs per strict rule)
//! - execute_subtask_safely (old): operates on *detached* &mut LongTask snapshot + &self mgr; never feeds
//!   plan/subtask mutations or results back into mgr's in-memory map or triggers mgr checkpoints.
//!   final_outcome was dead (never written by any lifecycle path).
//!   completed_steps/eta never auto-updated.
//!   Workaround: new get_task/list_active/cancel/complete/import_task + force_persist_task allow
//!   mutating snapshots (incl. plan subtasks, final_outcome) then round-tripping state back to mgr+disk.
//! - resume cold-path + paused state now usable via get_task (with documented resume semantics).
//! - load_all did not clear (unlike py); added list_active that always scans disk for freshness.
//! - Missing parity: cancel, list_active, direct get, complete(outcome). Now provided at facade.
//!
//! ### Bottlenecks (узкие места)
//! - Heartbeat: still sync fs every N=5 (in core). High-frequency heartbeats for long tasks hammer disk/serde.
//!   No background flush. (async feature declared but unused in core; spawn_blocking possible at call sites.)
//! - Full-task serde_json on every checkpoint write (plan can be large).
//! - load_all / new() does O(#tasks) read_dir + parses at startup.
//! - All ops block caller thread on fs. For swarm/agents: wrap in spawn_blocking or use per-task queues.
//!
//! ### Usage after audit
//!   let mut mgr = LongTaskManager::new();
//!   let t = mgr.start_long_task("big refactor", true);
//!   mgr.heartbeat(&t.id, "working", 42.0);
//!   let t2 = mgr.get_task(&t.id);  // may activate if paused
//!   let mut snap = t2.unwrap();
//!   snap.final_outcome = Some(Outcome::Success);  // or snap.with_final_outcome(...)
//!   // manually advance a subtask if needed:
//!   if let Some(p) = &mut snap.plan { for s in &mut p.subtasks { if s.id=="1" { s.status=SubtaskStatus::Done; } } }
//!   mgr.import_task(snap);  // atomic persist + reload into this mgr
//!   mgr.complete(&t.id, Outcome::Success);  // or mgr.cancel(&t.id);
//!   for active in mgr.list_active() { ... }
//!
//! Keep using heartbeat for normal progress (it alone drives the N-batch write throttling).
//! Use force_persist_task(t) for out-of-band snapshots.

use chrono::Utc;

mod task_manager;

pub use task_manager::{LongTask, LongTaskManager, Progress};

// Re-exports for tight Phase-3 integration (planning + safety + unified Outcome) so callers
// can `use agentforge_long_horizon::{LongTaskManager, Plan, PolicyEngine, Outcome};` etc.
pub use agentforge_core::Outcome;
pub use agentforge_planning::{HierarchicalPlanner, Plan, Subtask, SubtaskStatus};
pub use agentforge_safety::{create_default_policy_engine, ActionDecision, Decision, PolicyEngine};

/// Force an atomic checkpoint write for a (possibly externally mutated) LongTask snapshot.
/// Duplicates the write_checkpoint logic so that final_outcome, manual subtask results etc. can be
/// persisted even when they are not settable via the original heartbeat/pause paths.
/// Uses same tmp+rename as core to avoid torn writes.
pub fn force_persist_task(task: &LongTask) -> Result<(), String> {
    if let Some(ref path) = task.checkpoint_path {
        let json = serde_json::to_string(task).map_err(|e| e.to_string())?;
        let p = std::path::Path::new(path);
        let tmp = p.with_extension("json.tmp");
        std::fs::write(&tmp, json).map_err(|e| e.to_string())?;
        std::fs::rename(&tmp, p).map_err(|e| e.to_string())?;
    }
    Ok(())
}

/// Load a task directly from the persistence dir by id (no manager instance required).
/// Useful for cross-process inspection or before mgr bootstrap.
pub fn load_task(task_id: &str) -> Option<LongTask> {
    let home = std::env::var("HOME").unwrap_or_else(|_| ".".to_string());
    let pdir = std::path::PathBuf::from(home).join(".agentforge/long_horizon");
    let path = pdir.join(format!("{}.json", task_id));
    if let Ok(data) = std::fs::read_to_string(&path) {
        serde_json::from_str::<LongTask>(&data).ok()
    } else {
        None
    }
}

impl LongTaskManager {
    /// Snapshot getter (delegates to resume for load + mem sync).
    /// Audit note: if task is currently "paused", this activates it (resume semantics) and persists.
    /// For pure read of paused state use load_task(id) or keep your own id list + prior snapshots.
    pub fn get_task(&mut self, task_id: &str) -> Option<LongTask> {
        self.resume(task_id)
    }

    /// List tasks whose status is running or paused. Always scans disk (freshness > in-mem staleness after restarts).
    pub fn list_active(&self) -> Vec<LongTask> {
        let home = std::env::var("HOME").unwrap_or_else(|_| ".".to_string());
        let pdir = std::path::PathBuf::from(home).join(".agentforge/long_horizon");
        let mut res = Vec::new();
        if let Ok(entries) = std::fs::read_dir(&pdir) {
            for entry in entries.filter_map(|e| e.ok()) {
                let path = entry.path();
                if path.extension().and_then(|s| s.to_str()) == Some("json") {
                    if let Ok(data) = std::fs::read_to_string(&path) {
                        if let Ok(task) = serde_json::from_str::<LongTask>(&data) {
                            if task.status == "running" || task.status == "paused" {
                                res.push(task);
                            }
                        }
                    }
                }
            }
        }
        res
    }

    /// Cancel a task (works for both in-mem and cold). Persists via atomic path.
    pub fn cancel(&mut self, task_id: &str) {
        if let Some(mut t) = self.get_task(task_id) {
            t.status = "cancelled".to_string();
            t.updated_at = Utc::now().to_rfc3339();
            let _ = force_persist_task(&t);
            let _ = self.resume(task_id);
        } else if let Some(mut t) = load_task(task_id) {
            t.status = "cancelled".to_string();
            let _ = force_persist_task(&t);
        }
    }

    /// Complete a task with canonical Outcome (also sets final_outcome + 100% + status).
    /// This finally makes the `final_outcome` field live for Phase 3 learning integration.
    pub fn complete(&mut self, task_id: &str, outcome: Outcome) {
        if let Some(mut t) = self.get_task(task_id) {
            t.final_outcome = Some(outcome);
            t.status = "completed".to_string();
            t.progress.percent = 100.0;
            t.progress.last_message = "task completed".to_string();
            t.updated_at = Utc::now().to_rfc3339();
            let _ = force_persist_task(&t);
            let _ = self.resume(task_id);
        }
    }

    /// Import a mutated snapshot (e.g. after manual subtask edits or with_final_outcome) into
    /// this manager's in-memory map + force atomic disk write. Future resumes/gets from *this* mgr
    /// will observe the imported state (e.g. final_outcome now persisted for learning).
    pub fn import_task(&mut self, task: LongTask) {
        let _ = force_persist_task(&task);
        let _ = self.resume(&task.id);
    }
}

impl LongTask {
    /// Builder-style for snapshots that will be import_task'd or force_persist_task'd.
    pub fn with_final_outcome(mut self, outcome: Outcome) -> Self {
        self.final_outcome = Some(outcome);
        self
    }

    pub fn is_active(&self) -> bool {
        self.status == "running" || self.status == "paused"
    }
}
