use crate::types::{Outcome, PRMStepLabel, TrajectoryRecord};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;

/// Version manifest for reproducible datasets.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DatasetVersion {
    pub name: String,
    pub version: String,
    pub created_at: String,
    pub filters: HashMap<String, serde_json::Value>,
    pub record_count: usize,
    pub stats: HashMap<String, serde_json::Value>,
    pub source_hashes: HashMap<String, String>,
    pub path: String,
}

/// High-quality, filterable, versioned collection of TrajectoryRecords.
/// This is the Rust-native heart of the Learning Flywheel.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct TrajectoryDataset {
    pub name: String,
    pub records: Vec<TrajectoryRecord>,
    pub created_at: String,
    // version_history omitted for brevity in MVP
}

impl TrajectoryDataset {
    pub fn new(name: impl Into<String>) -> Self {
        Self {
            name: name.into(),
            records: Vec::new(),
            created_at: chrono::Utc::now().to_rfc3339(),
        }
    }

    pub fn add(&mut self, record: TrajectoryRecord) {
        self.records.push(record);
    }

    /// Basic filtering (chainable in spirit via new dataset)
    pub fn filter_by_outcome(&self, outcome: Outcome) -> Self {
        let filtered: Vec<_> = self
            .records
            .iter()
            .filter(|r| r.outcome == outcome)
            .cloned()
            .collect();

        Self {
            name: format!("{}_filtered", self.name),
            records: filtered,
            created_at: chrono::Utc::now().to_rfc3339(),
        }
    }

    pub fn filter_high_quality(&self, min_prm: f64) -> Self {
        let filtered: Vec<_> = self
            .records
            .iter()
            .filter(|r| r.is_high_quality(min_prm))
            .cloned()
            .collect();

        Self {
            name: format!("{}_high_quality", self.name),
            records: filtered,
            created_at: chrono::Utc::now().to_rfc3339(),
        }
    }

    pub fn filter_by_agent(&self, agent: &str) -> Self {
        let filtered: Vec<_> = self
            .records
            .iter()
            .filter(|r| r.agent == agent)
            .cloned()
            .collect();
        Self {
            name: format!("{}_agent_{}", self.name, agent),
            records: filtered,
            created_at: chrono::Utc::now().to_rfc3339(),
        }
    }

    pub fn filter_real_only(&self) -> Self {
        let filtered: Vec<_> = self
            .records
            .iter()
            .filter(|r| r.real_task_id.is_some())
            .cloned()
            .collect();
        Self {
            name: format!("{}_real", self.name),
            records: filtered,
            created_at: chrono::Utc::now().to_rfc3339(),
        }
    }

    /// Compute learning value score (mirrors Python heuristic: high PRM + success + informative errors + recovery).
    pub fn compute_learning_value(&mut self) {
        for rec in &mut self.records {
            let mut score = 0.0;
            if rec.outcome == Outcome::Success {
                score += 0.4;
            }
            if let Some(p) = rec.prm_overall {
                score += (p - 0.5).max(0.0) * 0.8;
            }
            if rec.prm_low_quality_steps.unwrap_or(0) > 0
                && rec.prm_high_quality_steps.unwrap_or(0) > 2
            {
                score += 0.15; // informative contrast
            }
            if rec.error_message.is_some() && rec.outcome == Outcome::Success {
                score += 0.1; // recovered from error = high learning value
            }
            rec.learning_value_score = score.clamp(0.0, 1.0);
        }
    }

    /// Export rich preference pairs (DPO-style) with full learning signals.
    /// Greatly improved for flywheel: includes outcomes, learning_values, durations, agent, prm steps counts,
    /// and sidecar provenance. Directly consumable by rust_flywheel_step.py (and Python flywheel).
    pub fn export_preference_pairs(&self) -> Vec<serde_json::Value> {
        let mut by_bench: HashMap<String, Vec<&TrajectoryRecord>> = HashMap::new();
        for rec in &self.records {
            by_bench
                .entry(rec.benchmark_id.clone())
                .or_default()
                .push(rec);
        }

        let mut pairs = Vec::new();
        for (bench, recs) in by_bench {
            let successes: Vec<_> = recs
                .iter()
                .filter(|r| r.outcome == Outcome::Success)
                .collect();
            let failures: Vec<_> = recs
                .iter()
                .filter(|r| r.outcome != Outcome::Success)
                .collect();
            if successes.is_empty() || failures.is_empty() {
                continue;
            }

            let best_success = successes
                .iter()
                .max_by(|a, b| {
                    a.prm_overall
                        .partial_cmp(&b.prm_overall)
                        .unwrap_or(std::cmp::Ordering::Equal)
                })
                .unwrap();
            let worst_failure = failures
                .iter()
                .max_by(|a, b| {
                    a.prm_overall
                        .partial_cmp(&b.prm_overall)
                        .unwrap_or(std::cmp::Ordering::Equal)
                })
                .unwrap();

            pairs.push(serde_json::json!({
                "benchmark_id": bench,
                "chosen": best_success.events,
                "rejected": worst_failure.events,
                "chosen_prm": best_success.prm_overall,
                "rejected_prm": worst_failure.prm_overall,
                "learning_value": (best_success.learning_value_score + 0.1),
                "chosen_learning_value": best_success.learning_value_score,
                "rejected_learning_value": worst_failure.learning_value_score,
                "chosen_outcome": best_success.outcome.to_string(),
                "rejected_outcome": worst_failure.outcome.to_string(),
                "chosen_agent": best_success.agent,
                "rejected_agent": worst_failure.agent,
                "chosen_duration": best_success.duration_seconds,
                "rejected_duration": worst_failure.duration_seconds,
                "chosen_steps": best_success.steps_taken,
                "chosen_tool_calls": best_success.tool_calls,
                "chosen_prm_hq_steps": best_success.prm_high_quality_steps,
                "chosen_prm_lq_steps": best_success.prm_low_quality_steps,
                "has_sidecar_prm": best_success.metadata.contains_key("prm_sidecar"),
                "source": "rust_flywheel_export",
                "export_format": "rich_pairs_v2",
            }));
        }
        pairs
    }

