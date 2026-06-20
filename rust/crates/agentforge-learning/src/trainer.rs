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

impl TrainingConfig {
    /// Lightweight validation for common misconfigs that would cause downstream
    /// training (or even dry-run bookkeeping) to misbehave. Called from trainers.
    pub fn validate(&self) -> Result<(), String> {
        if self.method.trim().is_empty() {
            return Err("training method must not be empty".to_string());
        }
        if self.batch_size == 0 {
            return Err("batch_size must be > 0".to_string());
        }
        if self.epochs == 0 {
            return Err("epochs must be > 0".to_string());
        }
        if self.learning_rate <= 0.0 {
            return Err("learning_rate must be > 0".to_string());
        }
        // model_name and extra are intentionally permissive
        Ok(())
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
        // Swarm safety: for default output_dir (None) use unique run- subdir so concurrent
        // prepares (e.g. from multiple swarm tasks) never race on the *same* preference_pairs.jsonl.
        // When explicit output_dir provided, caller is responsible for uniqueness; we still protect
        // the final file from partial writes via tmp+rename.
        let out_dir = if let Some(d) = output_dir {
            d
        } else {
            let base = PathBuf::from("training_ready/dpo");
            let rid: String = uuid::Uuid::new_v4().simple().to_string();
            base.join(format!("run-{}", &rid[..8]))
        };
        std::fs::create_dir_all(&out_dir).map_err(|e| e.to_string())?;

        let pairs = dataset.export_preference_pairs();
        let path = out_dir.join("preference_pairs.jsonl");

        // Atomic buffered write: prevents interleaved corrupt JSONL on concurrent writers to same target
        // (last writer wins with a *complete* valid file; no torn writes).
        let tmp = out_dir.join(format!(".pref.tmp-{}", uuid::Uuid::new_v4()));
        {
            let file = std::fs::File::create(&tmp).map_err(|e| e.to_string())?;
            let mut w = std::io::BufWriter::new(file);
            use std::io::Write;
            for p in pairs {
                writeln!(w, "{}", serde_json::to_string(&p).unwrap()).map_err(|e| e.to_string())?;
            }
            w.flush().map_err(|e| e.to_string())?;
        }
        std::fs::rename(&tmp, &path).map_err(|e| e.to_string())?;

        Ok(path)
    }

