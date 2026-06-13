use crate::dataset::TrajectoryDataset;
use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};

/// Common training hyperparameters.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TrainingConfig {
    pub method: String, // "dpo", "kto", "sft", etc.
    pub model_name: String,
    pub learning_rate: f64,
    pub epochs: u32,
    pub batch_size: u32,
    pub lora: bool,
    pub extra: serde_json::Value,
}

impl Default for TrainingConfig {
    fn default() -> Self {
        Self {
            method: "dpo".to_string(),
            model_name: "Qwen/Qwen2.5-7B-Instruct".to_string(),
            learning_rate: 5e-6,
            epochs: 1,
            batch_size: 4,
            lora: true,
            extra: serde_json::json!({}),
        }
    }
}

/// Result of a training run (or dry-run / preparation).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TrainingRun {
    pub run_id: String,
    pub method: String,
    pub config: TrainingConfig,
    pub prepared_data_path: Option<PathBuf>,
    pub output_dir: Option<PathBuf>,
    pub status: String,
    pub started_at: String,
    pub finished_at: Option<String>,
}

/// Abstract trainer interface.
pub trait BaseTrainer {
    fn prepare_dataset(
        &self,
        dataset: &TrajectoryDataset,
        output_dir: Option<PathBuf>,
    ) -> Result<PathBuf, String>;

    fn train(
        &self,
        prepared_data: &Path,
        config: &TrainingConfig,
        output_dir: Option<PathBuf>,
    ) -> Result<TrainingRun, String>;
}

/// Simple DPO trainer stub (data preparation focused for now).
pub struct DPOTrainer;

impl BaseTrainer for DPOTrainer {
    fn prepare_dataset(
        &self,
        dataset: &TrajectoryDataset,
        output_dir: Option<PathBuf>,
    ) -> Result<PathBuf, String> {
        let out_dir = output_dir.unwrap_or_else(|| PathBuf::from("training_ready/dpo"));
        std::fs::create_dir_all(&out_dir).map_err(|e| e.to_string())?;

        let pairs = dataset.export_preference_pairs();
        let path = out_dir.join("preference_pairs.jsonl");

        let mut file = std::fs::File::create(&path).map_err(|e| e.to_string())?;
        for p in pairs {
            use std::io::Write;
            writeln!(file, "{}", serde_json::to_string(&p).unwrap()).map_err(|e| e.to_string())?;
        }

        Ok(path)
    }

    fn train(
        &self,
        _prepared_data: &Path,
        config: &TrainingConfig,
        output_dir: Option<PathBuf>,
    ) -> Result<TrainingRun, String> {
        // In real implementation: call TRL / axolotl / etc.
        // For now: dry-run artifact.
        Ok(TrainingRun {
            run_id: uuid::Uuid::new_v4().to_string(),
            method: config.method.clone(),
            config: config.clone(),
            prepared_data_path: Some(_prepared_data.to_path_buf()),
            output_dir,
            status: "dry_run".to_string(),
            started_at: chrono::Utc::now().to_rfc3339(),
            finished_at: None,
        })
    }
}

/// KTO (Knowledge-to-Outcome) trainer: labels examples as desirable/undesirable.
pub struct KTOTrainer;

impl BaseTrainer for KTOTrainer {
    fn prepare_dataset(
        &self,
        dataset: &TrajectoryDataset,
        output_dir: Option<PathBuf>,
    ) -> Result<PathBuf, String> {
        let out_dir = output_dir.unwrap_or_else(|| PathBuf::from("training_ready/kto"));
        std::fs::create_dir_all(&out_dir).map_err(|e| e.to_string())?;

        let kto_examples: Vec<_> = dataset
            .records
            .iter()
            .map(|rec| {
                let desirable = rec.outcome == crate::types::Outcome::Success
                    && rec.prm_overall.unwrap_or(0.0) >= 0.6;
                serde_json::json!({
                    "task_id": rec.task_id,
                    "benchmark_id": rec.benchmark_id,
                    "events": rec.events,
                    "label": if desirable { "desirable" } else { "undesirable" },
                    "prm": rec.prm_overall,
                    "outcome": rec.outcome,
                })
            })
            .collect();

        let path = out_dir.join("kto_examples.jsonl");
        let mut file = std::fs::File::create(&path).map_err(|e| e.to_string())?;
        for ex in kto_examples {
            use std::io::Write;
            writeln!(file, "{}", serde_json::to_string(&ex).unwrap()).map_err(|e| e.to_string())?;
        }
        Ok(path)
    }

