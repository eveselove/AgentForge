//! Core types for the pure-Rust flywheel (Phase 1+).
//! Mirrors + extends Python ProposedSkill / improvement proposal structures
//! from learning/skill_improver.py and rust_flywheel_step.py artifacts.

use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::PathBuf;

/// Richer ProposedSkill for full flywheel (sectioned proposals per plan).
/// Current learning::ProposedSkill is the heuristic base; this is the target.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
#[serde(default)]
pub struct ProposedSkill {
    pub skill_name: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub new_system_prompt: Option<String>,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    pub suggested_few_shots: Vec<String>,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    pub suggested_ci_checks: Vec<String>,
    pub overall_rationale: String,
    pub estimated_impact: String,

    /// Sectioned / multi-proposal improvements (future parity with Python).
    #[serde(skip_serializing_if = "Vec::is_empty")]
    pub proposals: Vec<ImprovementProposal>,

    /// Rich provenance + learning signals.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub learning_meta: Option<LearningMeta>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub rust_pairs_used: Option<u64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub high_learning_value_records: Option<u64>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
#[serde(default)]
pub struct ImprovementProposal {
    pub section: String,
    pub rationale: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub before: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub after: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub confidence: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub estimated_delta: Option<String>,
}

impl ImprovementProposal {
    pub fn new(section: impl Into<String>, rationale: impl Into<String>) -> Self {
        Self {
            section: section.into(),
            rationale: rationale.into(),
            ..Default::default()
        }
    }

