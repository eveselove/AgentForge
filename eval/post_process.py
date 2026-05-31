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

    # --- Rust bridge + Flywheel (Phase 2/3 turbo, DEFAULT for Antigravity) ---
    # Full Rust-powered self-improving flywheel is ON BY DEFAULT (no env needed).
    # FINAL AGGRESSIVE DEPRECATION SWEEP (Phase 4): last local shim eradicated.
    # Direct call to central is_rust_flywheel_disabled() (THE source; covers ALL Phase 4 variants).
    # See PHASE4_REMOVAL_PLAN.md (zero local guard logic left in tree).
    # Ultra-safe: top-level import already guarantees binding or safe fallbacks.

    # PHASE 3/4 PRODUCTION POLISH: strengthened central is_pure... . Direct agentforge-runner (flywheel-step + continuous + candidate promote + shadow) is the complete obvious surface.
    # No local duplication. Python post_process flywheel glue deprecated (non-breaking fallback only).
    # Direct: agentforge-runner flywheel-step --real-data --output-dir ... --ingest ; continuous + promote + shadow fully integrated here + after_task.
    pure_rust = is_pure_rust_flywheel()

    # Phase 2 shadow / dual-run (v5 NEAR FARM-READY): AGENTFORGE_RUST_FLYWHEEL_SHADOW=1 triggers dual (Rust + Py) for fidelity.
    # Richer v5 fidelity (prompt_jacc + proposal_content_sim + grade/perf/severity + streak/trend/health aggregate) via parity_harness.
    # CONTINUOUS DUAL: dedicated AGENTFORGE_SHADOW_EVERY_N=2 (default) counter forces frequent dual collection for metrics (independent of pure EVERY_N=5).
    # Written to /tmp/agentforge_rust_flywheel/shadow_fidelity_*.json + _latest + _aggregate. Full support in after_task/hooks/runner --shadow + harness CLI.
    # Farm/CI/watchdog/canary ready on real data. Independent of pure_rust flag. Zero risk: trusted Py path always drives main result.
    shadow_mode = str(os.getenv("AGENTFORGE_RUST_FLYWHEEL_SHADOW", "0")).lower() in ("1", "true", "yes", "on")
    if shadow_mode:
        print("[post_process] PHASE2 SHADOW MODE ACTIVE (v5 NEAR FARM-READY + CONTINUOUS DUAL): dual Rust+Python for richer fidelity (grade/sev + pass/score). SHADOW_EVERY_N enables continuous real-farm metrics collection.")

    if not pure_rust:
        warnings.warn(
            "eval/post_process.py Rust flywheel trigger (Python orchestration path) "
            "is deprecated per RUST_FULL_MIGRATION_PLAN.md PHASE 3 FINAL SWEEP. "
            "Direct replacement: agentforge-runner flywheel-step --real-data --ingest . "
            "Python path remains only for !is_pure_rust_flywheel() (non-breaking).",
            DeprecationWarning,
            stacklevel=2,
        )

    rust_flywheel_enabled = not is_rust_flywheel_disabled() or pure_rust
    if rust_flywheel_enabled:
        try:
            from agentforge.learning.trajectory_dataset import export_preference_pairs_via_rust
            rust_pairs = export_preference_pairs_via_rust()
            if rust_pairs:
                result["rust_exported_pairs"] = len(rust_pairs)
                result["rust_bridge_used"] = True
                result["rust_sample_pair"] = rust_pairs[0]
        except Exception as e:
            result["rust_bridge_error"] = str(e)[:200]

        # Call run_rust_flywheel_step (direct) under the default-on guard (unless disabled).
        # Attaches proposal + candidate_yaml_path to result so farm sees autonomous improvement artifacts.
        # (run_rust_flywheel_step already forces USE_RUST internally when requested.)
        # SAFE + RATE LIMITED for live farm: only every N tasks (AGENTFORGE_RUST_FLYWHEEL_EVERY_N, default 5),
        # and only if the Rust binary is present (prefers release path).
        #
        # Phase 1 bridge hardening: AFTER the Rust rich export (export_preference_pairs_via_rust above),
        # when pure_rust (is_pure_rust_flywheel() or AGENTFORGE_FLYWHEEL_ENGINE=rust), PREFER the native
        # `agentforge-runner flywheel-step --real-data --output-dir <temp> --ingest` using release binary.
        # This makes pure-Rust emission the hot path for new Antigravity tasks. Ingest via candidates crate
        # inside the binary (or fall back to Python path/ingest on any failure). Non-breaking: !pure keeps Python.
        if rust_flywheel_enabled:
            do_flywheel = False
            try:
                # Use discover (prefers release for prod polish) + env
                try:
                    from agentforge.learning.trajectory_dataset import find_rust_runner  # type: ignore
                    discovered = find_rust_runner()
                    runner = os.getenv("AGENTFORGE_RUST_RUNNER") or (str(discovered) if discovered else "/home/agx/agentforge/rust/target/release/agentforge-runner")
                except Exception:
                    runner = os.getenv("AGENTFORGE_RUST_RUNNER", "/home/agx/agentforge/rust/target/release/agentforge-runner")
                if os.path.isfile(runner) and os.access(runner, os.X_OK):
                    # Rate limit using simple atomic-ish counter (respects AGENTFORGE_RUST_FLYWHEEL_EVERY_N from snippet)
                    counter_dir = Path("/tmp/agentforge_rust_flywheel")
                    counter_dir.mkdir(parents=True, exist_ok=True)
                    counter_file = counter_dir / ".flywheel_postprocess_counter"
                    n = int(os.getenv("AGENTFORGE_RUST_FLYWHEEL_EVERY_N", "5") or "5")
                    if n < 1:
                        n = 5
                    count = 0
                    try:
                        if counter_file.exists():
                            count = int(counter_file.read_text().strip() or "0")
                    except Exception:
                        count = 0
                    count = (count + 1) % 100000  # bound
                    counter_file.write_text(str(count))
                    if (count % n) == 0:
                        do_flywheel = True
                        result["rust_flywheel_rate_limited"] = {"every_n": n, "this_count": count}
                    else:
                        result["rust_flywheel_skipped_rate_limit"] = {"every_n": n, "count": count}
                else:
                    result["rust_flywheel_skipped_no_binary"] = runner

                # === Phase 2 shadow CONTINUOUS DUAL SUPPORT (v5 farm-ready) ===
                # Independent rate limit for shadow fidelity collection (richer data for validation/soak).
                # AGENTFORGE_SHADOW_EVERY_N (default 2) allows frequent dual (Rust+Py) runs for metrics
                # WITHOUT changing production flywheel cadence (pure_rust uses its own EVERY_N).
                # When shadow active, this ensures continuous dual-run fidelity on real farm data for
                # watchdog/cron/CI gates using --shadow-aggregate etc. Zero impact on prod promote path.
                if shadow_mode:
                    try:
                        shadow_counter_file = counter_dir / ".shadow_fidelity_counter"
                        shadow_n = int(os.getenv("AGENTFORGE_SHADOW_EVERY_N", "2") or "2")
                        if shadow_n < 1:
                            shadow_n = 2
                        s_count = 0
                        try:
                            if shadow_counter_file.exists():
                                s_count = int(shadow_counter_file.read_text().strip() or "0")
                        except Exception:
                            s_count = 0
                        s_count = (s_count + 1) % 100000
                        shadow_counter_file.write_text(str(s_count))
                        if (s_count % shadow_n) == 0:
                            do_flywheel = True  # force dual paths for fidelity even if pure rate skipped
                            result["shadow_fidelity_rate_limited"] = {"every_n": shadow_n, "this_count": s_count, "continuous_dual": True}
                        else:
                            result["shadow_fidelity_skipped_rate_limit"] = {"every_n": shadow_n, "count": s_count}
                    except Exception as _se:
                        # fail-open for shadow fidelity (we want data)
                        do_flywheel = True
                        result["shadow_rate_limit_error"] = str(_se)[:80]
            except Exception as _e:
                # On any rate-limit error, be conservative and allow (or skip)
                do_flywheel = True  # fail-open for data flow, but log
                result["rust_flywheel_rate_limit_error"] = str(_e)[:120]

            if do_flywheel:
                fw = None
                rust_fw = None
                python_fw = None
                runner_for_shadow = None

                # Discover runner once (supports pure path + Phase 2 shadow dual-run)
                try:
                    if callable(get_rust_runner_path):
                        runner_for_shadow = get_rust_runner_path()
                except Exception:
                    runner_for_shadow = None
                if not runner_for_shadow:
                    try:
                        from agentforge.learning.trajectory_dataset import find_rust_runner  # type: ignore
                        d = find_rust_runner()
                        if d:
                            runner_for_shadow = d
                    except Exception:
                        pass
                if not runner_for_shadow:
                    runner_for_shadow = os.getenv("AGENTFORGE_RUST_RUNNER", "/home/agx/agentforge/rust/target/release/agentforge-runner")

                # PURE RUST BRIDGE - Phase 1 hardened (2026-05-31)
                # For pure_rust (is_pure_rust_flywheel() or AGENTFORGE_FLYWHEEL_ENGINE=rust or AGENTFORGE_PURE_RUST_FLYWHEEL or .pure_rust_flywheel marker):
                #   ALWAYS prefer the RELEASE `agentforge-runner flywheel-step --real-data --output-dir /tmp/... --ingest` first.
                #   The attempt is forced (no early gate on !exists for pure path) so that ONLY real subprocess failures
                #   (FileNotFound at exec, nonzero rc, timeout, other exc) cause fallback to Python path (with clear logging).
                #   On success for pure non-shadow: set fw so Python path is skipped (hot direct path).
                #   Strong structured result fields always populated: rust_flywheel_via, rust_flywheel_artifacts_dir,
                #   rust_flywheel_proposal, rust_flywheel_candidate_yaml, rust_flywheel_manifest, + status/binary on paths.
                #   Non-breaking when !pure_rust: do_rust_path / do_python_path / legacy flow completely unchanged.
                #   Release binary is explicitly forced as the preferred candidate for pure (production quality).
                if pure_rust and not shadow_mode:
                    release_pref = Path("/home/agx/agentforge/rust/target/release/agentforge-runner")
                    if release_pref.is_file() and os.access(str(release_pref), os.X_OK):
                        runner_for_shadow = release_pref
                    # else: keep discovered; the forced attempt below will surface real failure (e.g. missing bin)

                do_rust_path = (pure_rust or shadow_mode) and os.path.isfile(str(runner_for_shadow)) and os.access(str(runner_for_shadow), os.X_OK)
                if pure_rust and not shadow_mode:
                    do_rust_path = True  # force attempt for pure so fallback ONLY happens on real subproc failure
                do_python_path = (not pure_rust or shadow_mode)  # run Python for main flow OR for shadow fidelity dual

                # Phase 2 shadow enrichment: capture precise dual-run timings for fidelity (rust vs py latency delta is key validation signal)
                _shadow_t0_rust = None
                _shadow_t0_py = None
                _shadow_rust_ms = 0.0
                _shadow_py_ms = 0.0
                _shadow_rust_dir = None
                _shadow_py_dir = None

                if do_rust_path:
                    try:
                        from datetime import datetime as _dt
                        ts = _dt.utcnow().strftime("%Y%m%d_%H%M%S")
                        out_dir = Path("/tmp/agentforge_rust_flywheel") / f"{'shadow' if shadow_mode else 'pure'}_flywheel_step_{ts}"
                        out_dir.mkdir(parents=True, exist_ok=True)
                        _shadow_rust_dir = str(out_dir)
                        cmd = [
                            str(runner_for_shadow),
                            "flywheel-step",
                            "--real-data",
                            "--output-dir", str(out_dir),
                            "--ingest",
                        ]
                        if shadow_mode:
                            cmd.append("--shadow")  # basic flag support for direct runner invocation in shadow context
                            print("[post_process] SHADOW: invoking Rust binary path (agentforge-runner flywheel-step --real-data --ingest --shadow)")
                        else:
                            print("[post_process] PURE RUST BRIDGE: preferring RELEASE agentforge-runner flywheel-step --real-data --output-dir --ingest")
                        _shadow_t0_rust = __import__("time").time()
                        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
                        if _shadow_t0_rust is not None:
                            _shadow_rust_ms = round((__import__("time").time() - _shadow_t0_rust) * 1000, 1)
                        if proc.returncode == 0:
                            result["rust_flywheel_triggered"] = True
                            result["rust_flywheel_pure_rust_binary"] = not shadow_mode
                            result["rust_flywheel_shadow_binary"] = shadow_mode
                            result["rust_flywheel_artifacts_dir"] = str(out_dir)
                            result["rust_flywheel_via"] = "agentforge-runner/flywheel-step+ingest(candidates)"
                            result["rust_flywheel_binary_used"] = str(runner_for_shadow)
                            result["rust_flywheel_status"] = "success"
                            prop_p = out_dir / "proposal.json"
                            rust_proposal = None
                            if prop_p.exists():
                                try:
                                    rust_proposal = json.loads(prop_p.read_text(encoding="utf-8"))
                                    result["rust_flywheel_proposal"] = rust_proposal
                                except Exception:
                                    result["rust_flywheel_proposal"] = {"_parse_error": True}
                            else:
                                result["rust_flywheel_proposal"] = None
                            cand_p = out_dir / "candidate_skill.yaml"
                            if cand_p.exists():
                                result["rust_flywheel_candidate_yaml"] = str(cand_p)
                            man_p = out_dir / "flywheel_manifest.json"
                            if man_p.exists():
                                result["rust_flywheel_manifest"] = str(man_p)
                            print(f"[post_process] {'SHADOW ' if shadow_mode else ''}Rust flywheel-step via agentforge-runner -> artifacts={out_dir}")
                            rust_fw = {"artifacts_dir": str(out_dir), "candidate_yaml_path": str(cand_p) if cand_p.exists() else None, "proposal": rust_proposal}
                            if pure_rust and not shadow_mode:
                                fw = rust_fw  # success: skip Python fallback entirely (direct pure hot path)
                        else:
                            # real subprocess failure (nonzero)
                            err_tail = (proc.stderr or "")[:300]
                            print(f"[post_process] PURE RUST BRIDGE: release binary flywheel-step FAILED rc={proc.returncode} (REAL SUBPROC FAILURE; Python fallback only for this run). stderr[:300]={err_tail}")
                            result["rust_flywheel_via"] = "release-binary-failed"
                            result["rust_flywheel_status"] = f"failed_rc_{proc.returncode}"
                            result["rust_flywheel_error"] = err_tail
                            result["rust_flywheel_artifacts_dir"] = str(out_dir)
                    except Exception as _e:
                        # real failure (missing release bin at exec time, timeout, etc)
                        print(f"[post_process] PURE RUST BRIDGE: direct RELEASE flywheel-step subprocess FAILED (REAL FAILURE -> Python fallback only): {_e}")
                        result["rust_flywheel_via"] = "release-binary-invocation-failed"
                        result["rust_flywheel_status"] = "subprocess_exception"
                        result["rust_flywheel_error"] = str(_e)[:200]

                # === POLISHED INTEGRATION POINT: explicit continuous tick (autonomy meta-loop) after flywheel-step attempt ===
                # Completes wiring of continuous + shadow into post_process (matches after_task hook + help text + demo).
                # Runs under pure or shadow (non-fatal, uses release binary, --json, writes health + suggested).
                # Result carries rust_continuous_tick for observability / harness / watchdog.
                if (pure_rust or shadow_mode) and ("rust_flywheel_triggered" in result or shadow_mode):
                    try:
                        cont_r = os.getenv("AGENTFORGE_RUST_RUNNER")
                        if not cont_r or not (os.path.isfile(cont_r) and os.access(cont_r, os.X_OK)):
                            rel = "/home/agx/agentforge/rust/target/release/agentforge-runner"
                            cont_r = rel if (os.path.isfile(rel) and os.access(rel, os.X_OK)) else "/home/agx/agentforge/rust/target/debug/agentforge-runner"
                        cont_cmd = [cont_r, "--json", "continuous", "--top-n", "2"]
                        if shadow_mode:
                            cont_cmd.append("--shadow")
                        cproc = subprocess.run(cont_cmd, capture_output=True, text=True, timeout=90)
                        if cproc.returncode == 0:
                            try:
                                cout = json.loads((cproc.stdout or "").strip() or "{}")
                            except Exception:
                                cout = {}
                            result["rust_continuous_tick"] = {
                                "via": "agentforge-runner/continuous@post_process",
                                "top_n": 2,
                                "shadow": bool(shadow_mode),
                                "suggested_count": cout.get("suggested_count") or (len(cout.get("suggested", [])) if isinstance(cout.get("suggested"), list) else 0),
                                "health_written": cout.get("health_written") or "/tmp/agentforge_rust_flywheel/flywheel_health.json",
                                "dry_run": cout.get("dry_run", True),
                            }
                            print(f"[post_process] INTEGRATION: continuous tick via runner (count={result['rust_continuous_tick']['suggested_count']}, shadow={shadow_mode})")
                    except Exception as _ce:
                        result["rust_continuous_tick_error"] = str(_ce)[:100]

                # Python path: run for !pure main flow, or for shadow, or for pure ONLY after real subproc failure of the preferred release (fw remains None)
                if do_python_path or (fw is None and not shadow_mode):
                    if pure_rust and not shadow_mode:
                        print("[post_process] PURE RUST BRIDGE: using Python fallback ONLY because preferred release binary direct attempt had real subprocess failure (transitional; non-breaking).")
                    elif shadow_mode:
                        print("[post_process] SHADOW: also invoking trusted Python path (phase2_3_integration.run_rust_flywheel_step) for dual fidelity comparison")
                    else:
                        print("[post_process] legacy Python path (phase2_3_integration.run_rust_flywheel_step)")
                    try:
                        from agentforge.phase2_3_integration import run_rust_flywheel_step
                        _shadow_t0_py = __import__("time").time()
                        python_fw = run_rust_flywheel_step(use_real_data=True, limit=12, env_force_rust=True)
                        if _shadow_t0_py is not None:
                            _shadow_py_ms = round((__import__("time").time() - _shadow_t0_py) * 1000, 1)
                        if python_fw:
                            _shadow_py_dir = python_fw.get("artifacts_dir")
                        if python_fw:
                            # In shadow mode: Python (trusted) provides the primary fw attachment; Rust artifacts already recorded above for fidelity
                            if not shadow_mode:
                                result["rust_flywheel_triggered"] = True
                            result["rust_flywheel_proposal"] = python_fw.get("proposal")
                            result["rust_flywheel_candidate_yaml"] = python_fw.get("candidate_yaml_path")
                            result["rust_flywheel_artifacts_dir"] = python_fw.get("artifacts_dir")
                            result["rust_flywheel_records"] = python_fw.get("records")
                            if not shadow_mode:
                                print(f"[post_process] Attached Rust flywheel proposal + candidate={python_fw.get('candidate_yaml_path')}")
                            fw = python_fw
                    except Exception as e:
                        result["rust_flywheel_error"] = str(e)[:180]
                        if shadow_mode:
                            print(f"[post_process] SHADOW Python path error (Rust path may have succeeded): {str(e)[:120]}")

                # === Phase 2 shadow v5 NEAR FARM-READY (via harness): +prompt_jacc/proposal_content/grade/perf/severity + richer aggregate (median/p95/streak/trend) + continuous dual. Full actionable metrics for farm usability/gates/CI. ===
                if shadow_mode and (rust_fw is not None or python_fw is not None or do_rust_path or do_python_path):
                    try:
                        from datetime import datetime as _dt2
                        fid_ts = _dt2.utcnow().strftime("%Y%m%d_%H%M%S_%f")
                        counter_dir = Path("/tmp/agentforge_rust_flywheel")
                        counter_dir.mkdir(parents=True, exist_ok=True)

                        # Prefer full artifacts via harness load (for manifests, rich exports) when dirs known; fallback to inline props
                        rust_dir = (rust_fw or {}).get("artifacts_dir") or result.get("rust_flywheel_artifacts_dir")
                        py_dir = (python_fw or fw or {}).get("artifacts_dir") if (python_fw or fw) else None
                        rust_prop = (rust_fw or {}).get("proposal") or result.get("rust_flywheel_proposal")
                        py_prop = (python_fw or {}).get("proposal") or (fw or {}).get("proposal") if fw else result.get("rust_flywheel_proposal")

                        rust_succ = bool(rust_fw is not None or result.get("rust_flywheel_pure_rust_binary") or result.get("rust_flywheel_shadow_binary"))
                        py_succ = bool(python_fw is not None or fw)

                        # Use unified rich compute from harness (gets v2 metrics everywhere)
                        fid = None
                        try:
                            from agentforge.learning.flywheel_parity.parity_harness import FlywheelParityHarness
                            h = FlywheelParityHarness()
                            r_arts = {}
                            p_arts = {}
                            if rust_dir and Path(rust_dir).exists():
                                try:
                                    r_arts = h.load_from_output_dir(Path(rust_dir))
                                except Exception:
                                    pass
                            if py_dir and Path(py_dir).exists():
                                try:
                                    p_arts = h.load_from_output_dir(Path(py_dir))
                                except Exception:
                                    pass
                            # ensure props if load missed
                            if not r_arts.get("proposal.json") and rust_prop:
                                r_arts["proposal.json"] = rust_prop
                            if not p_arts.get("proposal.json") and py_prop:
                                p_arts["proposal.json"] = py_prop
                            fid = h.compute_rich_shadow_fidelity(r_arts or {"proposal.json": rust_prop or {}}, p_arts or {"proposal.json": py_prop or {}})
                        except Exception:
                            fid = None

                        if fid is None:
                            # Fallback minimal (should rarely hit)
                            fidelity = {
                                "timestamp": _dt2.utcnow().isoformat() + "Z",
                                "mode": "shadow",
                                "env": "AGENTFORGE_RUST_FLYWHEEL_SHADOW=1",
                                "fidelity_version": "phase2-rich-v5-near-farm-ready-fallback",
                                "rust_succeeded": rust_succ,
                                "python_succeeded": py_succ,
                                "rust_artifacts_dir": rust_dir,
                                "python_candidate_yaml": (python_fw or fw or {}).get("candidate_yaml_path") if (python_fw or fw) else None,
                                "note": "Phase 2 shadow (harness compute unavailable this run; basic fallback).",
                            }
                            fid = fidelity

                        # Always attach post_process context + the new timing enrichment
                        fid["rust_artifacts_dir"] = rust_dir
                        fid["python_candidate_yaml"] = (python_fw or fw or {}).get("candidate_yaml_path") if (python_fw or fw) else None
                        if _shadow_rust_ms or _shadow_py_ms:
                            fid["post_process_timings_ms"] = {"rust": _shadow_rust_ms, "py": _shadow_py_ms}
                            if "time_rust_ms" not in fid or fid.get("time_rust_ms", 0) == 0:
                                fid["time_rust_ms"] = _shadow_rust_ms
                                fid["time_py_ms"] = _shadow_py_ms
                                fid["time_delta_ms"] = round(abs(_shadow_rust_ms - _shadow_py_ms), 1)
                        if "note" not in fid:
                            fid["note"] = "Phase 2 shadow NEAR FARM-READY (v5+: prompt_bigram + overall_semantic + grade/perf/severity + rich aggregate streak/trend/p95 + all diffs + continuous dual support) via parity_harness + post_process. Truly usable on real farm data, full hook integration."

                        fid_file = counter_dir / f"shadow_fidelity_{fid_ts}.json"
                        with open(fid_file, "w", encoding="utf-8") as f:
                            json.dump(fid, f, indent=2, ensure_ascii=False, default=str)
                        result["shadow_fidelity_written"] = str(fid_file)
                        result["shadow_mode"] = True
                        result["shadow_fidelity_pass"] = fid.get("fidelity_pass")
                        result["shadow_composite_score"] = fid.get("composite_fidelity_score")
                        print(f"[post_process] SHADOW MODE v5+ NEAR FARM-READY fidelity (harness + continuous dual) -> {fid_file} (pass={fid.get('fidelity_pass')}, score={fid.get('composite_fidelity_score')}, grade={fid.get('fidelity_grade')}, jacc={fid.get('rationale_similarity_jaccard')}, prompt_jacc={fid.get('new_system_prompt_jaccard')}, prompt_bigram={fid.get('new_system_prompt_bigram_jaccard')}, content_jacc={fid.get('proposals_content_avg_jaccard')}, semantic={fid.get('overall_semantic_fidelity')}, overlap={fid.get('proposal_key_overlap_pct')}, lv_delta={fid.get('learning_value_delta')}, severity={fid.get('divergence_severity')}, perf_ok={fid.get('perf_fidelity_ok')}, mismatched={len(fid.get('mismatched_critical_fields') or [])})")
                        # convenience latest for monitoring (watchdog etc) + rolling aggregate for continuous health
                        latest = counter_dir / "shadow_fidelity_latest.json"
                        with open(latest, "w", encoding="utf-8") as f:
                            json.dump(fid, f, indent=2, ensure_ascii=False, default=str)
                        # rolling aggregate (v5 richer via harness if avail - median/p95/streak/trend + pass_rate for continuous farm health)
                        try:
                            from agentforge.learning.flywheel_parity.parity_harness import FlywheelParityHarness
                            h = FlywheelParityHarness()
                            # Leverage harness aggregate logic (recomputes full v5 health from recent fidelity JSONs)
                            agg_info = h.run_shadow_aggregate(write=False) if hasattr(h, 'run_shadow_aggregate') else None
                            if agg_info and isinstance(agg_info, dict) and agg_info.get("aggregate"):
                                agg = agg_info["aggregate"]
                            else:
                                # Fallback rich computation inline (samples + streak + trend + percentiles)
                                fid_jsons = sorted(counter_dir.glob("shadow_fidelity_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:12]
                                scores = []
                                passes = []
                                for fpath in fid_jsons:
                                    try:
                                        d = json.loads(fpath.read_text(encoding="utf-8"))
                                        sc = d.get("composite_fidelity_score")
                                        if isinstance(sc, (int, float)): scores.append(float(sc))
                                        p = d.get("fidelity_pass")
                                        if isinstance(p, bool): passes.append(1 if p else 0)
                                    except Exception: pass
                                if scores:
                                    ss = sorted(scores)
                                    n = len(ss)
                                    med = ss[n//2] if n else 0.0
                                    p95 = ss[max(0, int(0.95*n)-1)] if n else 0.0
                                    # trailing pass streak
                                    streak = 0
                                    for fp in fid_jsons:
                                        try:
                                            dd = json.loads(fp.read_text(encoding="utf-8"))
                                            if dd.get("fidelity_pass") is True: streak += 1
                                            else: break
                                        except: break
                                    recent_avg = round(sum(ss[-3:])/min(3,n),4) if n >= 1 else 0.0
                                    trend = "stable"
                                    if n >= 3:
                                        ov = sum(scores)/n
                                        if recent_avg > ov + 0.025: trend = "improving"
                                        elif recent_avg < ov - 0.025: trend = "degrading"
                                    agg = {
                                        "samples": n, "avg_composite": round(sum(scores)/n,4),
                                        "median_composite": round(med,4), "p95_composite": round(p95,4),
                                        "min": round(min(scores),4), "max": round(max(scores),4),
                                        "pass_rate": round(sum(passes)/len(passes),3) if passes else None,
                                        "recent_pass_streak": streak, "trend": trend, "recent_3_avg": recent_avg,
                                        "updated": _dt2.utcnow().isoformat() + "Z", "source": "post_process_v5_rich"
                                    }
                                else:
                                    agg = {"samples": 0}
                            (counter_dir / "shadow_fidelity_aggregate.json").write_text(json.dumps(agg, indent=2), encoding="utf-8")
                            fid["aggregate"] = agg
                        except Exception:
                            # ultra-minimal fallback
                            try:
                                roll = [float(d.get("composite_fidelity_score",0)) for d in [json.loads(f.read_text()) for f in sorted(counter_dir.glob("shadow_fidelity_*.json"))[-8:]] if isinstance(d.get("composite_fidelity_score"), (int,float))]
                                if roll:
                                    agg = {"samples": len(roll), "avg_composite": round(sum(roll)/len(roll),4)}
                                    (counter_dir / "shadow_fidelity_aggregate.json").write_text(json.dumps(agg, indent=2), encoding="utf-8")
                                    fid["aggregate"] = agg
                            except Exception: pass
                    except Exception as _fe:
                        result["shadow_fidelity_error"] = str(_fe)[:120]
                        print(f"[post_process] SHADOW fidelity write error (non-fatal): {_fe}")

                # ensure fw for any downstream if shadow produced only via python path
                if fw is None and python_fw:
                    fw = python_fw

                # === CONTINUOUS + PROMOTE + SHADOW FULL INTEGRATION (post_process farm hook polish) ===
                # After flywheel-step (pure or shadow), tick the pure Rust continuous meta-loop (autonomy closer)
                # for health JSON + prioritizer suggestions. Mirrors after-task hook. Non-blocking, safe, --json.
                # Promote is the follow-up action (user or later automation via candidate promote after list).
                # This makes post_process the complete integration point for the pure Rust surface trio.
                if (pure_rust or shadow_mode) and os.path.isfile(str(runner_for_shadow)) and os.access(str(runner_for_shadow), os.X_OK):
                    try:
                        cont_cmd = [
                            str(runner_for_shadow),
                            "--json",
                            "continuous",
                            "--top-n", "2",
                        ]
                        if shadow_mode:
                            cont_cmd.append("--shadow")
                        print(f"[post_process] CONTINUOUS INTEGRATION: ticking runner continuous (pure surface) {'--shadow ' if shadow_mode else ''}for autonomy meta-loop + health JSON")
                        cont_res = subprocess.run(cont_cmd, capture_output=True, text=True, timeout=60)
                        if cont_res.returncode == 0:
                            result["rust_continuous_ticked"] = True
                            result["rust_continuous_shadow"] = shadow_mode
                            # Health already written by runner; surface key path
                            result["flywheel_health_path"] = "/tmp/agentforge_rust_flywheel/flywheel_health.json"
                        else:
                            result["rust_continuous_error"] = (cont_res.stderr or cont_res.stdout)[-200:]
                    except Exception as _ce:
                        result["rust_continuous_error"] = str(_ce)[:120]
                    # Always surface promote guidance (the obvious next pure surface step after step+continuous)
                    result["pure_promote_guidance"] = "agentforge-runner candidate list --top 5 --sort value --json; agentforge-runner candidate promote <id> --copy-to-skills [--dry-run]"
                    print("[post_process] PURE RUST SURFACE: step+continuous wired; promote via 'candidate promote' (see result.pure_promote_guidance). Shadow fidelity emitted when enabled.")
    # ----------------------------------------------------------------

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
        try:
            runner_cp = None
            try:
                if callable(get_rust_runner_path):
                    runner_cp = get_rust_runner_path()
            except Exception:
                pass
            if not runner_cp:
                runner_cp = os.getenv("AGENTFORGE_RUST_RUNNER") or "/home/agx/agentforge/rust/target/release/agentforge-runner"
            if os.path.isfile(str(runner_cp)) and os.access(str(runner_cp), os.X_OK):
                cont_cmd = [str(runner_cp), "--json", "continuous", "--top-n", "2"]
                if shadow_mode:
                    cont_cmd.append("--shadow")
                # fire-and-forget (non-blocking for post_process hot path; logs to its own files via runner)
                __import__("subprocess").Popen(cont_cmd, stdout=__import__("subprocess").DEVNULL, stderr=__import__("subprocess").DEVNULL)
                result["rust_continuous_ticked"] = True
                result["rust_continuous_shadow"] = shadow_mode
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
