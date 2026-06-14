//! FlywheelStep orchestrator implementation.
//!
//! Thin owning wrapper over the real Phase-1 engine (in lib.rs) for clean separation
//! as ports/hooks grow (post_process, workers, continuous, after_task, shadow).
//! Owns the inner to avoid repeated construction (future caches/state in improver)
//! and to make reuse semantics explicit.

use crate::types::{FlywheelConfig, FlywheelManifest};
use anyhow::Result;

/// Owns FlywheelOrchestrator (BaseSkillImprover) so execute calls preserve potential
/// internal state/caches. Eliminates per-call reconstruction narrow place.
#[derive(Debug, Default)]
pub struct FlywheelStepImpl {
    inner: crate::FlywheelOrchestrator,
}

impl FlywheelStepImpl {
    pub fn new() -> Self {
        Self {
            inner: crate::FlywheelOrchestrator::new(),
        }
    }

    /// Primary entry (used by runner/CLI + future direct hooks).
    /// Delegates to full engine:
    ///   - real_data -> TrajectoryDataset + sidecar PRM enrich + compute_learning_value
    ///   - single-pass signal mining (no 20+ iters; fixes prior narrow CPU place)
    ///   - propose_with_llm_stub (heuristic + clean SPLIT basic LLM critique path)
    ///   - 15+ conditional rich sectioned proposals for max emission quality
    ///   - artifact writes (proposal.json, candidate_skill.yaml ultra-rich, manifest, README)
    ///   - manifest + rich_flywheel_export for consumers (promote, parity, health)
    ///
    /// Safe: &self, no interior mutation without sync.
    pub fn execute(&self, config: &FlywheelConfig) -> Result<FlywheelManifest> {
        self.inner.run_step(config)
    }
}

// Compile-time Send+Sync audit (data race prevention).
// Catches accidental !Sync (RefCell/Rc/UnsafeCell etc) at build time for types used
// from concurrent contexts (swarm dispatch, multiple after_task hooks, continuous timers,
// parallel CI/parity runs). (Uses stable fn-body check; avoids the invalid const-block
// call pattern that currently breaks agentforge-learning builds.)
#[allow(dead_code)]
fn _assert_flywheel_step_traits() {
    fn _assert_send_sync<T: Send + Sync>() {}
    _assert_send_sync::<FlywheelStepImpl>();
    _assert_send_sync::<crate::FlywheelOrchestrator>();
}