    /// Chainable, clamps confidence to [0.0, 1.0] to avoid invalid logical values.
    pub fn with_confidence(mut self, c: f64) -> Self {
        self.confidence = Some(c.clamp(0.0, 1.0));
        self
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
#[serde(default)]
pub struct SectionedPrompt {
    pub sections: HashMap<String, String>,
    pub full_prompt: String,
}

impl SectionedPrompt {
    /// Construct with sections and auto-sync full_prompt (prevents desync logical error).
    pub fn from_sections(sections: HashMap<String, String>) -> Self {
        let full_prompt = sections.values().cloned().collect::<Vec<_>>().join("\n\n");
        Self {
            sections,
            full_prompt,
        }
    }

    /// Rebuild full_prompt from current sections to enforce consistency.
    pub fn sync_full_prompt(&mut self) {
        self.full_prompt = self
            .sections
            .values()
            .cloned()
            .collect::<Vec<_>>()
            .join("\n\n");
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
#[serde(default)]
pub struct LearningMeta {
    pub source: String,
    pub record_count: u64,
    pub success_rate: f64,
    pub avg_learning_value: f64,
    pub high_value_count: u64,
    pub engine: String,
}

/// Config for a FlywheelStep run (maps to CLI flags + Python args).
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
#[serde(default)]
pub struct FlywheelConfig {
    pub skill_name: String,
    pub dry_run: bool,
    pub real_data: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub limit: Option<usize>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub slice: Option<String>,
    pub ingest: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub output_dir: Option<PathBuf>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub trajectories_dir: Option<PathBuf>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub prm_dir: Option<PathBuf>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub min_prm: Option<f64>,
    pub json_mode: bool,
}

/// The emitted manifest (flywheel_manifest.json + internal).
/// Must stay compatible with Python consumers during migration.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct FlywheelManifest {
    pub version: String,
    pub timestamp: String,
    pub engine: String,
    pub skill: String,
    pub dry_run: bool,
    pub status: String,

    #[serde(skip_serializing_if = "Vec::is_empty")]
    pub proposals: Vec<ImprovementProposal>,
    #[serde(skip_serializing_if = "HashMap::is_empty")]
    pub stats: HashMap<String, serde_json::Value>,
    #[serde(skip_serializing_if = "HashMap::is_empty")]
    pub artifact_paths: HashMap<String, String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub candidate_id: Option<String>,

    /// Full rich export bundle (or reference) for fidelity.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub rich_flywheel_export: Option<serde_json::Value>,
}

impl FlywheelManifest {
    pub fn new(skill: &str) -> Self {
        let now = chrono::Utc::now().to_rfc3339();
        Self {
            version: "flywheel-manifest-v1".to_string(),
            timestamp: now,
            engine: "rust-agentforge-runner/flywheel-step".to_string(),
            skill: skill.to_string(),
            dry_run: true,
            status: "pending".to_string(),
            proposals: vec![],
            stats: HashMap::new(),
            artifact_paths: HashMap::new(),
            candidate_id: None,
            rich_flywheel_export: None,
        }
    }
}

impl Default for FlywheelManifest {
    fn default() -> Self {
        Self::new("")
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn flywheel_types_manifest_new_defaults_and_mutation() {
        let m = FlywheelManifest::new("unit-manifest");
        assert_eq!(m.skill, "unit-manifest");
        assert!(m.dry_run);
        assert!(m.proposals.is_empty());
        assert!(m.stats.is_empty());
        assert!(m.version.contains("v1"));
    }

    #[test]
    fn improvement_proposal_and_sectioned_prompt_roundtrip_serde() {
        // Covers improved emission types used in orchestrator
        let p = ImprovementProposal {
            section: "recovery_strategy".into(),
            rationale: "data mined".into(),
            before: Some("old".into()),
            after: Some("new explicit".into()),
            confidence: Some(0.82),
            estimated_delta: Some("+8pp".into()),
        };
        let j = serde_json::to_string(&p).expect("ser");
        let p2: ImprovementProposal = serde_json::from_str(&j).expect("de");
        assert_eq!(p2.section, "recovery_strategy");
        assert_eq!(p2.confidence, Some(0.82));

        let mut secs: std::collections::HashMap<String, String> = std::collections::HashMap::new();
        secs.insert("system".into(), "You are...".into());
        let sp = SectionedPrompt::from_sections(secs);
        let sj = serde_json::to_string(&sp).unwrap();
        let sp2: SectionedPrompt = serde_json::from_str(&sj).unwrap();
        assert_eq!(sp2.sections.len(), 1);
        assert!(sp2.full_prompt.contains("You are"));
    }

    #[test]
    fn flywheel_config_defaults_support_continuous_and_shadow_paths() {
        let c: FlywheelConfig = Default::default();
        assert!(c.skill_name.is_empty());
        assert!(!c.real_data);
        // dry_run default false (derive); explicit true used for safe dry/continuous/shadow preview paths
        let _ = c.dry_run;
        assert!(c.limit.is_none());
        // shadow handled at runner layer but config drives emission for flywheel-step
        let mut c2 = FlywheelConfig {
            skill_name: "cont".into(),
            dry_run: true,
            real_data: false,
            ..Default::default()
        };
        c2.output_dir = Some(std::path::PathBuf::from("/tmp/fw"));
        assert_eq!(c2.skill_name, "cont");
    }

    #[test]
    fn learning_meta_and_proposed_skill_for_flywheel_emission() {
        let lm = LearningMeta {
            record_count: 42,
            avg_learning_value: 0.67,
            engine: "rust-phase1".into(),
            ..Default::default()
        };
        let j = serde_json::to_string(&lm).unwrap();
        assert!(j.contains("0.67"));

        let ps = ProposedSkill {
            skill_name: "emit-skill".into(),
            overall_rationale: "mined failures".into(),
            estimated_impact: "high".into(),
            proposals: vec![ImprovementProposal {
                section: "tool_use".into(),
                ..Default::default()
            }],
            ..Default::default()
        };
        assert_eq!(ps.proposals.len(), 1);
        let pj = serde_json::to_string(&ps).unwrap();
        assert!(pj.contains("emit-skill"));
    }

    #[test]
    fn flywheel_config_disable_paths_and_shadow_env_compat() {
        // Covers config used by runner for --shadow, continuous dry/disable heavy paths, min_prm disable
        let mut c = FlywheelConfig {
            skill_name: "disable-test".into(),
            dry_run: true,
            real_data: false,
            limit: Some(0),
            min_prm: Some(0.0),
            ..Default::default()
        };
        c.json_mode = true;
        assert!(c.dry_run && c.limit == Some(0));
        let j = serde_json::to_string(&c).unwrap();
        let c2: FlywheelConfig = serde_json::from_str(&j).unwrap();
        assert_eq!(c2.min_prm, Some(0.0));
    }

    #[test]
    fn improvement_proposal_full_fields_for_rich_flywheel_emission() {
        let p = ImprovementProposal {
            section: "checkpointing".into(),
            rationale: "long horizon disable recovery risk".into(),
            before: Some("no checkpoints".into()),
            after: Some("write state every 3 steps".into()),
            confidence: Some(0.66),
            estimated_delta: Some("+high on resume".into()),
        };
        let j = serde_json::to_string(&p).unwrap();
        assert!(j.contains("checkpointing") && j.contains("0.66"));
        let p2: ImprovementProposal = serde_json::from_str(&j).unwrap();
        assert_eq!(p2.section, "checkpointing");
        assert!(p2.estimated_delta.unwrap().contains("high"));
    }
}