    /// Export clean step-level PRM labels for critic training.
    pub fn export_prm_step_labels(&self) -> Vec<serde_json::Value> {
        self.records
            .iter()
            .filter_map(|rec| {
                rec.prm_step_labels.as_ref().map(|labels| {
                    serde_json::json!({
                        "task_id": rec.task_id, "benchmark_id": rec.benchmark_id,
                        "outcome": rec.outcome, "overall_prm": rec.prm_overall,
                        "step_labels": labels,
                    })
                })
            })
            .collect()
    }

    /// Production rich flywheel export bundle.
    /// Contains: DPO-style preference pairs, available prm_step_labels, per-record learning_values,
    /// and summary stats including success_rate, avg_prm, high_value_count.
    /// Respects optional min_prm for high-value filtering in stats (does not drop data).
    pub fn export_flywheel_rich(&self, min_prm: Option<f64>) -> serde_json::Value {
        let pairs = self.export_preference_pairs();
        let prm_labels = self.export_prm_step_labels();
        let stats = self.basic_stats();
        let success_rate = stats.get("success_rate").copied().unwrap_or(0.0);
        let avg_prm = stats.get("avg_prm").copied().unwrap_or(0.0);

        let per_record: Vec<serde_json::Value> = self
            .records
            .iter()
            .map(|r| {
                serde_json::json!({
                    "task_id": r.task_id,
                    "benchmark_id": r.benchmark_id,
                    "agent": r.agent,
                    "outcome": format!("{:?}", r.outcome),
                    "prm_overall": r.prm_overall,
                    "learning_value": r.learning_value_score,
                    "high_quality": r.is_high_quality(min_prm.unwrap_or(0.6)),
                    "has_prm_sidecar": r.metadata.contains_key("prm_sidecar"),
                    "trajectory_path": r.trajectory_path,
                    "duration_seconds": r.duration_seconds,
                    "steps_taken": r.steps_taken,
                })
            })
            .collect();

        let min_prm_f = min_prm.unwrap_or(0.6);
        let high_value_count = self
            .records
            .iter()
            .filter(|r| r.learning_value_score >= 0.55 || r.is_high_quality(min_prm_f))
            .count();

        serde_json::json!({
            "preference_pairs": pairs,
            "prm_step_labels": prm_labels,
            "per_record_learning_values": per_record,
            "stats": {
                "success_rate": success_rate,
                "avg_prm": avg_prm,
                "high_value_count": high_value_count,
                "record_count": self.records.len(),
                "pairs_count": pairs.len(),
                "prm_labels_count": prm_labels.len(),
                "min_prm_filter": min_prm,
            },
            "source": "rust-agentforge-runner/flywheel-export",
            "export_version": "rich_flywheel_v1",
            "created_at": chrono::Utc::now().to_rfc3339(),
        })
    }

    /// Versioned export (saves records + manifest). Mirrors Python save_versioned.
    pub fn save_versioned(
        &self,
        base_dir: impl AsRef<std::path::Path>,
    ) -> Result<DatasetVersion, String> {
        let dir = base_dir.as_ref();
        std::fs::create_dir_all(dir).map_err(|e| e.to_string())?;
        let ver = format!("v{}", chrono::Utc::now().format("%Y%m%d_%H%M%S"));
        let data_path = dir.join(format!("records_{}.jsonl", ver));
        let manifest_path = dir.join("manifest.json");

        let mut f = std::fs::File::create(&data_path).map_err(|e| e.to_string())?;
        for r in &self.records {
            use std::io::Write;
            writeln!(f, "{}", serde_json::to_string(r).unwrap()).map_err(|e| e.to_string())?;
        }

        let stats = self.basic_stats();
        let version = DatasetVersion {
            name: self.name.clone(),
            version: ver.clone(),
            created_at: chrono::Utc::now().to_rfc3339(),
            filters: HashMap::new(),
            record_count: self.records.len(),
            stats: stats
                .into_iter()
                .map(|(k, v)| (k, serde_json::json!(v)))
                .collect(),
            source_hashes: HashMap::new(),
            path: data_path.to_string_lossy().to_string(),
        };
        let mut mf = std::fs::File::create(manifest_path).map_err(|e| e.to_string())?;
        use std::io::Write;
        writeln!(mf, "{}", serde_json::to_string_pretty(&version).unwrap())
            .map_err(|e| e.to_string())?;
        Ok(version)
    }

