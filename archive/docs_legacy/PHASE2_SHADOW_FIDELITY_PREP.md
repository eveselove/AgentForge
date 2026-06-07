# PHASE2_SHADOW_FIDELITY_PREP.md — Phase 2 Shadow v5 NEAR FARM-READY (richer metrics + continuous dual support + max farm usability)

**Status (2026-05-31 FULL AUTONOMOUS MAXIMUM MODE push complete)**: Phase 2 shadow pushed to near-completion for farm readiness. v5+ fidelity richer ( + new_system_prompt_bigram_jaccard + overall_semantic_fidelity + prompt/content/perf/grade/severity/streaks + all prior). Continuous dual support in post_process + after_task.sh (pure/legacy) + phase2_3_integration (run_rust_flywheel* + _maybe_emit helper) + runner. Easy CLI/farm examples + updated docs/examples everywhere. Full hook integration. Usable on real farm data (soak, gates, alerts). 

**End state: PHASE 2 SHADOW NEAR FARM-READY**. (Autonomous max: richer + continuous dual + examples + docs delivered directly.)

## Core Idea (from RUST_FULL_MIGRATION_PLAN.md Phase 2)
Run trusted Python paths + Rust shadow (via `agentforge-runner continuous` / flywheel-step) on configurable sample of farm ticks.
Capture rich fidelity diffs + metrics **before** any Rust-only promote or timer cutover.

## Mechanisms (v5+ NEAR FARM-READY, full autonomous push)
- **Continuous dual support** (post_process primary + after_task hooks (bin/rust_flywheel_after_task.sh wires --shadow to step+continuous) + phase2_3_integration (new _maybe_emit_shadow_dual_fidelity + calls in run_* + pure path) + runner --shadow flag/env): on AGENTFORGE_RUST_FLYWHEEL_SHADOW=1, real farm ticks run BOTH Rust shadow + Py trusted on identical data. Full v5+ fidelity (incl. new bigram+semantic) + _latest + rich aggregate emitted. Py always drives; shadow for validation only.
- **Richer fidelity JSON v5+** (central in parity_harness.compute_rich_shadow_fidelity, used by all):
  - Core + v5: new_system_prompt_jaccard, proposals_content_avg_jaccard, perf_fidelity_ok, fidelity_grade, divergence_severity, critical_divergence, time_delta.
  - **Added in push**: new_system_prompt_bigram_jaccard (semantic depth on prompt), overall_semantic_fidelity (avg of rationale/prompt/proposal content bigram-jaccs).
  - All prior: numeric_field_deltas, rationale_bigram_jaccard, artifacts_key_overlap_pct, rationale_char_len_delta, proposals_title_* diffs, detailed_diffs, manifest/stats, pass/score gates, smart pairing.
  - fidelity_version="phase2-rich-v5-near-farm-ready".
- **Richer aggregate for farm health**: median/p95, pass_rate, recent_pass_streak, trend (improving/degrading/stable), recent_3_avg (from harness + post_process enhanced).
- **Easiest CLI + farm examples** (copy-paste, --json for scripts):
  - `python -m agentforge.learning.flywheel_parity.parity_harness --shadow-compare-latest --json | jq '.fidelity_pass,.composite_fidelity_score,.fidelity_grade,.overall_semantic_fidelity,.new_system_prompt_bigram_jaccard,.recent_pass_streak'`
  - `python -m ... --shadow-aggregate --json` (zero-cost continuous gate from priors)
  - Live: `... shadow --limit 15 --json`
  - Via hooks: export AGENTFORGE_RUST_FLYWHEEL_SHADOW=1 ; bash bin/rust_flywheel_after_task.sh <task> ; python -m ... --shadow-compare-latest --json
  - From phase2_3 or post_process (auto when env): same.
- Full reusables: compute..., run_live..., run_shadow_fidelity_from_dirs, find_recent..., run_shadow_compare_latest etc importable for custom farm agents.
- **Metrics targets** (v5):
  - fidelity_pass + grade=excellent/good; composite>0.85; streak>=3 healthy for real farm soak.
- **Safety / Observability**: unchanged + v5 grade/severity in logs/JSONs for easy alerting. fidelity_version evolves.

