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

mod dataset;
mod improver;
mod trainer;
mod types;

pub use agentforge_core::ParseOutcomeError;
pub use dataset::{DatasetVersion, TrajectoryDataset};
pub use trainer::{BaseTrainer, DPOTrainer, KTOTrainer, SFTTrainer, TrainingConfig, TrainingRun};
pub use types::{CoreOutcome, Outcome, PRMStepLabel, TrajectoryRecord};
// Re-export the clean SPLIT basic LLM critique path (AGENTFORGE_LLM_CMD integration) + SkillImprover for flywheel emission quality.
pub use improver::{try_llm_critique_stub, ProposedSkill, SkillImprover};

// Thread-safety audit (addresses data race prevention).
// Every public type re-exported by this crate is asserted Send + Sync.
// This catches introduction of !Sync fields (Rc, RefCell, etc) in Trajectory* etc.
// (The crate intentionally uses only &mut self for mutation and has no shared mutable state / locks.)
#[cfg(test)]
mod send_sync_audit {
    use super::*;
    fn _assert_send_sync<T: Send + Sync>() {}
    #[test]
    fn all_public_types_are_send_sync() {
        _assert_send_sync::<ParseOutcomeError>();
        _assert_send_sync::<Outcome>();
        _assert_send_sync::<CoreOutcome>();
        _assert_send_sync::<PRMStepLabel>();
        _assert_send_sync::<TrajectoryRecord>();
        _assert_send_sync::<TrajectoryDataset>();
        _assert_send_sync::<DatasetVersion>();
        _assert_send_sync::<TrainingConfig>();
        _assert_send_sync::<TrainingRun>();
        _assert_send_sync::<ProposedSkill>();
        _assert_send_sync::<SkillImprover>();
        _assert_send_sync::<DPOTrainer>();
        _assert_send_sync::<KTOTrainer>();
        _assert_send_sync::<SFTTrainer>();
    }
}
