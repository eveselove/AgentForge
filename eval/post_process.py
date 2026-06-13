#!/usr/bin/env python3
"""
eval/post_process.py — PRM + trajectory enrichment + sidecar/mapping (core kept).

FLYWHEEL ORCHESTRATION TRIGGER (run_rust_flywheel_step, shadow harness, etc.) EXCISED
in Tier 2 surgical (Jules continuation 2026-06-13, task f29c675b + доделывай).

Direct canonical surface:
  agentforge-runner flywheel-step --real-data --ingest [--shadow]
  agentforge-runner continuous --top-n 2 [--shadow]
  agentforge-runner candidate list/promote ...

See docs/JULES_PY_REMOVAL_HANDOFF_f29c675b.md (Tier 2 section) and PHASE4 checklist.
Non-breaking for !pure paths (they should call runner directly in hooks/workers now).
"""

from pathlib import Path
from typing import Optional, Dict, Any
import json
import os

from .trajectory import load_trajectory, find_trajectory_file
from .prm import ProcessRewardModel

# Central guard (hardened) - single source of truth: learning/utils.py only (task-5af0e350)
# PHASE4_REMOVAL_PLAN marker: flywheel guard import only (for pure mode); surgical keep per checklist (Tier2).
from agentforge.learning.utils import is_pure_rust_flywheel


def post_process_task(
    task_id: str,
    trajectories_dir: Optional[Path] = None,
    use_llm_judge: Optional[bool] = None,
) -> Dict[str, Any]:
    """Core post-run: load trajectory, compute PRM, enrich, write sidecar, update mapping.
    Flywheel trigger removed - call agentforge-runner directly from after-task hooks.
    """
    if use_llm_judge is None:
        envv = os.getenv(
            "AGENTFORGE_PRM_USE_LLM_JUDGE", os.getenv("AGENTFORGE_PRM_LLM_JUDGE", "0")
        )
        use_llm_judge = str(envv).lower() in ("1", "true", "yes", "on")

    raw_traj = load_trajectory(
        task_id, include_prm=False, trajectories_dir=trajectories_dir
    )
    try:
        prm = ProcessRewardModel(use_llm_judge=bool(use_llm_judge))
        prm_res = prm.score_trajectory(raw_traj)
        from dataclasses import asdict

        prm_result = asdict(prm_res)
        if getattr(prm, "_llm_judge_used", False):
            prm_result["_llm_judge_used"] = True
    except Exception:
        traj = load_trajectory(
            task_id, include_prm=True, trajectories_dir=trajectories_dir
        )
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

    # NOTE: All previous flywheel trigger / shadow / run_rust_flywheel_step logic excised (Tier 2).
    # Pure Rust flywheel is now always direct via agentforge-runner (wired in after_task, workers, continuous).
    # Shadow fidelity (if needed) via runner --shadow + parity harness (if still present for tests).
    pure_rust = is_pure_rust_flywheel()
    shadow_mode = str(os.getenv("AGENTFORGE_RUST_FLYWHEEL_SHADOW", "0")).lower() in (
        "1",
        "true",
        "yes",
        "on",
    )

    if pure_rust or shadow_mode:
        # Direct runner continuous tick (canonical autonomy closer + health)
        try:
            runner = (
                os.getenv("AGENTFORGE_RUST_RUNNER")
                or "/home/eveselove/agentforge/rust/target/release/agentforge-runner"
            )
            if os.path.isfile(runner):
                import subprocess

                subprocess.Popen(
                    [runner, "--json", "continuous", "--top-n", "2"]
                    + (["--shadow"] if shadow_mode else []),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                result["rust_continuous_ticked"] = True
                result["rust_continuous_shadow"] = shadow_mode
                result["flywheel_health_path"] = (
                    "/tmp/agentforge_rust_flywheel/flywheel_health.json"
                )
        except Exception as _e:
            result["rust_continuous_error"] = str(_e)[:100]

    # Write PRM sidecar (very useful for later analysis / training)
    if actual_path and prm_result:
        try:
            sidecar_path = Path(actual_path).with_suffix(".prm.json")
            sidecar_data = {
                "task_id": task_id,
                "prm_result": prm_result,
                "generated_at": __import__("datetime").datetime.utcnow().isoformat()
                + "Z",
            }
            with open(sidecar_path, "w", encoding="utf-8") as f:
                json.dump(sidecar_data, f, indent=2, ensure_ascii=False)
            result["prm_sidecar"] = str(sidecar_path)
        except Exception:
            pass

    # Update mapping (best-effort)
    try:
        from .mappings import update_status

        update_status(
            task_id,
            "processed",
            extra={
                "prm_overall_score": result.get("prm_overall_score"),
                "trajectory_path": result.get("trajectory_path"),
            },
        )
        result["mapping_updated"] = True
    except Exception:
        result["mapping_updated"] = False

    return result


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m agentforge.eval.post_process <task_id>")
        sys.exit(1)
    res = post_process_task(sys.argv[1])
    print(json.dumps(res, indent=2, ensure_ascii=False))
