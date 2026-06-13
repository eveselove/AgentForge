#!/usr/bin/env python3
"""
DEPRECATED — Full Rust Migration (2026-05-31)
This post_process + flywheel trigger logic is legacy.
Prefer direct calls to:
  agentforge-runner flywheel-step --real-data --ingest --shadow

See RUST_ONLY_MIGRATION_PLAN.md
Non-PRM parts of trajectory processing may stay longer.
"""

"""
eval/post_process.py — Minimal Phase 1 post-processing hook + flywheel trigger (Legacy).

!!! AGGRESSIVE FINAL DEPRECATION SWEEP (RUST_FULL_MIGRATION_PLAN.md + PHASE4_REMOVAL_PLAN.md) !!!
!!! FLYWHEEL ORCHESTRATION / TRIGGER GLUE DEPRECATED — PHASE 4 REMOVAL TARGET !!!
The Python flywheel trigger logic (calls into rust_flywheel_step/phase2_3) is deprecated.
USE DIRECT: agentforge-runner flywheel-step --real-data --output-dir DIR --ingest

Guard with hardened central ONLY:
  from agentforge.learning.utils import is_pure_rust_flywheel, is_rust_flywheel_disabled

Core PRM/trajectory post_process stays valuable (non-flywheel parts).
Python flywheel path only for !pure (non-breaking).

See learning/utils.py (Phase 4 strengthened guards)
See PHASE4_REMOVAL_PLAN.md

Minimal Phase 1 post-processing hook.

After a real task completes (via runner or grok_runner), call this (or import the function)
with a task_id to:
- Locate the trajectory (using robust loader)
- Compute PRM
- Enrich and persist (update mapping + optionally write a sidecar result)

This is the "automatic after-task" glue for observability + learning data.
"""

from pathlib import Path
from typing import Optional, Dict, Any
import json
import subprocess

from .trajectory import load_trajectory, find_trajectory_file
from .prm import ProcessRewardModel
import os
import warnings

# PHASE 3/4: ONLY hardened central guards (is_pure + is_disabled). No local logic.
try:
    from agentforge.learning.utils import (
        is_pure_rust_flywheel,
        is_rust_flywheel_disabled,
        get_rust_runner_path,
    )
except Exception:
    try:
        from learning.utils import (
            is_pure_rust_flywheel,
            is_rust_flywheel_disabled,
            get_rust_runner_path,
        )  # safe fallback
    except Exception:
        from learning.utils import is_pure_rust_flywheel, is_rust_flywheel_disabled  # safe fallback
        get_rust_runner_path = None  # type: ignore



def post_process_task(task_id: str, trajectories_dir: Optional[Path] = None, use_llm_judge: Optional[bool] = None) -> Dict[str, Any]:
    """
    Main entry point for post-run enrichment.

    Returns a dict with trajectory_path, prm_result, and any persisted info.
    use_llm_judge: if True (or via AGENTFORGE_PRM_USE_LLM_JUDGE=1) activates real LLM judge inside PRM.
    """
    if use_llm_judge is None:
        envv = os.getenv("AGENTFORGE_PRM_USE_LLM_JUDGE", os.getenv("AGENTFORGE_PRM_LLM_JUDGE", "0"))
        use_llm_judge = str(envv).lower() in ("1", "true", "yes", "on")

    # Force PRM recompute with judge flag via direct construction + score (bypass cached loader path for flag)
    raw_traj = load_trajectory(task_id, include_prm=False, trajectories_dir=trajectories_dir)
    try:
        prm = ProcessRewardModel(use_llm_judge=bool(use_llm_judge))
        prm_res = prm.score_trajectory(raw_traj)
        from dataclasses import asdict
        prm_result = asdict(prm_res)
        if getattr(prm, "_llm_judge_used", False):
            prm_result["_llm_judge_used"] = True
    except Exception:
        # Fallback to loader path
        traj = load_trajectory(task_id, include_prm=True, trajectories_dir=trajectories_dir)
        prm_result = traj.get("prm_result") or {}
    traj = raw_traj
    traj["prm_result"] = prm_result

    actual_path = find_trajectory_file(task_id, trajectories_dir=trajectories_dir)

    result = {
        "task_id": task_id,
        "trajectory_path": str(actual_path) if actual_path else None,
        "prm_overall_score": prm_result.get("overall_prm_score"),
        "prm_high_quality_steps": prm_result.get("num_high_quality_steps"),
        "prm_low_quality_steps": prm_result.get("num_low_quality_steps"),
        "events_count": len(traj.get("events", [])),
    }

    # Flywheel trigger + shadow harness EXCISED (Tier 2 surgical, Jules continuation 2026-06-13 task f29c675b)
    # All Python flywheel orchestration removed. Use agentforge-runner flywheel-step / continuous directly.
    pure_rust = is_pure_rust_flywheel() if \"is_pure_rust_flywheel\" in globals() else True
    shadow_mode = str(os.getenv(\"AGENTFORGE_RUST_FLYWHEEL_SHADOW\", \"0\")).lower() in (\"1\", \"true\", \"yes\", \"on\")

    # (core PRM/trajectory enrichment above; sidecar/mapping/continuous runner tick below)

    # Write PRM sidecar (very useful for later analysis / training)
    if actual_path and prm_result:
        try:
            sidecar_path = Path(actual_path).with_suffix(".prm.json")
            sidecar_data = {
                "task_id": task_id,
                "prm_result": prm_result,
                "generated_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
            }
            with open(sidecar_path, "w", encoding="utf-8") as f:
                json.dump(sidecar_data, f, indent=2, ensure_ascii=False)
            result["prm_sidecar"] = str(sidecar_path)
        except Exception:
            pass

    # Update mapping (best-effort)
    try:
        from .mappings import update_status
        update_status(task_id, "processed", extra={
            "prm_overall_score": result["prm_overall_score"],
            "trajectory_path": result["trajectory_path"],
        })
        result["mapping_updated"] = True
    except Exception:
        result["mapping_updated"] = False

    # === PRODUCTION POLISH: continuous tick inside post_process (remaining integration point) ===
    # Under pure or shadow: non-blocking direct runner continuous (autonomy closer + health + shadow fidelity).
    # Mirrors exactly what rust_flywheel_after_task.sh + timer now do. Makes continuous fully wired into post_process path.
    # Promote remains the obvious next (via candidate promote after list in review).
    if pure_rust or shadow_mode:
        # direct runner continuous (already the target surface)
        try:
            runner = os.getenv("AGENTFORGE_RUST_RUNNER") or "/home/eveselove/agentforge/rust/target/release/agentforge-runner"
            if os.path.isfile(runner):
                import subprocess
                subprocess.Popen([runner, "--json", "continuous", "--top-n", "2"] + (["--shadow"] if shadow_mode else []), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                result["rust_continuous_ticked"] = True
        except Exception as _e:
            result["rust_continuous_error"] = str(_e)[:100]
                # Also surface promote UX note for farm observers
                result["next_promote"] = "agentforge-runner candidate list --top 5 ; candidate promote <id> --copy-to-skills"
        except Exception as _ce:
            result["rust_continuous_error"] = str(_ce)[:120]

    return result


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python -m agentforge.eval.post_process <task_id>")
        sys.exit(1)

    res = post_process_task(sys.argv[1])
    print(json.dumps(res, indent=2, ensure_ascii=False))
