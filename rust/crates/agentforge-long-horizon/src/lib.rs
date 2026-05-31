//! AgentForge Long Horizon (Phase 3).
//!
//! Long-running task orchestration with checkpoints, heartbeats, pause/resume.
//! Integrates tightly with planning + safety + observability.

pub mod task_manager;

pub use task_manager::{LongTask, LongTaskManager, Progress};
