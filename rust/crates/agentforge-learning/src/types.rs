use serde::{Deserialize, Serialize};
use std::collections::HashMap;

/// Outcome of a task execution.
///
/// **Canonical single source of truth**: `agentforge_core::Outcome`.
/// Re-exported here for ergonomic `use agentforge_learning::Outcome`.
/// All crates use this for serde, cross-crate, Phase 2/3 flywheel.
///
/// Conversions available (unified):
/// - `Outcome::from("success")` / `Outcome::from("partial_success")` (lenient, bad->Failure)
/// - `"foo".parse::<Outcome>()` (strict, via FromStr)
/// - `String::from(outcome)`, `outcome.to_string()`
/// - Direct variants: `Outcome::Success` etc.
pub use agentforge_core::Outcome;

/// Transitional alias for legacy code using `learning::CoreOutcome` (same type).
pub use agentforge_core::Outcome as CoreOutcome;

fn default_failure_outcome() -> Outcome {
    Outcome::Failure
}

/// Per-step PRM label (for training process reward models / critics).
#[derive(Debug, Clone, Serialize, Deserialize, Default, PartialEq)]
#[serde(default)]
pub struct PRMStepLabel {
    pub index: usize,
    pub event_type: String,
    pub score: f64,
    pub reasons: Vec<String>,
    pub confidence: Option<f64>,
}

/// Canonical rich record for learning (one trajectory + rich labels).
/// Mirrors the Python TrajectoryRecord for easy file-based interop.
/// Implements Default (via inherent + trait) for ergonomic minimal construction + mutation
/// in tests, edges and flywheel (e.g. `let mut r = TrajectoryRecord::default(); r.xxx = ...`).
/// Serde is tolerant to missing fields (defaults applied) for robust Python/JSONL interop.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(default)]
pub struct TrajectoryRecord {
    pub task_id: String,
    pub benchmark_id: String,
    pub agent: String,
    #[serde(default = "default_failure_outcome")]
    pub outcome: Outcome,
    pub real_task_id: Option<String>,

    // Phase 1+ signals
    pub prm_overall: Option<f64>,
    pub prm_high_quality_steps: Option<u32>,
    pub prm_low_quality_steps: Option<u32>,
    pub prm_step_labels: Option<Vec<PRMStepLabel>>,
    pub prm_suggestions: Option<Vec<String>>,

    // Execution metadata
    pub duration_seconds: f64,
    pub steps_taken: u32,
    pub tool_calls: u32,
    pub cost_usd: f64,
    pub error_message: Option<String>,

    // Rich content (normalized events)
    pub events: Vec<serde_json::Value>, // flexible for now; can be strongly typed later

    pub judge_notes: Option<String>,
    pub quality_score: Option<f64>,

    // Derived
    pub learning_value_score: f64,
    pub trajectory_path: Option<String>,
    pub evaluated_at: Option<String>,
    pub metadata: HashMap<String, serde_json::Value>,
}

impl std::default::Default for TrajectoryRecord {
    fn default() -> Self {
        TrajectoryRecord {
            task_id: String::new(),
            benchmark_id: String::new(),
            agent: String::new(),
            outcome: Outcome::Failure,
            real_task_id: None,
            prm_overall: None,
            prm_high_quality_steps: None,
            prm_low_quality_steps: None,
            prm_step_labels: None,
            prm_suggestions: None,
            duration_seconds: 0.0,
            steps_taken: 0,
            tool_calls: 0,
            cost_usd: 0.0,
            error_message: None,
            events: Vec::new(),
            judge_notes: None,
            quality_score: None,
            learning_value_score: 0.0,
            trajectory_path: None,
            evaluated_at: None,
            metadata: HashMap::new(),
        }
    }
}

impl TrajectoryRecord {
    /// Inherent `default()` so `TrajectoryRecord::default()` resolves in downstream crates
    /// (agentforge-flywheel tests etc.) even without `use std::default::Default;` in scope.
    /// Delegates to the trait impl. Enables the "minimal rec + mutate" pattern used for edges.
    #[allow(clippy::should_implement_trait)]
    pub fn default() -> Self {
        <Self as std::default::Default>::default()
    }

    pub fn is_high_quality(&self, min_prm: f64) -> bool {
        match self.prm_overall {
            Some(score) => score >= min_prm && self.outcome == Outcome::Success,
            None => self.outcome == Outcome::Success,
        }
    }
}