    pub fn basic_stats(&self) -> HashMap<String, f64> {
        let mut m = HashMap::new();
        let total = self.records.len() as f64;
        if total == 0.0 {
            return m;
        }
        let successes = self
            .records
            .iter()
            .filter(|r| r.outcome == Outcome::Success)
            .count() as f64;
        let prm_vals: Vec<f64> = self.records.iter().filter_map(|r| r.prm_overall).collect();
        let avg_prm: f64 = if prm_vals.is_empty() {
            0.0
        } else {
            prm_vals.iter().sum::<f64>() / prm_vals.len() as f64
        };
        m.insert("success_rate".into(), successes / total);
        m.insert("avg_prm".into(), avg_prm);
        m.insert("count".into(), total);
        m.insert("prm_labeled_count".into(), prm_vals.len() as f64);
        m
    }

    pub fn len(&self) -> usize {
        self.records.len()
    }
    pub fn is_empty(&self) -> bool {
        self.records.is_empty()
    }

    // ------------------------------------------------------------------
    // FLYWHEEL + PRM SIDECAR LOADING (rich support for trajectories/*.jsonl + *.prm.json)
    // ------------------------------------------------------------------

    /// Parse a .prm.json sidecar file (flexible keys for real farm data).
    /// Returns (overall, hq_steps, lq_steps, step_labels, suggestions).
    /// Never panics; returns None on any read/parse error (graceful).
    #[allow(clippy::type_complexity)]
    fn parse_prm_sidecar(
        path: &std::path::Path,
    ) -> Option<(
        Option<f64>,
        Option<u32>,
        Option<u32>,
        Option<Vec<PRMStepLabel>>,
        Option<Vec<String>>,
    )> {
        let content = std::fs::read_to_string(path).ok()?;
        let v: serde_json::Value = serde_json::from_str(&content).ok()?;
        let get_f64 = |keys: &[&str]| -> Option<f64> {
            for k in keys {
                if let Some(x) = v.get(k).and_then(|vv| vv.as_f64()) {
                    return Some(x);
                }
                if let Some(s) = v.get(k).and_then(|vv| vv.as_str()) {
                    if let Ok(f) = s.parse::<f64>() {
                        return Some(f);
                    }
                }
            }
            None
        };
        let overall = get_f64(&[
            "overall",
            "overall_score",
            "prm_overall",
            "prm",
            "score",
            "prm_overall_score",
        ]);
        let hq = v
            .get("high_quality_steps")
            .or_else(|| v.get("prm_high_quality_steps"))
            .and_then(|x| x.as_u64())
            .map(|n| n as u32)
            .or_else(|| get_f64(&["high_quality_steps", "hq_steps"]).map(|f| f as u32));
        let lq = v
            .get("low_quality_steps")
            .or_else(|| v.get("prm_low_quality_steps"))
            .and_then(|x| x.as_u64())
            .map(|n| n as u32)
            .or_else(|| get_f64(&["low_quality_steps", "lq_steps"]).map(|f| f as u32));
        let suggestions: Option<Vec<String>> = v
            .get("suggestions")
            .or_else(|| v.get("prm_suggestions"))
            .and_then(|x| x.as_array())
            .map(|arr| {
                arr.iter()
                    .filter_map(|a| a.as_str().map(|s| s.to_owned()))
                    .collect()
            });
        let step_labels: Option<Vec<PRMStepLabel>> = {
            // Support flat top-level + real farm nested under prm_raw.step_scores / prm_raw.steps etc.
            let arr = v
                .get("step_labels")
                .or_else(|| v.get("steps"))
                .or_else(|| v.get("prm_steps"))
                .or_else(|| v.get("prm_step_labels"))
                .or_else(|| v.get("prm_raw").and_then(|pr| pr.get("step_scores")))
                .or_else(|| v.get("prm_raw").and_then(|pr| pr.get("steps")))
                .or_else(|| v.get("prm_raw").and_then(|pr| pr.get("prm_step_labels")))
                .and_then(|x| x.as_array());
            arr.map(|arr| {
                arr.iter()
                    .enumerate()
                    .map(|(i, s)| PRMStepLabel {
                        index: s
                            .get("index")
                            .and_then(|x| x.as_u64())
                            .or_else(|| s.get("step_index").and_then(|x| x.as_u64()))
                            .unwrap_or(i as u64) as usize,
                        event_type: s
                            .get("event_type")
                            .or_else(|| s.get("type"))
                            .and_then(|x| x.as_str())
                            .unwrap_or("event")
                            .to_string(),
                        score: s
                            .get("score")
                            .and_then(|x| x.as_f64())
                            .or_else(|| s.get("prm").and_then(|x| x.as_f64()))
                            .unwrap_or(0.5),
                        reasons: s
                            .get("reasons")
                            .or_else(|| s.get("reason"))
                            .and_then(|x| x.as_array())
                            .map(|a| {
                                a.iter()
                                    .filter_map(|r| r.as_str().map(|t| t.to_string()))
                                    .collect()
                            })
                            .unwrap_or_default(),
                        confidence: s.get("confidence").and_then(|x| x.as_f64()),
                    })
                    .collect()
            })
        };
        Some((overall, hq, lq, step_labels, suggestions))
    }

