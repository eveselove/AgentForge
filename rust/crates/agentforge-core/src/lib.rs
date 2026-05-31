//! AgentForge Core
//!
//! Fundamental types and abstractions used across the entire system.

pub mod agent;
pub mod config;
pub mod outcome;
pub mod task;

pub use agent::{Agent, AgentId};
pub use config::AgentForgeConfig;
pub use outcome::{Outcome, ParseOutcomeError};
pub use task::{InMemoryTaskStore, JsonFileTaskStore, Task, TaskStatus, TaskStore};
