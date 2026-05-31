#!/usr/bin/env python3
"""
DEPRECATED — Full Rust Migration (2026-05-31)
This shim is a temporary bridge. Logic should move into agentforge-runner or native hooks.

See RUST_ONLY_MIGRATION_PLAN.md
"""

"""
rust_post_process_hook.py — Small production shim for Rust-accelerated post-processing (Legacy).

Callable from grok_runner.sh, grok_worker.sh, jules_worker, or directly after real tasks
(via the existing post_process.py which is already lightly wired).

When AGENTFORGE_USE_RUST=1 (or AGENTFORGE_RUST_RUNNER set):
- Forces the Rust path in post_process (preference export etc via agentforge-runner)
- Optionally triggers a bounded run_rust_flywheel_step (when AGENTFORGE_RUST_FLYWHEEL=1 too)

This is the zero-friction hook to drop into worker post-task steps so the Rust flywheel
affects live farm runs immediately.

Usage (from shell after a task):
    AGENTFORGE_USE_RUST=1 python /home/agx/agentforge/bin/rust_post_process_hook.py <task_id>

Or in worker scripts (non-blocking):
    ( AGENTFORGE_USE_RUST=1 python -m agentforge.bin.rust_post_process_hook $TASK_ID \
      >> logs/rust_hook_$TASK_ID.log 2>&1 ) &

It delegates to the canonical post_process_task + phase2_3_integration.

DEPRECATION (Phase 1/2/3, RUST_FULL_MIGRATION_PLAN.md):
    Hook wiring for Python flywheel orchestration (the flywheel step trigger here).
    Under pure Rust cutover the post_process flywheel glue + phase2_3 paths will
    short-circuit or delegate to binary (flywheel-step + continuous).

!!! AGGRESSIVE FINAL DEPRECATION SWEEP (RUST_FULL_MIGRATION_PLAN.md + PHASE4_REMOVAL_PLAN.md) !!!
!!! THIS FLYWHEEL TRIGGER HOOK + ALL PYTHON ORCHESTRATION PATHS HERE PHASE 4 DELETION TARGET !!!
PHASE 4 FINAL: Python flywheel orchestration hook DEPRECATED.
PREFER EXCLUSIVELY (RUNNER UX COMPLETE): agentforge-runner flywheel-step --real-data --ingest [--shadow]
    agentforge-runner --json continuous --top-n N [--no-dry-run] [--shadow]
Bridge now always prefers binary under is_pure_rust_flywheel(); Python fallback only for rollback.
Shadow: AGENTFORGE_RUST_FLYWHEEL_SHADOW=1 wires dual-run + fidelity JSONs here (see post_process).

Guard EXCLUSIVELY with Phase 4 hardened central (no local copies):
  from agentforge.learning.utils import is_pure_rust_flywheel, is_rust_flywheel_disabled

Non-breaking. Full removal order/risks/rollback in PHASE4_REMOVAL_PLAN.md (Tier 3).
See learning/utils.py exhaustive deprecated orchestration list.
Pure Rust surface (runner continuous + shadow into hooks) now obvious + complete for farm.
"""

from __future__ import annotations

import os
import sys
import warnings
import json
import subprocess
from pathlib import Path

# Make "import agentforge.xxx" work when script run directly (outside -m / installed pkg)
# Package dir is .../agentforge ; its parent (/home/agx) must be on sys.path
ROOT = Path(__file__).resolve().parent.parent  # agentforge/
PKG_PARENT = ROOT.parent  # e.g. /home/agx
if str(PKG_PARENT) not in sys.path:
    sys.path.insert(0, str(PKG_PARENT))

from agentforge.eval.post_process import post_process_task  # type: ignore
from agentforge.phase2_3_integration import run_rust_flywheel_step  # type: ignore

# Phase 1: central pure-Rust detector (RUST_FULL_MIGRATION_PLAN.md) — expanded usage in high-traffic hook
# PHASE 3/4: hardened central guards only (no local dupe)
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
        from learning.utils import is_pure_rust_flywheel, is_rust_flywheel_disabled  # fallback
        get_rust_runner_path = None  # type: ignore