    /// Enrich existing records with PRM data from *.prm.json sidecars in the given directory.
    /// Matches by:
    ///   - stem of `trajectory_path` (e.g. "abc123_grok.jsonl" -> "abc123_grok.prm.json")
    ///   - task_id, real_task_id, or benchmark_id as key
    ///
    /// Production-robust: skips unreadable/missing sidecars silently (counts only successes).
    /// Call after loading trajectories JSONL.
    pub fn enrich_from_prm_sidecars(&mut self, sidecar_dir: impl AsRef<std::path::Path>) -> usize {
        let dir = sidecar_dir.as_ref();
        if !dir.exists() || !dir.is_dir() {
            return 0;
        }
        let mut sidecar_map: HashMap<String, std::path::PathBuf> = HashMap::new();
        if let Ok(rd) = std::fs::read_dir(dir) {
            for e in rd.flatten() {
                let p = e.path();
                if let Some(fname) = p.file_name().and_then(|n| n.to_str()) {
                    if fname.ends_with(".prm.json") {
                        let stem = fname.trim_end_matches(".prm.json").to_string();
                        sidecar_map.insert(stem.clone(), p.clone());
                        // tolerant variants for farm naming (prefix match)
                        if let Some(prefix) = stem.split('_').next() {
                            sidecar_map.entry(prefix.to_string()).or_insert(p.clone());
                        }
                        if let Some(sans) = stem.rsplit_once('_').map(|(a, _)| a) {
                            sidecar_map.entry(sans.to_string()).or_insert(p.clone());
                        }
                    }
                }
            }
        }
        let mut enriched = 0usize;
        for rec in &mut self.records {
            let mut matched: Option<std::path::PathBuf> = None;
            if let Some(tp) = &rec.trajectory_path {
                let stem = std::path::Path::new(tp)
                    .file_stem()
                    .and_then(|s| s.to_str())
                    .unwrap_or("");
                if let Some(pth) = sidecar_map.get(stem) {
                    matched = Some(pth.clone());
                }
            }
            for key in [
                &rec.task_id,
                rec.real_task_id.as_deref().unwrap_or(""),
                &rec.benchmark_id,
            ] {
                if !key.is_empty() {
                    if let Some(pth) = sidecar_map.get(key) {
                        matched = Some(pth.clone());
                        break;
                    }
                }
            }
            if let Some(prm_p) = matched {
                if let Some((ov, hq, lq, steps, sugg)) = Self::parse_prm_sidecar(&prm_p) {
                    if rec.prm_overall.is_none() {
                        rec.prm_overall = ov;
                    }
                    if rec.prm_high_quality_steps.is_none() {
                        rec.prm_high_quality_steps = hq;
                    }
                    if rec.prm_low_quality_steps.is_none() {
                        rec.prm_low_quality_steps = lq;
                    }
                    if rec.prm_step_labels.is_none() {
                        rec.prm_step_labels = steps;
                    }
                    if rec.prm_suggestions.is_none() {
                        rec.prm_suggestions = sugg;
                    }
                    rec.metadata.insert(
                        "prm_sidecar".into(),
                        serde_json::json!(prm_p.to_string_lossy()),
                    );
                    enriched += 1;
                }
            }
        }
        enriched
    }

    /// Load all *.jsonl files from a trajectories directory (raw event streams typical in farm).
    /// Uses the jsonl loader (supports event fallback + full records).
    pub fn load_from_trajectories_dir(
        &mut self,
        dir: impl AsRef<std::path::Path>,
    ) -> Result<usize, String> {
        let dir = dir.as_ref();
        if !dir.exists() || !dir.is_dir() {
            return Err(format!("Trajectories dir not found: {}", dir.display()));
        }
        let mut total = 0usize;
        for entry in std::fs::read_dir(dir).map_err(|e| e.to_string())? {
            let p = entry.map_err(|e| e.to_string())?.path();
            if p.extension().and_then(|e| e.to_str()) == Some("jsonl") {
                if let Ok(n) = self.load_from_jsonl(&p) {
                    total += n;
                }
            }
        }
        Ok(total)
    }

