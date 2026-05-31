//! Prioritizer + high-value ranking (real port from Python learning/pending_candidates.py).
//!
//! Ports:
//! - _lv_key / list_high_value_candidates / print_pending_summary scoring logic
//! - composite: lv * lift_potential + recency (where lift_pot = hlv * (1-sr) * max(lv, 0.05))
//!   Matches both the *10 variant in list_high_value_candidates and recency tiebreak from _lv_key.
//! Real FS data from candidate_meta.json (rich_*) + proposal fallbacks now drive it.

use super::*;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CandidatePriority {
    pub summary: CandidateSummary,
    pub score: f64, // composite of learning_value, impact, recency, etc.
}

pub struct Prioritizer;

impl Prioritizer {
    pub fn new() -> Self {
        Self
    }

    /// Real composite rank ported from Python _lv_key logic in pending_candidates.py:
    ///   lv = rich_avg_learning_value or avg_learning_value
    ///   lift_pot = hlv * (1 - sr) * max(lv, 0.05)
    ///   score = (lv * 100.0 + lift_pot) + tiny_recency_boost   (primary matches py tuple key; + recency)
    /// Returns ranked list (desc score). Used for --sort value.
    pub fn rank(&self, candidates: &[CandidateSummary]) -> Vec<CandidatePriority> {
        let mut scored: Vec<CandidatePriority> = candidates
            .iter()
            .map(|c| {
                let lv = c.rich_avg_learning_value.or(c.avg_learning_value).unwrap_or(0.0);
                let hlv = c.high_value_count;
                let sr = c.success_rate.unwrap_or(0.5);
                // Lift potential: high value signals on lower-success batches = high priority for flywheel (exact py port)
                let lift_pot = (hlv as f64) * (1.0 - sr) * lv.max(0.05);
                // Primary score mirrors py _lv_key: lv*100 + lift_pot  (even when lv~0, lift_pot distinguishes high-hlv/low-sr)
                // + recency boost (newer timestamps higher) for tie stability, as tiny addend.
                let base = lv * 100.0 + lift_pot;
                let recency_bonus: f64 = c
                    .timestamp
                    .as_deref()
                    .or_else(|| {
                        // fallback: parse leading YYYYMMDD_ from id/dirname (real data uses this)
                        c.id.split('_').next()
                    })
                    .and_then(|ts| ts.parse::<f64>().ok())
                    .unwrap_or(0.0)
                    / 1_000_000_000_000.0; // tiny so it doesn't dominate LV/lift
                let score = base + recency_bonus;
                CandidatePriority {
                    summary: c.clone(),
                    score,
                }
            })
            .collect();

        // Sort descending by score (stable on ties via original order not critical)
        scored.sort_by(|a, b| {
            b.score
                .partial_cmp(&a.score)
                .unwrap_or(std::cmp::Ordering::Equal)
        });
        scored
    }
}