def main(argv: list[str] | None = None) -> int:
    argv = argv or sys.argv[1:]
    if not argv:
        print("Usage: python -m agentforge.bin.rust_post_process_hook <task_id> [extra...]")
        print("  Sets up Rust env and runs post_process + optional flywheel step.")
        return 2

    task_id = argv[0]

    # Ensure Rust is considered (non-destructive to caller env)
    os.environ.setdefault("AGENTFORGE_USE_RUST", "1")

    print(f"[rust_post_process_hook] Starting for task_id={task_id} (USE_RUST={os.environ.get('AGENTFORGE_USE_RUST')})")

    try:
        result = post_process_task(task_id)
        print(f"[rust_post_process_hook] post_process result keys: {list(result.keys())}")
    except Exception as e:
        print(f"[rust_post_process_hook] post_process error (non-fatal): {e}")
        result = {"task_id": task_id, "error": str(e)[:200]}

    # Flywheel + continuous tick (meta autonomy) now driven inside post_process_task (rate-limited + binary-checked when AGENTFORGE_RUST_FLYWHEEL=1; pure runner path for step+continuous+promote+shadow).
    # This block kept for explicit override / direct canonical call via phase2_3_integration hook.
    # Still rate-limited here for safety when called standalone. Promote guidance surfaced in result.
    if os.environ.get("AGENTFORGE_RUST_FLYWHEEL") == "1":
        # PHASE 3 FINAL: use strengthened central guard (includes marker + disables, no duplication)
        # Direct: agentforge-runner flywheel-step --real-data --output-dir <temp> --ingest
        pure_rust_hook = is_pure_rust_flywheel()
        if not pure_rust_hook:
            warnings.warn(
                "rust_post_process_hook.py flywheel trigger (Python orchestration path) "
                "is deprecated per RUST_FULL_MIGRATION_PLAN.md PHASE 3. "
                "Prefer direct agentforge-runner flywheel-step (see pure_rust_hook path).",
                DeprecationWarning,
                stacklevel=2,
            )
        else:
            print("[rust_post_process_hook] PURE RUST BRIDGE: preferring direct RELEASE agentforge-runner (from hook)")
        do_fly = False
        try:
            n = int(os.environ.get("AGENTFORGE_RUST_FLYWHEEL_EVERY_N", "5") or 5)
            counter_file = Path("/tmp/agentforge_rust_flywheel/.flywheel_hook_counter")
            counter_file.parent.mkdir(parents=True, exist_ok=True)
            c = 0
            if counter_file.exists():
                try:
                    c = int(counter_file.read_text().strip() or "0")
                except Exception:
                    c = 0
            c = (c + 1) % 100000
            counter_file.write_text(str(c))
            if (c % max(n, 1)) == 0:
                do_fly = True
        except Exception:
            do_fly = True  # conservative

        if do_fly:
            # PURE RUST BRIDGE - Phase 1 hardened (2026-05-31) [hook path]
            # Same strong preference: ALWAYS try release `agentforge-runner flywheel-step ... --ingest` first for pure_rust_hook.
            # Only fall back to phase2_3 run_ fn on real subprocess failure (clear logs + strong fields).
            # Non-breaking for !pure (delegates exactly as before).
            fw = None
            if pure_rust_hook:
                runner_path = None
                try:
                    if callable(get_rust_runner_path):
                        runner_path = get_rust_runner_path()
                except Exception:
                    runner_path = None
                if not runner_path:
                    runner_path = os.environ.get("AGENTFORGE_RUST_RUNNER")
                release_pref = Path("/home/agx/agentforge/rust/target/release/agentforge-runner")
                if release_pref.is_file() and os.access(str(release_pref), os.X_OK):
                    runner_path = release_pref
                if not runner_path:
                    runner_path = "/home/agx/agentforge/rust/target/release/agentforge-runner"

                try:
                    from datetime import datetime as _dt
                    ts = _dt.utcnow().strftime("%Y%m%d_%H%M%S")
                    out_dir = Path("/tmp/agentforge_rust_flywheel") / f"hook_pure_flywheel_step_{ts}"
                    out_dir.mkdir(parents=True, exist_ok=True)
                    cmd = [
                        str(runner_path),
                        "flywheel-step",
                        "--real-data",
                        "--output-dir", str(out_dir),
                        "--ingest",
                    ]
                    print("[rust_post_process_hook] PURE RUST BRIDGE (hook): release agentforge-runner flywheel-step --real-data --ingest")
                    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
                    if proc.returncode == 0:
                        fw = {
                            "artifacts_dir": str(out_dir),
                            "candidate_yaml_path": str(out_dir / "candidate_skill.yaml") if (out_dir / "candidate_skill.yaml").exists() else None,
                            "proposal": None,
                        }
                        prop_p = out_dir / "proposal.json"
                        if prop_p.exists():
                            try:
                                fw["proposal"] = json.loads(prop_p.read_text(encoding="utf-8"))
                            except Exception:
                                pass
                        result["rust_flywheel_via"] = "agentforge-runner/flywheel-step+ingest(candidates)@hook"
                        result["rust_flywheel_artifacts_dir"] = str(out_dir)
                        result["rust_flywheel_proposal"] = fw.get("proposal")
                        result["rust_flywheel_candidate_yaml"] = fw.get("candidate_yaml_path")
                        result["rust_flywheel_binary"] = str(runner_path)
                        result["rust_flywheel_status"] = "success"
                        print(f"[rust_post_process_hook] PURE RUST BRIDGE (hook) SUCCESS: artifacts={out_dir}")
                        # Continuous integration polish (hook path): tick the autonomy meta-loop (mirrors after_task + post_process main)
                        try:
                            ccmd = [str(runner_path), "--json", "continuous", "--top-n", "1"]
                            if os.environ.get("AGENTFORGE_RUST_FLYWHEEL_SHADOW") in ("1", "true", "yes"):
                                ccmd.append("--shadow")
                            cproc = subprocess.run(ccmd, capture_output=True, text=True, timeout=60)
                            if cproc.returncode == 0:
                                result["rust_continuous_via_hook"] = "agentforge-runner/continuous"
                        except Exception:
                            pass
                    else:
                        err = (proc.stderr or "")[:250]
                        print(f"[rust_post_process_hook] PURE RUST BRIDGE (hook): release binary FAILED rc={proc.returncode} (REAL FAILURE, fallback to py). {err}")
                        result["rust_flywheel_via"] = "hook-release-failed"
                        result["rust_flywheel_status"] = f"failed_rc_{proc.returncode}"
                        result["rust_flywheel_error"] = err
                except Exception as _e:
                    print(f"[rust_post_process_hook] PURE RUST BRIDGE (hook): direct release subproc FAILED (REAL -> py fallback): {_e}")
                    result["rust_flywheel_via"] = "hook-release-invocation-failed"
                    result["rust_flywheel_status"] = "subprocess_exception"
                    result["rust_flywheel_error"] = str(_e)[:200]

            if fw is None:
                # Only reached for !pure, or for pure after real subproc failure of release (or no pure)
                if pure_rust_hook:
                    print("[rust_post_process_hook] PURE RUST BRIDGE (hook): Python fallback ONLY after real release subproc failure (non-breaking).")
                try:
                    # Prefer canonical... delegates internally to direct when pure (but we already tried above)
                    from agentforge.phase2_3_integration import run_rust_flywheel_step_if_enabled
                    fw = run_rust_flywheel_step_if_enabled(force=True) or run_rust_flywheel_step(use_real_data=True, limit=25, env_force_rust=True)
                except Exception as e:
                    print(f"[rust_post_process_hook] Flywheel step skipped: {e}")
                    result["rust_flywheel_error"] = str(e)[:120]
                    fw = None

            if fw:
                result["rust_flywheel"] = {
                    "proposal_summary": str((fw or {}).get("proposal", {}))[:300] if isinstance(fw, dict) else str(fw)[:200],
                    "candidate_yaml_path": (fw or {}).get("candidate_yaml_path") if isinstance(fw, dict) else None,
                    "rust_pairs": (fw or {}).get("rust_pairs") if isinstance(fw, dict) else None,
                    "via": result.get("rust_flywheel_via") or "phase2_3_or_direct_pure-prefers-binary@hook",
                }
                print(f"[rust_post_process_hook] Flywheel step (rate-pass) attached. candidate={(fw or {}).get('candidate_yaml_path') if isinstance(fw, dict) else 'n/a'}")
        else:
            print(f"[rust_post_process_hook] Flywheel skipped by rate limit (EVERY_N={os.environ.get('AGENTFORGE_RUST_FLYWHEEL_EVERY_N',5)})")

    # Emit compact for logs / callers
    print("[rust_post_process_hook] DONE")

    # === POLISH: continuous tick in hook (full integration of continuous + shadow + promote UX) ===
    # Under pure: fire direct runner continuous (non-blocking) for autonomy closer + health + fidelity.
    # Matches post_process + after_task. Promote is next obvious step after candidates appear.
    if pure_rust_hook or str(os.environ.get("AGENTFORGE_RUST_FLYWHEEL_SHADOW", "0")).lower() in ("1", "true"):
        try:
            rpath = os.environ.get("AGENTFORGE_RUST_RUNNER") or "/home/agx/agentforge/rust/target/release/agentforge-runner"
            if os.path.isfile(rpath) and os.access(rpath, os.X_OK):
                import subprocess
                ccmd = [rpath, "--json", "continuous", "--top-n", "2"]
                if str(os.environ.get("AGENTFORGE_RUST_FLYWHEEL_SHADOW", "0")).lower() in ("1", "true"):
                    ccmd.append("--shadow")
                subprocess.Popen(ccmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                print("[rust_post_process_hook] continuous ticked (pure/shadow)")
        except Exception:
            pass

    # For machine callers, could json dump but keep simple + human friendly
    return 0


if __name__ == "__main__":
    raise SystemExit(main())