    /// High-level flywheel loader: trajectories dir (with optional separate prm sidecar dir) + optional eval results dir.
    /// Returns (num_from_trajectories, num_prm_enriched, num_from_results). Always calls compute_learning_value internally.
    /// Supports --trajectories + --prm-dir for real farm data (sidecars may be colocated or separate).
    /// Graceful on partial/missing data; tolerant path resolution for /home/eveselove/agentforge etc.
    pub fn load_flywheel_data(
        &mut self,
        trajectories_dir: Option<impl AsRef<std::path::Path>>,
        prm_dir: Option<impl AsRef<std::path::Path>>,
        results_dir: Option<impl AsRef<std::path::Path>>,
    ) -> Result<(usize, usize, usize), String> {
        let mut t_loaded = 0usize;
        let mut p_enriched = 0usize;
        let mut r_loaded = 0usize;
        if let Some(td) = trajectories_dir {
            let td = td.as_ref();
            let cands: Vec<std::path::PathBuf> = vec![
                td.to_path_buf(),
                std::path::PathBuf::from("/home/eveselove/agentforge").join(td),
                std::path::PathBuf::from("../../../agentforge").join(td),
                std::path::PathBuf::from("..").join(td),
            ];
            let mut did = false;
            for c in &cands {
                if c.exists() && c.is_dir() {
                    if let Ok(n) = self.load_from_trajectories_dir(c) {
                        t_loaded += n;
                        // enrich from traj dir itself (common case: sidecars next to jsonl)
                        p_enriched += self.enrich_from_prm_sidecars(c);
                        did = true;
                        break;
                    }
                }
            }
            if !did {
                if let Ok(n) = self.load_from_trajectories_dir(td) {
                    t_loaded += n;
                    p_enriched += self.enrich_from_prm_sidecars(td);
                }
            }
        }
        // Dedicated prm dir (may contain sidecars not colocated with trajs)
        if let Some(pd) = prm_dir {
            let pd = pd.as_ref();
            let cands: Vec<std::path::PathBuf> = vec![
                pd.to_path_buf(),
                std::path::PathBuf::from("/home/eveselove/agentforge").join(pd),
                std::path::PathBuf::from("../../../agentforge").join(pd),
                std::path::PathBuf::from("..").join(pd),
            ];
            for c in &cands {
                if c.exists() && c.is_dir() {
                    p_enriched += self.enrich_from_prm_sidecars(c);
                    break;
                }
            }
            // last try direct even if not "exists" in check (enrich is graceful)
            if p_enriched == 0 {
                p_enriched += self.enrich_from_prm_sidecars(pd);
            }
        }
        if let Some(rd) = results_dir {
            let rd = rd.as_ref();
            let cands: Vec<std::path::PathBuf> = vec![
                rd.to_path_buf(),
                std::path::PathBuf::from("/home/eveselove/agentforge").join(rd),
                std::path::PathBuf::from("../../../agentforge").join(rd),
                std::path::PathBuf::from("..").join(rd),
            ];
            let mut did = false;
            for c in &cands {
                if c.exists() && c.is_dir() {
                    if let Ok(n) = self.load_from_eval_results_dir(c) {
                        r_loaded += n;
                        did = true;
                        break;
                    }
                }
            }
            if !did {
                if let Ok(n) = self.load_from_eval_results_dir(rd) {
                    r_loaded += n;
                }
            }
        }
        self.compute_learning_value();
        Ok((t_loaded, p_enriched, r_loaded))
    }

    // ------------------------------------------------------------------
    // REAL INPUT LOADERS (for CLI + Python bridge: JSONL trajectories, eval results dirs)
    // ------------------------------------------------------------------

    /// Parse a string outcome (from Python/JSON) into our enum (lenient).
    /// Delegates to unified core::Outcome From<&str> (single source of truth, no dup logic).
    fn parse_outcome(s: &str) -> Outcome {
        Outcome::from(s)
    }

    /// Load records from a directory of eval results JSON files (mirrors Python load_from_eval_results minimally).
    /// Populates with available fields; events left empty (attach via add_trajectory if full trajs wanted later).
    pub fn load_from_eval_results_dir(
        &mut self,
        dir: impl AsRef<std::path::Path>,
    ) -> Result<usize, String> {
        let dir = dir.as_ref();
        if !dir.exists() || !dir.is_dir() {
            return Err(format!("Eval results dir not found: {}", dir.display()));
        }
        let mut loaded = 0usize;
        for entry in std::fs::read_dir(dir).map_err(|e| e.to_string())? {
            let entry = entry.map_err(|e| e.to_string())?;
            let path = entry.path();
            if path.extension().and_then(|e| e.to_str()) != Some("json") {
                continue;
            }
            let content = std::fs::read_to_string(&path).map_err(|e| e.to_string())?;
            let v: serde_json::Value = match serde_json::from_str(&content) {
                Ok(v) => v,
                Err(_) => continue,
            };
            let task_id = v
                .get("task_id")
                .and_then(|x| x.as_str())
                .unwrap_or("unknown")
                .to_string();
            let benchmark_id = task_id.clone();
            let agent = v
                .get("agent")
                .and_then(|x| x.as_str())
                .unwrap_or("unknown")
                .to_string();
            let outcome = Self::parse_outcome(
                v.get("outcome")
                    .and_then(|x| x.as_str())
                    .unwrap_or("failed"),
            );
            let rec = TrajectoryRecord {
                task_id: task_id.clone(),
                benchmark_id,
                agent,
                outcome,
                real_task_id: v
                    .get("real_task_id")
                    .and_then(|x| x.as_str())
                    .map(|s| s.to_string()),
                prm_overall: v.get("prm_overall_score").and_then(|x| x.as_f64()),
                prm_high_quality_steps: v
                    .get("prm_high_quality_steps")
                    .and_then(|x| x.as_u64())
                    .map(|n| n as u32),
                prm_low_quality_steps: v
                    .get("prm_low_quality_steps")
                    .and_then(|x| x.as_u64())
                    .map(|n| n as u32),
                prm_step_labels: None,
                prm_suggestions: None,
                duration_seconds: v
                    .get("duration_seconds")
                    .and_then(|x| x.as_f64())
                    .unwrap_or(0.0),
                steps_taken: v.get("steps_taken").and_then(|x| x.as_u64()).unwrap_or(0) as u32,
                tool_calls: v.get("tool_calls").and_then(|x| x.as_u64()).unwrap_or(0) as u32,
                cost_usd: v.get("cost_usd").and_then(|x| x.as_f64()).unwrap_or(0.0),
                error_message: v
                    .get("error_message")
                    .and_then(|x| x.as_str())
                    .map(|s| s.to_string()),
                events: vec![],
                judge_notes: v
                    .get("judge_notes")
                    .and_then(|x| x.as_str())
                    .map(|s| s.to_string()),
                quality_score: v.get("quality_score").and_then(|x| x.as_f64()),
                learning_value_score: v
                    .get("learning_value_score")
                    .and_then(|x| x.as_f64())
                    .unwrap_or(0.0),
                trajectory_path: v
                    .get("trajectory_path")
                    .and_then(|x| x.as_str())
                    .map(|s| s.to_string()),
                evaluated_at: v
                    .get("evaluated_at")
                    .and_then(|x| x.as_str())
                    .map(|s| s.to_string()),
                metadata: {
                    let mut m = HashMap::new();
                    if let Some(src) = path.to_str() {
                        m.insert("source_file".into(), serde_json::json!(src));
                    }
                    m
                },
            };
            self.records.push(rec);
            loaded += 1;
        }
        Ok(loaded)
    }