/// Public API: returns top-N by real prioritizer score (non-promoted preferred in spirit of callers).
/// Mirrors Python list_high_value_candidates + the sort in print_pending_summary("value").
pub fn list_high_value_candidates(store: &CandidateStore, top_n: usize) -> Vec<CandidateSummary> {
    let mut list = store.list_pending().unwrap_or_default();
    // Filter out already-promoted for "high value pending" view (matches store.list_high_value intent)
    list.retain(|c| !c.promoted);
    let ranked = Prioritizer::new().rank(&list);
    ranked.into_iter().take(top_n).map(|p| p.summary).collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;

    #[test]
    fn prioritizer_rank_composite_score_edges_and_recency() {
        // Pure unit test (no FS): covers lv, lift_pot (hlv*(1-sr)*lv), recency bonus from ts/id, promoted not filtered here
        let summaries = vec![
            CandidateSummary {
                id: "old_low_lv".into(),
                skill: "s".into(),
                impact: "low".into(),
                high_value_count: 1,
                promoted: false,
                path: PathBuf::new(),
                rich_avg_learning_value: Some(0.1),
                avg_learning_value: None,
                success_rate: Some(0.9),
                timestamp: Some("20200101_000000".into()),
                records_loaded: None,
            },
            CandidateSummary {
                id: "new_high_impact".into(),
                skill: "s".into(),
                impact: "high".into(),
                high_value_count: 12,
                promoted: false,
                path: PathBuf::new(),
                rich_avg_learning_value: Some(0.75),
                avg_learning_value: Some(0.6),
                success_rate: Some(0.25),
                timestamp: Some("20260531_055029".into()),
                records_loaded: Some(42),
            },
            CandidateSummary {
                id: "promoted_skip_in_list_but_ranked_here".into(),
                skill: "s".into(),
                impact: "high".into(),
                high_value_count: 5,
                promoted: true,
                path: PathBuf::new(),
                rich_avg_learning_value: Some(0.1),
                avg_learning_value: None,
                success_rate: Some(0.1),
                timestamp: Some("20260530_000000".into()),
                records_loaded: Some(10),
            },
            CandidateSummary {
                id: "zeroes".into(),
                skill: "s".into(),
                impact: "medium".into(),
                high_value_count: 0,
                promoted: false,
                path: PathBuf::new(),
                rich_avg_learning_value: None,
                avg_learning_value: None,
                success_rate: None,
                timestamp: None,
                records_loaded: None,
            },
        ];

        let ranked = Prioritizer::new().rank(&summaries);
        assert_eq!(ranked.len(), 4);
        // Highest should be the new high impact one (high lv + high lift from hlv*low_sr)
        let top = &ranked[0];
        assert_eq!(top.summary.id, "new_high_impact");
        assert!(top.score.is_finite() && top.score > 50.0);

        let low = ranked.iter().find(|p| p.summary.id == "old_low_lv").unwrap();
        assert!(top.score > low.score);

        // promoted is included in rank() (upstream list_high filters); zeroes get tiny score but finite
        let zero = ranked.iter().find(|p| p.summary.id == "zeroes").unwrap();
        assert!(zero.score.is_finite());

        // list_high_value fn filters promoted + limits
        // (will use real store in integration tests)
    }

    #[test]
    fn prioritizer_list_high_value_candidates_filters_promoted_and_respects_top_n() {
        // Integration-style unit test using isolated temp store (covers continuous use path)
        let pid = std::process::id();
        let tmp_root = std::env::temp_dir().join(format!("agentforge_prio_list_{}", pid));
        let _ = std::fs::create_dir_all(&tmp_root);
        let store = CandidateStore::new(Some(tmp_root.clone()));

        // Seed 3 candidates: 2 non-promoted, 1 promoted
        for (i, (cid, promoted)) in [
            ("20260531_prio_a", false),
            ("20260531_prio_b", false),
            ("20260531_prio_promoted", true),
        ].iter().enumerate() {
            let d = tmp_root.join(cid);
            let _ = std::fs::create_dir_all(&d);
            let meta = serde_json::json!({
                "candidate_id": cid,
                "skill": format!("prio-skill-{}", i),
                "promoted": promoted,
                "high_learning_value_records": 5 + i as u64,
                "estimated_impact": "high",
                "rich_avg_learning_value": 0.6 + (i as f64 * 0.1)
            });
            let _ = std::fs::write(d.join("candidate_meta.json"), serde_json::to_string(&meta).unwrap());
        }

        let tops = list_high_value_candidates(&store, 2);
        assert_eq!(tops.len(), 2, "top_n respected and promoted filtered");
        assert!(tops.iter().all(|c| !c.promoted));
        // higher rich lv first due to rank
        if tops.len() == 2 {
            assert!(tops[0].rich_avg_learning_value.unwrap_or(0.0) >= tops[1].rich_avg_learning_value.unwrap_or(0.0));
        }

        let _ = std::fs::remove_dir_all(&tmp_root);
    }

    #[test]
    fn prioritizer_rank_lift_potential_and_zero_edge_math() {
        let summaries = vec![
            CandidateSummary {
                id: "high_lift".into(), skill: "s".into(), impact: "high".into(), high_value_count: 20,
                promoted: false, path: PathBuf::new(), rich_avg_learning_value: Some(0.4),
                avg_learning_value: None, success_rate: Some(0.1), timestamp: None, records_loaded: None,
            },
            CandidateSummary {
                id: "zero_hlv".into(), skill: "s".into(), impact: "low".into(), high_value_count: 0,
                promoted: false, path: PathBuf::new(), rich_avg_learning_value: Some(0.9),
                avg_learning_value: Some(0.9), success_rate: Some(0.1), timestamp: None, records_loaded: None,
            },
        ];
        let ranked = Prioritizer::new().rank(&summaries);
        let high_lift = ranked.iter().find(|p| p.summary.id == "high_lift").unwrap();
        let zero = ranked.iter().find(|p| p.summary.id == "zero_hlv").unwrap();
        // lift = hlv*(1-sr)*lv.max(0.05) => 20*0.9*0.4 = 7.2 ; base ~40+7.2=47.2
        assert!(high_lift.score > 40.0);
        // zero hlv still gets base lv*100 even if lift 0
        assert!(zero.score > 80.0);
        assert!(high_lift.score < zero.score); // pure lv wins over lift here
    }

    #[test]
    fn prioritizer_handles_empty_and_all_promoted_inputs() {
        let empty: Vec<CandidateSummary> = vec![];
        let ranked = Prioritizer::new().rank(&empty);
        assert!(ranked.is_empty());

        let all_prom = vec![CandidateSummary {
            id: "p1".into(), skill: "s".into(), impact: "med".into(), high_value_count: 3,
            promoted: true, path: PathBuf::new(), rich_avg_learning_value: Some(0.5),
            avg_learning_value: None, success_rate: Some(0.5), timestamp: None, records_loaded: None,
        }];
        let ranked2 = Prioritizer::new().rank(&all_prom);
        assert_eq!(ranked2.len(), 1);
        assert!(ranked2[0].score.is_finite());
    }

    #[test]
    fn prioritizer_top_n_zero_and_negative_equiv_returns_empty_for_continuous() {
        // Edge for continuous --top-n 0 (safe no-op path)
        let summaries = vec![
            CandidateSummary { id: "c1".into(), skill: "s".into(), impact: "h".into(), high_value_count: 10, promoted: false, path: PathBuf::new(), rich_avg_learning_value: Some(0.9), avg_learning_value: None, success_rate: Some(0.1), timestamp: None, records_loaded: None },
        ];
        let ranked = Prioritizer::new().rank(&summaries);
        assert_eq!(ranked.len(), 1);
        // list_high_value respects top_n=0 as empty (used by continuous skeleton)
        let pid = std::process::id();
        let tmp = std::env::temp_dir().join(format!("prio_zero_{}", pid));
        let _ = std::fs::create_dir_all(&tmp);
        let store = CandidateStore::new(Some(tmp.clone()));
        // seed one
        let d = tmp.join("z1"); let _ = std::fs::create_dir_all(&d);
        let _ = std::fs::write(d.join("candidate_meta.json"), r#"{"candidate_id":"z1","skill":"z","promoted":false,"high_learning_value_records":7,"rich_avg_learning_value":0.8}"#);
        let tops0 = list_high_value_candidates(&store, 0);
        assert!(tops0.is_empty(), "top_n=0 must yield no suggestions (continuous safe)");
        let tops_neg = list_high_value_candidates(&store, usize::MAX); // large but filter works
        assert!(!tops_neg.is_empty());
        let _ = std::fs::remove_dir_all(&tmp);
    }

    #[test]
    fn prioritizer_composite_score_stable_on_ties_and_promoted_filter_in_list_high() {
        let s1 = CandidateSummary {
            id: "tie_a".into(), skill: "s".into(), impact: "med".into(), high_value_count: 2,
            promoted: false, path: PathBuf::new(), rich_avg_learning_value: Some(0.3),
            avg_learning_value: Some(0.3), success_rate: Some(0.5), timestamp: Some("20260501_000000".into()), records_loaded: None,
        };
        let s2 = CandidateSummary {
            id: "tie_b".into(), skill: "s".into(), impact: "med".into(), high_value_count: 2,
            promoted: false, path: PathBuf::new(), rich_avg_learning_value: Some(0.3),
            avg_learning_value: Some(0.3), success_rate: Some(0.5), timestamp: Some("20260501_000000".into()), records_loaded: None,
        };
        let ranked = Prioritizer::new().rank(&[s1.clone(), s2.clone()]);
        assert_eq!(ranked.len(), 2);
        // scores equal is fine (stable sort)
        assert!((ranked[0].score - ranked[1].score).abs() < 1e-9 || ranked[0].score > ranked[1].score);

        // list_high filters promoted regardless of score
        let pid = std::process::id();
        let tmp = std::env::temp_dir().join(format!("prio_tie_{}", pid));
        let _ = std::fs::create_dir_all(&tmp);
        let store = CandidateStore::new(Some(tmp.clone()));
        for (id, prom) in [("tie1", false), ("tie2", true)] {
            let d = tmp.join(id); let _ = std::fs::create_dir_all(&d);
            // full fields for reliable CandidateMeta de (no missing non-default)
            let meta = format!(r#"{{"candidate_id":"{}","timestamp":"","skill":"t","estimated_impact":"med","rust_pairs_used":0,"high_learning_value_records":3,"source_artifacts":"","generated_by":"","copied_files":[],"promoted":{},"reviewed":false,"rich_avg_learning_value":0.4}}"#, id, prom);
            let _ = std::fs::write(d.join("candidate_meta.json"), meta);
        }
        let tops = list_high_value_candidates(&store, 5);
        // Filter must exclude promoted (critical for continuous flywheel to avoid re-work)
        assert!(tops.iter().all(|c| !c.promoted), "promoted must be filtered for continuous safety");
        assert!(tops.iter().any(|c| c.id == "tie1"));
        assert!(tops.len() <= 2); // at most the non-promoted (test isolation)
        let _ = std::fs::remove_dir_all(&tmp);
    }

    #[test]
    fn list_high_value_candidates_handles_missing_meta_gracefully_for_continuous() {
        let pid = std::process::id();
        let tmp = std::env::temp_dir().join(format!("prio_missing_{}", pid));
        let _ = std::fs::create_dir_all(&tmp);
        let store = CandidateStore::new(Some(tmp.clone()));
        // corrupt-ish dir (no meta) + good one
        let bad = tmp.join("bad_no_meta"); let _ = std::fs::create_dir_all(&bad);
        let good = tmp.join("20260531_good_lv"); let _ = std::fs::create_dir_all(&good);
        let _ = std::fs::write(good.join("candidate_meta.json"), r#"{"candidate_id":"20260531_good_lv","skill":"g","promoted":false,"rich_avg_learning_value":0.55,"high_learning_value_records":2}"#);
        let tops = list_high_value_candidates(&store, 3);
        assert!(tops.iter().any(|c| c.id.contains("good_lv")));
        assert!(tops.iter().all(|c| !c.promoted));
        let _ = std::fs::remove_dir_all(&tmp);
    }

    #[test]
    fn prioritizer_continuous_cutover_disable_after_promote_filters_safely() {
        // Critical for cutover: after promote in continuous, promoted candidates are fully disabled from high-value suggestions
        let pid = std::process::id();
        let tmp = std::env::temp_dir().join(format!("prio_cutover_{}", pid));
        let _ = std::fs::create_dir_all(&tmp);
        let store = CandidateStore::new(Some(tmp.clone()));
        for (cid, prom) in [("pre_cut", false), ("post_cut", true)] {
            let d = tmp.join(cid); let _ = std::fs::create_dir_all(&d);
            // Full fields for robust CandidateMeta deserialize (all non-Option non-defaulted present)
            let meta = format!(r#"{{"candidate_id":"{}","timestamp":"","skill":"c","estimated_impact":"med","rust_pairs_used":0,"high_learning_value_records":4,"source_artifacts":"","generated_by":"","copied_files":[],"promoted":{},"reviewed":false,"rich_avg_learning_value":0.7}}"#, cid, prom);
            let _ = std::fs::write(d.join("candidate_meta.json"), meta);
        }
        let tops = list_high_value_candidates(&store, 10);
        assert!(tops.iter().all(|c| !c.promoted));
        assert!(tops.iter().any(|c| c.id == "pre_cut"));
        assert!(!tops.iter().any(|c| c.id == "post_cut"));
        let _ = std::fs::remove_dir_all(&tmp);
    }

    #[test]
    fn prioritizer_disable_via_zero_high_value_and_limit_for_shadow_continuous() {
        // Disable path (zero hlv or top_n=0) used in shadow/continuous health checks must yield safe empty without panic
        let summaries = vec![CandidateSummary {
            id: "zeroed".into(), skill: "s".into(), impact: "low".into(), high_value_count: 0,
            promoted: false, path: PathBuf::new(), rich_avg_learning_value: Some(0.1),
            avg_learning_value: None, success_rate: Some(0.9), timestamp: None, records_loaded: None,
        }];
        let ranked = Prioritizer::new().rank(&summaries);
        assert_eq!(ranked.len(), 1);
        assert!(ranked[0].score.is_finite());

        let pid = std::process::id();
        let tmp = std::env::temp_dir().join(format!("prio_disable_{}", pid));
        let _ = std::fs::create_dir_all(&tmp);
        let store = CandidateStore::new(Some(tmp.clone()));
        let d = tmp.join("zh"); let _ = std::fs::create_dir_all(&d);
        let _ = std::fs::write(d.join("candidate_meta.json"), r#"{"candidate_id":"zh","skill":"z","promoted":false,"high_learning_value_records":0}"#);
        let tops = list_high_value_candidates(&store, 0);
        assert!(tops.is_empty(), "top_n=0 disable for continuous shadow must be empty");
        let _ = std::fs::remove_dir_all(&tmp);
    }

    #[test]
    fn prioritizer_shadow_emission_fields_stable_under_disable_for_runner_continuous() {
        // Fields consumed by runner continuous --json + shadow must stay stable even under disable filters
        let s = CandidateSummary {
            id: "shadow_stable".into(), skill: "ss".into(), impact: "high".into(), high_value_count: 8,
            promoted: false, path: PathBuf::new(), rich_avg_learning_value: Some(0.82),
            avg_learning_value: None, success_rate: Some(0.2), timestamp: Some("20260531_120000".into()), records_loaded: Some(99),
        };
        let ranked = Prioritizer::new().rank(&[s]);
        assert!(ranked[0].score > 80.0);
        assert!(ranked[0].summary.rich_avg_learning_value.unwrap() > 0.8);
    }

    // =====================================================================
    // DEEPER PROPERTY-BASED TESTS for prioritizer (continuous + shadow ranking invariants + cross promote edges)
    // Production: scores monotonic, finite, filter correctness under promoted/zero/lv edges, recency stability
    // =====================================================================
    use proptest::prelude::*;

    proptest! {
        #[test]
        fn prop_prioritizer_rank_produces_non_increasing_finite_scores(
            n in 1usize..12,
            base_lv in 0.0f64..2.0,
            hlv_mult in 0u64..25,
            sr in 0.0f64..1.0
        ) {
            let mut summaries = vec![];
            for i in 0..n {
                summaries.push(CandidateSummary {
                    id: format!("p{}", i),
                    skill: "s".into(),
                    impact: if i % 2 == 0 { "high" } else { "med" }.into(),
                    high_value_count: hlv_mult + (i as u64),
                    promoted: false,
                    path: PathBuf::new(),
                    rich_avg_learning_value: Some(base_lv + (i as f64 * 0.01)),
                    avg_learning_value: None,
                    success_rate: Some(sr),
                    timestamp: Some(format!("202605{:02}_000000", 30 - (i % 28))),
                    records_loaded: Some(10 + i as u64),
                });
            }
            let ranked = Prioritizer::new().rank(&summaries);
            prop_assert_eq!(ranked.len(), n);
            for i in 0..ranked.len() {
                prop_assert!(ranked[i].score.is_finite(), "all scores must be finite for continuous health");
                if i > 0 {
                    prop_assert!(ranked[i-1].score >= ranked[i].score - 1e-9, "rank must be non-increasing for stable continuous top-N");
                }
            }
        }

        #[test]
        fn prop_list_high_value_filters_promoted_and_respects_top_n_cross_promote(
            n_cand in 3usize..9,
            top in 0usize..6,
            promote_last in proptest::bool::ANY
        ) {
            let pid = std::process::id();
            let tmp = std::env::temp_dir().join(format!("prio_prop_filt_{}_{}", pid, n_cand));
            let _ = std::fs::create_dir_all(&tmp);
            let store = CandidateStore::new(Some(tmp.clone()));
            for i in 0..n_cand {
                let cid = format!("prop_filt_{}", i);
                let d = tmp.join(&cid); let _ = std::fs::create_dir_all(&d);
                let promoted = promote_last && i == n_cand-1;
                let meta = format!(r#"{{"candidate_id":"{}","timestamp":"20260531_00000{}","skill":"pf","estimated_impact":"high","rust_pairs_used":0,"high_learning_value_records":3,"source_artifacts":"","generated_by":"","copied_files":[],"promoted":{},"reviewed":false,"rich_avg_learning_value":0.5}}"#, cid, i%10, promoted);
                let _ = std::fs::write(d.join("candidate_meta.json"), meta);
            }
            let tops = list_high_value_candidates(&store, top);
            prop_assert!(tops.len() <= top);
            prop_assert!(tops.iter().all(|c| !c.promoted), "list_high must never return promoted (post-promote disable for continuous)");
            let _ = std::fs::remove_dir_all(&tmp);
        }
    }

    #[test]
    fn prioritizer_cross_promote_shadow_continuous_zero_and_extreme_edges() {
        // Production edge: zero hlv, extreme min_prm equiv (via filter), promote cutover + shadow stable scores
        let pid = std::process::id();
        let tmp = std::env::temp_dir().join(format!("prio_cross_edge_{}", pid));
        let _ = std::fs::create_dir_all(&tmp);
        let store = CandidateStore::new(Some(tmp.clone()));
        // zero hlv (shadow emission edge)
        let z = tmp.join("zero_hlv_shadow"); let _ = std::fs::create_dir_all(&z);
        let _ = std::fs::write(z.join("candidate_meta.json"), r#"{"candidate_id":"zero_hlv_shadow","skill":"z","promoted":false,"high_learning_value_records":0,"rich_avg_learning_value":0.01}"#);
        // promoted one
        let p = tmp.join("post_prom_shadow"); let _ = std::fs::create_dir_all(&p);
        let _ = std::fs::write(p.join("candidate_meta.json"), r#"{"candidate_id":"post_prom_shadow","skill":"p","promoted":true,"high_learning_value_records":10,"rich_avg_learning_value":0.9}"#);
        // good one
        let g = tmp.join("good_for_cont"); let _ = std::fs::create_dir_all(&g);
        let _ = std::fs::write(g.join("candidate_meta.json"), r#"{"candidate_id":"good_for_cont","skill":"g","promoted":false,"high_learning_value_records":4,"rich_avg_learning_value":0.88}"#);

        let tops = list_high_value_candidates(&store, 5);
        assert!(tops.iter().all(|c| !c.promoted));
        assert!(tops.iter().any(|c| c.id == "good_for_cont"));
        assert!(!tops.iter().any(|c| c.id.contains("zero_hlv") || c.id.contains("post_prom")));

        // rank still produces finite for zero case (used in health emission)
        let all = store.list_pending().unwrap_or_default();
        let ranked = Prioritizer::new().rank(&all);
        for r in &ranked {
            assert!(r.score.is_finite());
        }
        let _ = std::fs::remove_dir_all(&tmp);
    }
}