## Example Usage for Farm Testing (copy-paste ready — v5 MAX EASE + CONTINUOUS DUAL)
```bash
# 1. Enable continuous dual shadow (env)
export AGENTFORGE_RUST_FLYWHEEL_SHADOW=1

# 2. Real work (post_process / after_task pure / workers) auto-emits v5 richer fidelity (grade/severity + prompt/content sim + perf + aggregate streak/trend refresh on ticks)

# 3. EASIEST one-liner farm gate/CI/canary (v5)
python -m agentforge.learning.flywheel_parity.parity_harness --shadow-compare-latest --json | jq '{pass: .fidelity_pass, score: .composite_fidelity_score, grade: .fidelity_grade, severity: .divergence_severity, prompt_jacc: .new_system_prompt_jaccard, content_jacc: .proposals_content_avg_jaccard}'

# 4. Zero-cost continuous health (cron/watchdog — v5 richer)
python -m agentforge.learning.flywheel_parity.parity_harness --shadow-aggregate --json | jq '.aggregate | {avg: .avg_composite, median: .median_composite, streak: .recent_pass_streak, trend: .trend, p95: .p95_composite}'

# 5. Live fresh dual on real farm data (canary)
python -m agentforge.learning.flywheel_parity.parity_harness shadow --limit 30 --json

# 6. Cron for continuous dual farm soak health (add to crontab)
# */5 * * * * cd /home/eveselove/agentforge && PYTHONPATH=. python -m agentforge.learning.flywheel_parity.parity_harness --shadow-aggregate --json | jq -r '.aggregate | "FARM_FIDELITY avg=\(.avg_composite) streak=\(.recent_pass_streak) trend=\(.trend)"' >> logs/farm_fidelity_health.log

# 7. Script inspect
cat /tmp/agentforge_rust_flywheel/shadow_fidelity_latest.json | python -c '
import sys, json
d = json.load(sys.stdin)
print("PASS:", d.get("fidelity_pass"), "GRADE:", d.get("fidelity_grade"), "SEVERITY:", d.get("divergence_severity"))
'
```

**All paths (incl. after_task pure shadow) produce _latest + _aggregate with v5 richer fields. Use `--json` + jq for instant farm gates/CI/continuous monitoring on real data.**

## Files touched for this v5+ PUSH (near farm-ready, richer + continuous dual, no new files)
- learning/flywheel_parity/parity_harness.py (added prompt_bigram_jacc + overall_semantic_fidelity to v5 compute; docstring/CLI/parser enriched; aggregate logic)
- eval/post_process.py (v5+ comments, print with new fields, enhanced aggregate with harness+inline streak/trend/p95 for richer farm health)
- phase2_3_integration.py (added _maybe_emit_shadow_dual_fidelity helper + wiring into run_rust_flywheel_step + if_enabled pure/legacy paths for continuous dual from hooks/cron)
- PHASE2_SHADOW_FIDELITY_PREP.md (full v5+ overhaul + new metrics/examples), MIGRATION_PROGRESS.md (Phase 2 bumped), USAGE_RUST_IN_FARM.md, RUST_FULL_MIGRATION_PLAN.md, examples/* (refreshed for v5+)
- bin/rust_flywheel_after_task.sh (v5+ comments; shadow wiring already complete for step+continuous)
- (All existing hooks integrated; Rust --shadow pre-existing; edits only)

## Cross-refs
- RUST_FULL_MIGRATION_PLAN.md (Phase 2 — pushed near)
- CONTINUOUS_FLYWHEEL.md + USAGE_RUST_IN_FARM.md
- learning/flywheel_parity/parity_harness.py + PARITY_REPORT_PHASE1.md
- MIGRATION_PROGRESS.md (Phase 2 92% near farm-ready + bullets)
- FARM_ROLLOUT_CHECKLIST.md (shadow v5 for safe validation)
- eval/post_process.py + bin/rust_flywheel_after_task.sh (continuous dual hooks)

**PHASE 2 SHADOW NEAR FARM-READY** (v5+: richer fidelity (prompt_bigram + overall_semantic + grade/perf + streaks) + continuous dual support wired into post_process + after_task + phase2_3 hooks + runner + ultra-easy CLI/farm examples + all docs/examples updated. Truly usable on real farm data. Full autonomous max push complete.)

(FULL AUTONOMOUS MAXIMUM MODE — decided & executed directly + efficiently.)