    fn train(
        &self,
        prepared_data: &Path,
        config: &TrainingConfig,
        output_dir: Option<PathBuf>,
    ) -> Result<TrainingRun, String> {
        config.validate()?;
        // In real implementation: call TRL / axolotl / etc.
        // For now: dry-run artifact.
        Ok(TrainingRun {
            run_id: uuid::Uuid::new_v4().to_string(),
            method: config.method.clone(),
            config: config.clone(),
            prepared_data_path: Some(prepared_data.to_path_buf()),
            output_dir,
            status: "dry_run".to_string(),
            started_at: chrono::Utc::now().to_rfc3339(),
            finished_at: Some(chrono::Utc::now().to_rfc3339()),
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
        // Swarm safety: unique run- subdir on implicit default (see DPOTrainer for rationale).
        let out_dir = if let Some(d) = output_dir {
            d
        } else {
            let base = PathBuf::from("training_ready/kto");
            let rid: String = uuid::Uuid::new_v4().simple().to_string();
            base.join(format!("run-{}", &rid[..8]))
        };
        std::fs::create_dir_all(&out_dir).map_err(|e| e.to_string())?;

        // Stream directly over records (no Vec<json> allocation) + buffered atomic write:
        // eliminates the main memory/alloc bottleneck for large trajectory datasets.
        let path = out_dir.join("kto_examples.jsonl");
        let tmp = out_dir.join(format!(".kto.tmp-{}", uuid::Uuid::new_v4()));
        {
            let file = std::fs::File::create(&tmp).map_err(|e| e.to_string())?;
            let mut w = std::io::BufWriter::new(file);
            use std::io::Write;
            for rec in &dataset.records {
                let desirable = rec.outcome == crate::types::Outcome::Success
                    && rec.prm_overall.unwrap_or(0.0) >= 0.6;
                let ex = serde_json::json!({
                    "task_id": rec.task_id,
                    "benchmark_id": rec.benchmark_id,
                    "events": rec.events,
                    "label": if desirable { "desirable" } else { "undesirable" },
                    "prm": rec.prm_overall,
                    "outcome": rec.outcome,
                });
                writeln!(w, "{}", serde_json::to_string(&ex).unwrap())
                    .map_err(|e| e.to_string())?;
            }
            w.flush().map_err(|e| e.to_string())?;
        }
        std::fs::rename(&tmp, &path).map_err(|e| e.to_string())?;
        Ok(path)
    }

    fn train(
        &self,
        prepared_data: &Path,
        config: &TrainingConfig,
        output_dir: Option<PathBuf>,
    ) -> Result<TrainingRun, String> {
        config.validate()?;
        Ok(TrainingRun {
            run_id: uuid::Uuid::new_v4().to_string(),
            method: if config.method.is_empty() {
                "kto".to_string()
            } else {
                config.method.clone()
            },
            config: config.clone(),
            prepared_data_path: Some(prepared_data.to_path_buf()),
            output_dir,
            status: "dry_run".to_string(),
            started_at: chrono::Utc::now().to_rfc3339(),
            finished_at: Some(chrono::Utc::now().to_rfc3339()),
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
        // Swarm safety: unique run- subdir on implicit default (see DPOTrainer for rationale).
        let out_dir = if let Some(d) = output_dir {
            d
        } else {
            let base = PathBuf::from("training_ready/sft");
            let rid: String = uuid::Uuid::new_v4().simple().to_string();
            base.join(format!("run-{}", &rid[..8]))
        };
        std::fs::create_dir_all(&out_dir).map_err(|e| e.to_string())?;

        // Stream directly (filter+map iterator, no intermediate Vec allocation) + BufWriter + atomic rename.
        let path = out_dir.join("sft_success_trajectories.jsonl");
        let tmp = out_dir.join(format!(".sft.tmp-{}", uuid::Uuid::new_v4()));
        {
            let file = std::fs::File::create(&tmp).map_err(|e| e.to_string())?;
            let mut w = std::io::BufWriter::new(file);
            use std::io::Write;
            for rec in dataset
                .records
                .iter()
                .filter(|r| r.outcome == crate::types::Outcome::Success)
            {
                let s = serde_json::json!({
                    "task_id": rec.task_id,
                    "benchmark_id": rec.benchmark_id,
                    "agent": rec.agent,
                    "events": rec.events,
                    "prm": rec.prm_overall,
                    "duration": rec.duration_seconds,
                });
                writeln!(w, "{}", serde_json::to_string(&s).unwrap()).map_err(|e| e.to_string())?;
            }
            w.flush().map_err(|e| e.to_string())?;
        }
        std::fs::rename(&tmp, &path).map_err(|e| e.to_string())?;
        Ok(path)
    }

    fn train(
        &self,
        prepared_data: &Path,
        config: &TrainingConfig,
        output_dir: Option<PathBuf>,
    ) -> Result<TrainingRun, String> {
        config.validate()?;
        Ok(TrainingRun {
            run_id: uuid::Uuid::new_v4().to_string(),
            method: if config.method.is_empty() {
                "sft".to_string()
            } else {
                config.method.clone()
            },
            config: config.clone(),
            prepared_data_path: Some(prepared_data.to_path_buf()),
            output_dir,
            status: "dry_run".to_string(),
            started_at: chrono::Utc::now().to_rfc3339(),
            finished_at: Some(chrono::Utc::now().to_rfc3339()),
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
        assert!(run.finished_at.is_some());

        let kto = KTOTrainer;
        let p2 = kto.prepare_dataset(&ds, None).unwrap();
        assert!(p2.to_string_lossy().contains("kto"));

        let sft = SFTTrainer;
        let _ = sft.prepare_dataset(&ds, None).unwrap();

        // Validation coverage (new in audit fix)
        let mut bad = cfg.clone();
        bad.batch_size = 0;
        assert!(dpo.train(&p, &bad, None).is_err());
        bad = cfg.clone();
        bad.learning_rate = 0.0;
        assert!(kto.train(&p2, &bad, None).is_err());
    }
}