    fn train(
        &self,
        prepared_data: &Path,
        config: &TrainingConfig,
        output_dir: Option<PathBuf>,
    ) -> Result<TrainingRun, String> {
        Ok(TrainingRun {
            run_id: uuid::Uuid::new_v4().to_string(),
            method: "kto".to_string(),
            config: config.clone(),
            prepared_data_path: Some(prepared_data.to_path_buf()),
            output_dir,
            status: "dry_run".to_string(),
            started_at: chrono::Utc::now().to_rfc3339(),
            finished_at: None,
        })
    }
}

/// SFT (Supervised Fine-Tuning) trainer: success trajectories as gold completions.
pub struct SFTTrainer;

impl BaseTrainer for SFTTrainer {
    fn prepare_dataset(
        &self,
        dataset: &TrajectoryDataset,
        output_dir: Option<PathBuf>,
    ) -> Result<PathBuf, String> {
        let out_dir = output_dir.unwrap_or_else(|| PathBuf::from("training_ready/sft"));
        std::fs::create_dir_all(&out_dir).map_err(|e| e.to_string())?;

        let successes: Vec<_> = dataset
            .records
            .iter()
            .filter(|r| r.outcome == crate::types::Outcome::Success)
            .map(|rec| {
                serde_json::json!({
                    "task_id": rec.task_id,
                    "benchmark_id": rec.benchmark_id,
                    "agent": rec.agent,
                    "events": rec.events,
                    "prm": rec.prm_overall,
                    "duration": rec.duration_seconds,
                })
            })
            .collect();

        let path = out_dir.join("sft_success_trajectories.jsonl");
        let mut file = std::fs::File::create(&path).map_err(|e| e.to_string())?;
        for s in successes {
            use std::io::Write;
            writeln!(file, "{}", serde_json::to_string(&s).unwrap()).map_err(|e| e.to_string())?;
        }
        Ok(path)
    }

    fn train(
        &self,
        prepared_data: &Path,
        config: &TrainingConfig,
        output_dir: Option<PathBuf>,
    ) -> Result<TrainingRun, String> {
        Ok(TrainingRun {
            run_id: uuid::Uuid::new_v4().to_string(),
            method: "sft".to_string(),
            config: config.clone(),
            prepared_data_path: Some(prepared_data.to_path_buf()),
            output_dir,
            status: "dry_run".to_string(),
            started_at: chrono::Utc::now().to_rfc3339(),
            finished_at: None,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::dataset::TrajectoryDataset;
    use crate::types::{Outcome, TrajectoryRecord};
    use std::collections::HashMap;

    fn minimal_rec(id: &str, outcome: Outcome) -> TrajectoryRecord {
        TrajectoryRecord {
            task_id: id.into(),
            benchmark_id: "bench".into(),
            agent: "a".into(),
            outcome,
            real_task_id: None,
            prm_overall: Some(0.8),
            prm_high_quality_steps: None,
            prm_low_quality_steps: None,
            prm_step_labels: None,
            prm_suggestions: None,
            duration_seconds: 0.0,
            steps_taken: 0,
            tool_calls: 0,
            cost_usd: 0.0,
            error_message: None,
            events: vec![],
            judge_notes: None,
            quality_score: None,
            learning_value_score: 0.0,
            trajectory_path: None,
            evaluated_at: None,
            metadata: HashMap::new(),
        }
    }

    #[test]
    fn trainers_prepare_and_dryrun() {
        let mut ds = TrajectoryDataset::new("t");
        ds.add(minimal_rec("r1", Outcome::Success));
        let cfg = TrainingConfig::default();

        let dpo = DPOTrainer;
        let p = dpo.prepare_dataset(&ds, None).unwrap();
        let run = dpo.train(&p, &cfg, None).unwrap();
        assert_eq!(run.status, "dry_run");

        let kto = KTOTrainer;
        let p2 = kto.prepare_dataset(&ds, None).unwrap();
        assert!(p2.to_string_lossy().contains("kto"));

        let sft = SFTTrainer;
        let _ = sft.prepare_dataset(&ds, None).unwrap();
    }
}