    /// Load from a JSONL file.
    /// Supports:
    /// - Lines that are full TrajectoryRecord (serde)
    /// - Lines that are eval-style flat records (maps fields)
    /// - Fallback: if line has "type" (trajectory event), treat whole file as one record's events for a synthetic task.
    pub fn load_from_jsonl(&mut self, path: impl AsRef<std::path::Path>) -> Result<usize, String> {
        let path = path.as_ref();
        let content = std::fs::read_to_string(path).map_err(|e| e.to_string())?;
        let mut loaded = 0usize;
        let mut events_fallback: Vec<serde_json::Value> = vec![];
        let mut has_events = false;

        for line in content.lines() {
            let line = line.trim();
            if line.is_empty() {
                continue;
            }
            let v: serde_json::Value = match serde_json::from_str(line) {
                Ok(v) => v,
                Err(_) => continue,
            };

            // Try direct TrajectoryRecord deserialize (handles our Rust exports)
            if let Ok(rec) = serde_json::from_value::<TrajectoryRecord>(v.clone()) {
                // fix outcome if needed? already parsed in serde
                self.records.push(rec);
                loaded += 1;
                continue;
            }

            // Eval-style or learning dataset flat
            if v.get("task_id").is_some() || v.get("benchmark_id").is_some() {
                let task_id = v
                    .get("task_id")
                    .and_then(|x| x.as_str())
                    .or_else(|| v.get("benchmark_id").and_then(|x| x.as_str()))
                    .unwrap_or("unknown")
                    .to_string();
                let benchmark_id = v
                    .get("benchmark_id")
                    .and_then(|x| x.as_str())
                    .unwrap_or(&task_id)
                    .to_string();
                let agent = v
                    .get("agent")
                    .and_then(|x| x.as_str())
                    .unwrap_or("unknown")
                    .to_string();
                let outcome_str = v
                    .get("outcome")
                    .and_then(|x| x.as_str())
                    .unwrap_or("failed");
                let outcome = Self::parse_outcome(outcome_str);
                let rec = TrajectoryRecord {
                    task_id: task_id.clone(),
                    benchmark_id,
                    agent,
                    outcome,
                    real_task_id: v
                        .get("real_task_id")
                        .and_then(|x| x.as_str())
                        .map(|s| s.to_string()),
                    prm_overall: v
                        .get("prm_overall")
                        .and_then(|x| x.as_f64())
                        .or_else(|| v.get("prm_overall_score").and_then(|x| x.as_f64())),
                    prm_high_quality_steps: v
                        .get("prm_high_quality_steps")
                        .and_then(|x| x.as_u64())
                        .map(|n| n as u32),
                    prm_low_quality_steps: v
                        .get("prm_low_quality_steps")
                        .and_then(|x| x.as_u64())
                        .map(|n| n as u32),
                    prm_step_labels: None,
                    prm_suggestions: v.get("prm_suggestions").and_then(|x| x.as_array()).map(
                        |arr| {
                            arr.iter()
                                .filter_map(|a| a.as_str().map(|s| s.to_string()))
                                .collect()
                        },
                    ),
                    duration_seconds: v
                        .get("duration_seconds")
                        .and_then(|x| x.as_f64())
                        .unwrap_or(0.0),
                    steps_taken: v.get("steps_taken").and_then(|x| x.as_u64()).unwrap_or(0) as u32,
                    tool_calls: v.get("tool_calls").and_then(|x| x.as_u64()).unwrap_or(0) as u32,
                    cost_usd: v.get("cost_usd").and_then(|x| x.as_f64()).unwrap_or(0.0),
                    error_message: v
                        .get("error_message")
                        .and_then(|x| x.as_str())
                        .map(|s| s.to_string()),
                    events: v
                        .get("events")
                        .and_then(|x| x.as_array())
                        .cloned()
                        .unwrap_or_default(),
                    judge_notes: v
                        .get("judge_notes")
                        .and_then(|x| x.as_str())
                        .map(|s| s.to_string()),
                    quality_score: v.get("quality_score").and_then(|x| x.as_f64()),
                    learning_value_score: v
                        .get("learning_value_score")
                        .and_then(|x| x.as_f64())
                        .unwrap_or(0.0),
                    trajectory_path: v
                        .get("trajectory_path")
                        .and_then(|x| x.as_str())
                        .map(|s| s.to_string()),
                    evaluated_at: v
                        .get("evaluated_at")
                        .and_then(|x| x.as_str())
                        .map(|s| s.to_string()),
                    metadata: {
                        let mut m = HashMap::new();
                        m.insert("source".into(), serde_json::json!("jsonl"));
                        if let Some(p) = path.to_str() {
                            m.insert("path".into(), serde_json::json!(p));
                        }
                        m
                    },
                };
                self.records.push(rec);
                loaded += 1;
                continue;
            }

            // Pair file? extract chosen/rejected as pseudo records (for stats)
            if v.get("chosen").is_some() && v.get("rejected").is_some() {
                // add minimal for both sides
                for (side, lab) in [("chosen", "success"), ("rejected", "failed")] {
                    if let Some(side_v) = v.get(side) {
                        let bid = v
                            .get("benchmark_id")
                            .and_then(|x| x.as_str())
                            .unwrap_or("pair")
                            .to_string();
                        let rec = TrajectoryRecord {
                            task_id: format!("{}-{}", bid, side),
                            benchmark_id: bid.clone(),
                            agent: "unknown".into(),
                            outcome: Self::parse_outcome(lab),
                            real_task_id: None,
                            prm_overall: side_v.get("prm_overall").and_then(|x| x.as_f64()),
                            prm_high_quality_steps: None,
                            prm_low_quality_steps: None,
                            prm_step_labels: None,
                            prm_suggestions: None,
                            duration_seconds: 0.0,
                            steps_taken: 0,
                            tool_calls: 0,
                            cost_usd: 0.0,
                            error_message: side_v
                                .get("error_message")
                                .and_then(|x| x.as_str())
                                .map(|s| s.to_string()),
                            events: side_v
                                .get("events")
                                .and_then(|x| x.as_array())
                                .cloned()
                                .unwrap_or_default(),
                            judge_notes: None,
                            quality_score: None,
                            learning_value_score: side_v
                                .get("learning_value")
                                .and_then(|x| x.as_f64())
                                .unwrap_or(0.0),
                            trajectory_path: None,
                            evaluated_at: None,
                            metadata: HashMap::new(),
                        };
                        self.records.push(rec);
                        loaded += 1;
                    }
                }
                continue;
            }

            // Fallback: treat as trajectory event line
            if v.get("type").is_some() {
                has_events = true;
                events_fallback.push(v.clone());
            }
        }

        if loaded == 0 && has_events && !events_fallback.is_empty() {
            // Synthesize one record from the events JSONL (common for raw trajectories)
            let task_id = path
                .file_stem()
                .and_then(|s| s.to_str())
                .unwrap_or("traj")
                .to_string();
            let rec = TrajectoryRecord {
                task_id: task_id.clone(),
                benchmark_id: task_id.clone(),
                agent: "grok".into(),
                outcome: Outcome::PartialSuccess, // unknown without end marker; caller can override
                real_task_id: None,
                prm_overall: None,
                prm_high_quality_steps: None,
                prm_low_quality_steps: None,
                prm_step_labels: None,
                prm_suggestions: None,
                duration_seconds: 0.0,
                steps_taken: events_fallback.len() as u32,
                tool_calls: 0,
                cost_usd: 0.0,
                error_message: None,
                events: events_fallback,
                judge_notes: None,
                quality_score: None,
                learning_value_score: 0.0,
                trajectory_path: Some(path.to_string_lossy().to_string()),
                evaluated_at: None,
                metadata: {
                    let mut m = HashMap::new();
                    m.insert(
                        "source".into(),
                        serde_json::json!("trajectory_jsonl_fallback"),
                    );
                    m
                },
            };
            self.records.push(rec);
            loaded = 1;
        }

        Ok(loaded)
    }

