"""
!!! AGGRESSIVE FINAL DEPRECATION + PHASE 4 CLEANUP PREP (RUST_FULL_MIGRATION_PLAN.md) !!!
Flywheel Parity Test Harness (Python side for Phase 1+ migration).

DEPRECATED / MIGRATION-ONLY: Python flywheel orchestration support.
Entire learning/flywheel_parity/ (including this __init__) is scheduled for
removal in Phase 4 once Rust flywheel is the sole engine + all golden parities
validated in CI / soak.

See RUST_FULL_MIGRATION_PLAN.md for context:
- Foundation for artifact parity between Python flywheel step and future
  pure-Rust `agentforge-runner flywheel-step`.
- Golden fixtures + semantic comparison (ignoring volatile fields like timestamps,
  content hashes in candidate ids, absolute paths, generated_at).
- Focus artifacts: proposal.json, candidate_skill.yaml (incl. _learning_meta),
  flywheel_manifest.json, candidate_meta.json, rust_rich_flywheel_export.json
  (rich stats, per-record learning_values, prm_step_labels etc).

This enables safe cutover: run both impls on identical inputs, assert structural
+ semantic equivalence within tolerances on numeric fields.

Turbo practical start — skeleton ready for extension when Rust flywheel-step lands.
Now in aggressive final deprecation sweep: see PHASE4_REMOVAL_PLAN.md (skeleton created this sweep; removal order, risks, rollback) + learning/utils.py (even stronger is_pure_rust_flywheel guards).
Python flywheel parity side is Phase 4 deletion target.
"""

from .parity_harness import (
    ARTIFACTS,
    load_golden,
    normalize_artifact,
    compare_artifacts,
    run_parity_check,
    FlywheelParityHarness,
)

__all__ = [
    "ARTIFACTS",
    "load_golden",
    "normalize_artifact",
    "compare_artifacts",
    "run_parity_check",
    "FlywheelParityHarness",
]

# Phase 2 shadow (FURTHER ENRICHED v4 + farm usability maxed) — re-exported
# from agentforge.learning.flywheel_parity import FlywheelParityHarness
# h = FlywheelParityHarness()
# fid = h.run_live_shadow_comparison(limit=20)  # writes full v4 JSON (pass/score + numeric_deltas + bigram + title_diffs + smart metrics)
# OR easiest: fid = h.run_shadow_compare_latest()   # auto smart rust/py pair from /tmp
# CLI one-liner (farm/CI/watchdog): python -m agentforge.learning.flywheel_parity.parity_harness --shadow-compare-latest --json
# Produces v4 shadow_fidelity_*.json + _latest + _aggregate (with fidelity_pass etc) under /tmp/agentforge_rust_flywheel/
