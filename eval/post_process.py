#!/usr/bin/env python3
"""
DEPRECATED / OBSOLETE — PROPOSED FOR REMOVAL (full Rust migration)

eval/post_process.py — PRM + trajectory enrichment + sidecar/mapping (core kept).

STATUS (2026-06-13, SWARM task analysis):
- We have FULLY transitioned to Rust (agentforge-runner, agentforge-flywheel, direct flywheel-step/continuous/candidate via Rust binary).
- Flywheel orchestration triggers (run_rust_*, shadow harness glue) were EXCISED in prior migration waves (see PHASE4_REMOVAL_PLAN, JULES_PY_REMOVAL_HANDOFF_f29c675b, RUST_FULL_MIGRATION_PLAN).
- This file was surgically thinned to "PRM/trajectory/sidecar + direct runner continuous tick" (Tier 2, KEEP FOR VALUE at the time).
- HOWEVER: no longer used in active production paths:
  * grok_worker.sh now only calls rust_flywheel_after_task.sh (direct runner).
  * grok_runner.sh calls this via python -m with --flags (task-id, trajectory, etc) but the __main__ + post_process_task only support bare <task_id> positional (post-surgical minimal version). Result: calls are no-ops (wrong task_id lookup, no PRM, no sidecar, no tick).
  * log_trajectory.sh same flag-based invocation (conditional on AUTO_PRM).
  * Pure Python callers limited to: eval/runner.py (benchmarks), eval/phase1_demo.py, eval/tests/*, and manual `python -m agentforge.eval.post_process <task_id>`.
  * Rust crates (agentforge-flywheel) consume PRM *sidecars* if present (from old runs) but perform their own high-PRM mining heuristics; no dependency on live Python PRM.
- PRM (prm.py + LLM-as-judge via grok CLI) remains Python-only and was valuable for learning signals, but with full switch the canonical surface is agentforge-runner + Rust learning stack. Any future PRM-like scoring belongs in Rust.
- Continuous tick inside (the last glue) is redundant (direct calls + after_task + timers + services already do runner continuous).

PER INSTRUCTION ("Мы полностью перешли на Rust, поэтому если этот код больше не используется, предлагайте его удаление"):
RECOMMENDATION: DELETE THIS FILE.

  git rm eval/post_process.py
  (follow-up waves: clean stale references in eval/runner.py, analyze_trajectories.py, tests, phase1_demo.py, grok_runner.sh, log_trajectory.sh, docs/*, bin/*, learning/*, safety/*, __init__.py reexports if any; update PHASE4 checklist + REMAINING_PYTHON doc)

This stub prevents silent imports/accidental use. Any call now loudly signals deprecation.

All prior central guards (is_pure_rust_flywheel from learning/utils.py) honored.
"""

import sys
from typing import Any, Dict, Optional
from pathlib import Path


def post_process_task(
    task_id: str,
    trajectories_dir: Optional[Path] = None,
    use_llm_judge: Optional[bool] = None,
) -> Dict[str, Any]:
    """DEPRECATED. Returns stub result only. Do not rely on this."""
    print(
        "WARNING: eval/post_process.py is DEPRECATED and proposed for removal after complete Rust migration.",
        file=sys.stderr,
    )
    print(
        "Use agentforge-runner flywheel-step / continuous / candidate ... directly. PRM sidecars optional legacy.",
        file=sys.stderr,
    )
    return {
        "task_id": task_id,
        "deprecated": True,
        "removed": True,
        "prm_overall_score": None,
        "prm_high_quality_steps": 0,
        "prm_low_quality_steps": 0,
        "events_count": 0,
        "rust_continuous_ticked": False,
        "mapping_updated": False,
        "note": "This module scheduled for git rm per PHASE4 + SWARM analysis 2026-06-13",
    }


if __name__ == "__main__":
    print(
        "eval/post_process.py: DEPRECATED — full transition to Rust complete. Propose removal of this file.",
        file=sys.stderr,
    )
    if len(sys.argv) >= 2:
        print(f"(would have processed: {sys.argv[1]})", file=sys.stderr)
    sys.exit(2)