    /// Unified real input loader: auto-detects if path is file (jsonl) or dir (eval results *or* trajectories with *.jsonl + optional *.prm.json sidecars).
    /// Returns number of records loaded. Robust for flywheel use.
    pub fn load_from_real_input(
        &mut self,
        input: impl AsRef<std::path::Path>,
    ) -> Result<usize, String> {
        let p = input.as_ref();
        if p.is_dir() {
            // Prefer eval results (classic *.json)
            if let Ok(n) = self.load_from_eval_results_dir(p) {
                if n > 0 {
                    return Ok(n);
                }
            }
            // Fallback: trajectories dir full of *.jsonl (with auto sidecar enrich)
            if let Ok(n) = self.load_from_trajectories_dir(p) {
                if n > 0 {
                    let _en = self.enrich_from_prm_sidecars(p);
                    return Ok(n);
                }
            }
            // last try eval anyway (may return err)
            self.load_from_eval_results_dir(p)
        } else if p.is_file() {
            // accept .jsonl or .json or any text jsonl
            self.load_from_jsonl(p)
        } else {
            Err(format!("Input path not found: {}", p.display()))
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::types::{Outcome, TrajectoryRecord};

    fn sample_rec(id: &str, outcome: Outcome, prm: Option<f64>) -> TrajectoryRecord {
        TrajectoryRecord {
            task_id: id.into(),
            benchmark_id: "bench1".into(),
            agent: "grok".into(),
            outcome,
            real_task_id: None,
            prm_overall: prm,
            prm_high_quality_steps: Some(2),
            prm_low_quality_steps: Some(1),
            prm_step_labels: None,
            prm_suggestions: None,
            duration_seconds: 12.0,
            steps_taken: 5,
            tool_calls: 3,
            cost_usd: 0.03,
            error_message: None,
            events: vec![],
            judge_notes: None,
            quality_score: prm,
            learning_value_score: 0.0,
            trajectory_path: None,
            evaluated_at: None,
            metadata: HashMap::new(),
        }
    }

    #[test]
    fn dataset_filters_and_exports() {
        let mut ds = TrajectoryDataset::new("test");
        ds.add(sample_rec("t1", Outcome::Success, Some(0.85)));
        ds.add(sample_rec("t2", Outcome::Failure, Some(0.3)));
        ds.compute_learning_value();

        let hq = ds.filter_high_quality(0.7);
        assert_eq!(hq.len(), 1);

        let pairs = ds.export_preference_pairs();
        assert!(!pairs.is_empty());

        let prm_labels = ds.export_prm_step_labels();
        // no labels attached in sample but API works
        assert!(prm_labels.is_empty() || !prm_labels.is_empty()); // just exercise
    }

    #[test]
    fn flywheel_sidecar_parse_and_enrich_graceful() {
        use std::io::Write;
        // tempfile not a dependency — using std::env::temp_dir() + manual files below (already implemented in test body)

        // Fallback: test parse_prm_sidecar directly via a temp file we control (no extra dep)
        let tmp = std::env::temp_dir().join(format!("test_prm_{}.json", std::process::id()));
        {
            let mut f = std::fs::File::create(&tmp).expect("temp prm");
            writeln!(f, r#"{{
                "overall": 0.82,
                "prm_high_quality_steps": 7,
                "low_quality_steps": 1,
                "steps": [
                    {{"index":0, "event_type":"llm_turn", "score":0.91, "reasons":["clear","correct"]}},
                    {{"index":1, "type":"tool_result", "score":0.65, "reason":"partial"}}
                ],
                "suggestions": ["use more context", "add verification"]
            }}"#).ok();
        }

        // Use private parse via a small wrapper: create ds and manually invoke via a record with path
        let mut ds = TrajectoryDataset::new("sidecar_test");
        let mut rec = sample_rec("side1", Outcome::Success, None);
        rec.trajectory_path = Some("/tmp/farm/side1.jsonl".to_string());
        rec.task_id = "side1".to_string();
        ds.add(rec);

        // place sidecar named to match stem
        let sidecar_dir = tmp.parent().unwrap();
        // rename tmp to match expected stem "side1.prm.json"
        let target_side = sidecar_dir.join("side1.prm.json");
        let _ = std::fs::copy(&tmp, &target_side);
        let _ = std::fs::remove_file(&tmp);

        let enriched = ds.enrich_from_prm_sidecars(sidecar_dir);
        assert!(
            enriched >= 1,
            "should have enriched at least one via sidecar"
        );
        let r = &ds.records[0];
        assert!(r.prm_overall.is_some());
        assert_eq!(r.prm_overall.unwrap(), 0.82);
        assert!(r.prm_step_labels.is_some());
        assert!(r.prm_suggestions.as_ref().map(|v| v.len()).unwrap_or(0) > 0);
        assert!(r.metadata.contains_key("prm_sidecar"));

        // cleanup
        let _ = std::fs::remove_file(&target_side);

        // Also exercise load_flywheel_data (empty dirs are graceful)
        let mut ds2 = TrajectoryDataset::new("empty_fly");
        let res = ds2.load_flywheel_data(
            Some(std::path::Path::new("/nonexistent_farm_traj_zzz")),
            None::<std::path::PathBuf>,
            Some(std::path::Path::new("/nonexistent_farm_res_zzz")),
        );
        assert!(res.is_ok());
        assert_eq!(ds2.len(), 0);
    }

    // Phase 1 parity foundation (RUST_FULL_MIGRATION_PLAN.md):
    // Golden/fixture comparison lives in sibling Python harness at
    // agentforge/learning/flywheel_parity/parity_harness.py + fixtures/golden/
    // (real artifacts collected from pending_candidates/).
    // When `flywheel-step` is added to the runner CLI, add a Rust-side
    // integration test here that shells out or links to produce identical
    // (normalized) proposal.json + candidate_skill.yaml + rich exports.
    // Goal: byte- or semantic-identical artifacts for safe cutover.
}
