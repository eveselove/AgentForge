//! AgentForge Core
//!
//! Fundamental types and abstractions used across the entire system.

pub mod agent;
pub mod config;
pub mod outcome;
pub mod task;

#[cfg(feature = "lancedb")]
pub mod lance_task_store;

#[cfg(feature = "lancedb")]
pub use lance_task_store::LanceTaskStore;

pub use agent::{Agent, AgentId};
pub use config::AgentForgeConfig;
pub use outcome::{Outcome, ParseOutcomeError};
pub use task::{InMemoryTaskStore, JsonFileTaskStore, Task, TaskStatus, TaskStore};
