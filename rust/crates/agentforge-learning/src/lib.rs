//! AgentForge Learning Flywheel (Phase 2) - Rust implementation.
//!
//! This is the Rust-native core for turning high-quality execution data
//! (trajectories + PRM scores + outcomes) into automatic improvement of agents and skills.
//!
//! It mirrors the excellent Python reference implementation in `agentforge/learning/`
//! but provides type safety, performance, and easier integration into a Rust-first future.
//!
//! Key: clean SPLIT basic LLM critique path (via try_llm_critique_stub + AGENTFORGE_LLM_CMD)
//! for maximum flywheel-step emission quality (richer proposals + candidate_skill.yaml).

pub mod dataset;
pub mod trainer;
pub mod types;
pub mod improver;

pub use dataset::TrajectoryDataset;
pub use trainer::{BaseTrainer, DPOTrainer, KTOTrainer, SFTTrainer, TrainingConfig, TrainingRun};
pub use types::{TrajectoryRecord, Outcome, PRMStepLabel, CoreOutcome};
pub use agentforge_core::ParseOutcomeError;
// Re-export the clean SPLIT basic LLM critique path (AGENTFORGE_LLM_CMD integration) + SkillImprover for flywheel emission quality.
pub use improver::{SkillImprover, ProposedSkill, try_llm_critique_stub};
