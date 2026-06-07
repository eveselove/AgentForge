#!/usr/bin/env python3
"""
bin/run_continuous_flywheel.py — Production continuous autonomy closer for the Rust flywheel.

One-shot invocation (designed for systemd timer / cron every 15-30min):
    cd /home/eveselove/agentforge
    ENABLE_RUST_FLYWHEEL=1 AGENTFORGE_USE_RUST=1 \
      python -m agentforge.bin.run_continuous_flywheel --top-n 2 --dry-run

Real (safe) run (promote-and-ab only; full prod promote only on explicit --auto-promote-winners + clear prior A/B winner):
    ... --top-n 2   # no --dry-run

Reuses 100% of existing:
- ENABLE_RUST_FLYWHEEL marker file
- AGENTFORGE_RUST_FLYWHEEL / USE_RUST / RUST_RUNNER envs + bin/rust_flywheel.env + enable_*.sh
- list_high_value_candidates + promote_candidate (with prepare_ab + auto_ab)
- LearningEvaluator A/B artifacts + is_clear_winner logic (via persisted ab_results)
- pending_candidates/ + rust_flywheel_step after-task hooks (this is the "meta" layer on top)

High reliability:
- fcntl flock (exclusive, non-blocking)
- Hard timeout (default 240s)
- Detailed logging to logs/continuous_flywheel_*.log + main grok_worker.log tail
- Idempotent: skips recently A/B'd (ab artifacts <6h old or .ab_in_progress marker)
- Dry-run default for safety in timer
- Never clobbers prod skills unless --auto-promote-winners + clear treatment winner (still uses timestamped safe names by default)

Closes the loop autonomously:
  high-LV collect (via prioritizer) → promote-and-ab (auto A/B prep + optional simulate run) for top N
  → detect clear winners from prior (real or sim) A/B results → (conditional) final promote + record

Next manual step only needed for: real A/B approval + final prod skill overwrite (when --auto-promote-winners not used).

!!! AGGRESSIVE FINAL DEPRECATION SWEEP (RUST_FULL_MIGRATION_PLAN.md + PHASE4_REMOVAL_PLAN.md) !!!
!!! THIS ENTIRE PYTHON CONTINUOUS FLYWHEEL ORCHESTRATOR DEPRECATED — PHASE 4 DELETION !!!
MIGRATE TO (direct, COMPLETE pure-Rust UX surface + shadow/farm integration):
  agentforge-runner continuous [--top-n N] [--no-dry-run] [--shadow] [--json]
  AGENTFORGE_RUST_FLYWHEEL_SHADOW=1 agentforge-runner --json continuous --top-n 2
  agentforge-runner flywheel-step --real-data --ingest [--shadow]
  agentforge-runner candidate ...
  (See runner --help for farm hooks examples: post_process, after_task, timer, demo, parity)

Guard EXCLUSIVELY with Phase 4 hardened central:
  from agentforge.learning.utils import is_pure_rust_flywheel

Loud warnings + pointers in code. Non-breaking !pure. Full removal Phase 4.
See learning/utils.py (stronger guards + complete file list)
See PHASE4_REMOVAL_PLAN.md for risks/rollback.
Runner help now documents all continuous + shadow integration points explicitly.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
import warnings
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure root import
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))

from learning.pending_candidates import (
    list_high_value_candidates,
    promote_candidate,
    PENDING_DIR,
    list_pending_candidates,
    cleanup_old_flywheel_artifacts,
)

# Phase 1: central pure-Rust detector (RUST_FULL_MIGRATION_PLAN.md) — expanded usage
try:
    from agentforge.learning.utils import is_pure_rust_flywheel
except Exception:
    from learning.utils import is_pure_rust_flywheel  # safe fallback for -m / direct

try:
    import fcntl  # linux only, perfect for our env
except ImportError:
    fcntl = None  # type: ignore

AGENTFORGE_ROOT = ROOT
LOG_DIR = AGENTFORGE_ROOT / "logs"
STATE_DIR = Path("/tmp/agentforge_rust_flywheel")
LOCK_FILE = STATE_DIR / ".continuous_flywheel.lock"
HEALTH_FILE = STATE_DIR / "flywheel_health.json"

# Reuse existing enable marker exactly
ENABLE_MARKER = AGENTFORGE_ROOT / "ENABLE_RUST_FLYWHEEL"


def log(msg: str, also_to_main: bool = True) -> None:
    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[continuous_flywheel {ts}Z] {msg}"
    print(line)
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_DIR / "continuous_flywheel.log", "a", encoding="utf-8") as f:
            f.write(line + "\n")
        if also_to_main:
            for main_log in (LOG_DIR / "grok_worker.log", LOG_DIR / "jules_worker.log"):
                if main_log.exists():
                    with open(main_log, "a", encoding="utf-8") as mf:
                        mf.write(line + "\n")
    except Exception:
        pass


def _env_enabled() -> bool:
    if ENABLE_MARKER.exists():
        return True
    if os.environ.get("AGENTFORGE_RUST_FLYWHEEL") == "1":
        return True
    if os.environ.get("ENABLE_RUST_FLYWHEEL") == "1":
        return True
    return False


def _acquire_lock(timeout_sec: int = 8) -> Optional[Any]:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if fcntl is None:
        # Fallback: simple mtime guard (still good for our single-host)
        if LOCK_FILE.exists():
            try:
                age = time.time() - LOCK_FILE.stat().st_mtime
                if age < 300:
                    log("Fallback lock contended (<5min) — another continuous run in flight; skipping.")
                    return None
            except Exception:
                pass
        LOCK_FILE.touch()
        return LOCK_FILE
    try:
        fh = open(LOCK_FILE, "w")
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fh
    except BlockingIOError:
        log("fcntl lock contended — another continuous flywheel run in flight; skipping (high reliability).")
        return None
    except Exception as e:
        log(f"Lock error (non-fatal, proceeding without hard lock): {e}")
        return open(LOCK_FILE, "w")  # best effort


def _release_lock(lock_handle: Any) -> None:
    try:
        if lock_handle and fcntl:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
        if isinstance(lock_handle, Path):
            lock_handle.unlink(missing_ok=True)
        elif lock_handle:
            lock_handle.close()
    except Exception:
        pass


def _timeout_handler(signum, frame):
    raise TimeoutError("Continuous flywheel step exceeded hard timeout")


def _is_recently_ab_tested(cand: Dict[str, Any], hours: int = 6) -> bool:
    """Idempotency: skip if A/B artifacts created recently or marker present."""
    p = Path(cand.get("path", ""))
    if not p.exists():
        return False
    markers = [p / ".ab_in_progress", p / ".ab_done"]
    for m in markers:
        if m.exists():
            return True
    for f in p.glob("ab_*.json"):
        try:
            if time.time() - f.stat().st_mtime < hours * 3600:
                return True
        except Exception:
            pass
    for f in (p / "run_ab_after_promote.py", p / "ab_test_config.json"):
        try:
            if f.exists() and time.time() - f.stat().st_mtime < hours * 3600:
                return True
        except Exception:
            pass
    return False


def _has_clear_winner(cand_path: Path) -> Optional[Dict[str, Any]]:
    """Detect clear winner from any persisted ab_result*.json using evaluator semantics."""
    for res_file in sorted(cand_path.glob("ab_result*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            data = json.loads(res_file.read_text(encoding="utf-8"))
            winner = data.get("winner")
            conf = data.get("confidence", "low")
            deltas = data.get("deltas", {})
            if winner == "treatment" and conf in ("medium", "high"):
                # Mirror evaluator.is_clear_winner
                sr = float(deltas.get("success_rate", 0.0))
                prm = float(deltas.get("avg_prm", 0.0))
                if sr > 0.03 or prm > 0.05:  # conservative gate
                    return {"file": str(res_file), "winner": winner, "confidence": conf, "deltas": deltas}
        except Exception:
            pass
    return None


def _recently_generated(cand: Dict[str, Any], hours: int = 1) -> bool:
    """For health metrics."""
    p = Path(cand.get("path", ""))
    if not p.exists():
        return False
    try:
        return (time.time() - p.stat().st_mtime) < hours * 3600
    except Exception:
        return False


def run_continuous_step(
    *,
    top_n: int = 2,
    dry_run: bool = True,
    min_avg_lv: float = 0.10,
    auto_promote_winners: bool = False,
    timeout_sec: int = 240,
) -> Dict[str, Any]:
    """Core one-shot step. Returns summary for health + logs.

    DEPRECATION NOTE (LOUD, Phase 2 prep):
        Direct pure-Rust equivalent now exists:
            agentforge-runner continuous --top-n {top_n} [--dry-run|--no-dry-run] [--json]
        This Python function is legacy bridge. Health written here is also written by Rust skeleton
        (to same /tmp/.../flywheel_health.json path) for shadow/fidelity comparison.
    """
    start = time.time()
    summary: Dict[str, Any] = {
        "started_at": datetime.utcnow().isoformat() + "Z",
        "dry_run": dry_run,
        "top_n": top_n,
        "promote_and_ab_count": 0,
        "clear_winner_promotes": 0,
        "skipped_recent_ab": 0,
        "high_value_considered": 0,
    }

    if not _env_enabled():
        log("ENABLE_RUST_FLYWHEEL marker (or AGENTFORGE_RUST_FLYWHEEL=1) not present — continuous step is a no-op. (reuse of existing guard)")
        summary["skipped"] = "env_guard"
        return summary

    # Ensure canonical env (non-destructive)
    os.environ.setdefault("AGENTFORGE_RUST_FLYWHEEL", "1")
    os.environ.setdefault("AGENTFORGE_USE_RUST", "1")
    if not os.environ.get("AGENTFORGE_RUST_RUNNER"):
        rel = AGENTFORGE_ROOT / "rust/target/release/agentforge-runner"
        dbg = AGENTFORGE_ROOT / "rust/target/debug/agentforge-runner"
        os.environ["AGENTFORGE_RUST_RUNNER"] = str(rel if rel.exists() else dbg)

    # PHASE 3 FINAL SWEEP: LOUD deprecation guard + pure-Rust commands (RUST_FULL_MIGRATION_PLAN.md)
    _pure = is_pure_rust_flywheel()
    print(f"[PHASE3 GUARD] is_pure_rust_flywheel()={_pure} (AGENTFORGE_PURE_RUST_FLYWHEEL/FLYWHEEL_ENGINE + .pure_rust_flywheel marker)", file=sys.stderr)
    if not _pure:
        warnings.warn(
            "bin/run_continuous_flywheel.py (Python continuous flywheel orchestration) "
            "is deprecated per RUST_FULL_MIGRATION_PLAN.md PHASE 3 FINAL. "
            "Direct: agentforge-runner continuous --top-n N . Python path remains for !pure (non-breaking).",
            DeprecationWarning,
            stacklevel=2,
        )
        # LOUD multi-line banner for logs/timer (high-signal)
        print("\n" + "="*70, file=sys.stderr)
        print("[DEPRECATION PHASE 3 - LOUD] Python continuous flywheel meta-orchestration DEPRECATED", file=sys.stderr)
        print("  bin/run_continuous_flywheel.py + .sh + agentforge-flywheel.* are heavily marked for removal.", file=sys.stderr)
        print("  PURE RUST REPLACEMENT (live, COMPLETE UX):", file=sys.stderr)
        print("    agentforge-runner --json continuous --top-n 2 [--shadow]", file=sys.stderr)
        print("    agentforge-runner continuous --top-n 2 --no-dry-run", file=sys.stderr)
        print("    AGENTFORGE_RUST_FLYWHEEL_SHADOW=1 agentforge-runner --json continuous --top-n 1", file=sys.stderr)
        print("  See: agentforge-runner continuous --help   (farm hooks, shadow, demo one-liners all listed)", file=sys.stderr)
        print("  Sunset after Phase 3 soak. One-command cutover: bin/make_pure_rust_flywheel_default.sh", file=sys.stderr)
        print("="*70 + "\n", file=sys.stderr)
        print(
            "[DEPRECATION PHASE 3] bin/run_continuous_flywheel.py — per RUST_FULL_MIGRATION_PLAN.md. "
            "Prefer direct `agentforge-runner continuous`. See bin/test_pure_rust_flywheel_step.sh .",
            file=sys.stderr,
        )

    # === PURE RUST DIRECT PATH FOR CONTINUOUS (integration polish for farm timer / cron / service) ===
    # When _pure (is_pure_rust_flywheel or AGENTFORGE_PURE_RUST_FLYWHEEL=1 etc), bypass all Python
    # orchestration here: invoke agentforge-runner continuous directly (with --json + shadow support).
    # This is the production hot path, matching after_task.sh + post_process continuous tick.
    # Writes identical /tmp/.../flywheel_health.json ; --shadow for dual fidelity.
    # Non-breaking: !pure continues to full legacy logic below.
    if _pure:
        log("[PURE RUST CONTINUOUS] Direct runner path (COMPLETE UX). Bypassing Python meta-orchestration.")
        try:
            runner = os.environ.get("AGENTFORGE_RUST_RUNNER")
            if not runner or not (Path(runner).is_file() and os.access(runner, os.X_OK)):
                rel = AGENTFORGE_ROOT / "rust/target/release/agentforge-runner"
                dbg = AGENTFORGE_ROOT / "rust/target/debug/agentforge-runner"
                runner = str(rel if rel.exists() else dbg)
            shadow = _env_flag("AGENTFORGE_RUST_FLYWHEEL_SHADOW", False) or os.getenv("AGENTFORGE_RUST_FLYWHEEL_SHADOW", "0") in ("1", "true", "yes", "on")
            cont_cmd = [runner, "--json", "continuous", "--top-n", str(top_n)]
            if not dry_run:
                cont_cmd.append("--no-dry-run")
            if shadow:
                cont_cmd.append("--shadow")
            log(f"  Invoking: {' '.join(cont_cmd)}")
            proc = subprocess.run(cont_cmd, capture_output=True, text=True, timeout=120, cwd=str(AGENTFORGE_ROOT))
            if proc.returncode == 0:
                try:
                    outj = json.loads(proc.stdout.strip() or "{}")
                except Exception:
                    outj = {"raw": proc.stdout[-500:]}
                summary["pure_rust_direct"] = True
                summary["continuous_via"] = "agentforge-runner/continuous"
                summary["suggested"] = outj.get("suggested", [])
                summary["health_written"] = outj.get("health_written")
                summary["shadow"] = shadow
                summary["dry_run"] = outj.get("dry_run", dry_run)
                # Health file guaranteed by runner
                health_p = Path("/tmp/agentforge_rust_flywheel/flywheel_health.json")
                if health_p.exists():
                    summary["health_path"] = str(health_p)
                log(f"[PURE RUST CONTINUOUS] Success. suggested={len(summary.get('suggested',[]))} health={summary.get('health_path')}")
                summary["duration_sec"] = round(time.time() - start, 2)
                return summary
            else:
                log(f"[PURE RUST CONTINUOUS] Runner rc={proc.returncode} (stderr tail: {(proc.stderr or '')[-200:]}); falling back to Python path (non-fatal)")
                summary["pure_rust_continuous_failed"] = True
        except Exception as _pe:
            log(f"[PURE RUST CONTINUOUS] Direct invoke error (falling back): {_pe}")
            # fallthrough to legacy (safe)

    # === SAFEGUARDS: respect flywheel health (rich export monitoring) for safe default ===
    # Timer + continuous always run but force conservative dry-run on degrade (graceful degradation)
    try:
        from learning.trajectory_dataset import get_flywheel_health
        _h = get_flywheel_health()
        _rich = _h.get("rich_exports") or {}
        _degraded = _h.get("degraded", False) or int(_rich.get("consecutive_failures", 0)) >= 5
        if _degraded:
            if not dry_run:
                log("🛡️ SAFEGUARD: flywheel degraded (rich_exports consec_fail or stale) — FORCING dry_run=True for this continuous tick (respects default-on safety)")
            dry_run = True
            summary["safeguard_forced_dry_run"] = True
            summary["degraded_reason"] = _h.get("degraded_reason")
    except Exception:
        pass  # non-fatal, proceed

    log(f"Starting continuous flywheel step (top_n={top_n}, dry_run={dry_run}, auto_promote_winners={auto_promote_winners})")
    log(f"Reusing ENABLE marker + all post_process / after_task / rust_flywheel_step wiring.")

    # Robust cleanup
    try:
        cleaned = cleanup_old_flywheel_artifacts(48)
        if cleaned:
            log(f"Cleaned {cleaned} old artifacts")
    except Exception:
        pass

    # High-value prioritizer (new in this autonomy wave, built on rich lv fields)
    high_value = list_high_value_candidates(limit=20, min_avg_lv=min_avg_lv)
    summary["high_value_considered"] = len(high_value)
    log(f"High-value candidates (via prioritizer): {len(high_value)}")

    lock = _acquire_lock()
    if lock is None:
        summary["skipped"] = "lock_contended"
        return summary

    try:
        # Hard timeout guard
        if hasattr(signal, "SIGALRM"):
            signal.signal(signal.SIGALRM, _timeout_handler)
            signal.alarm(timeout_sec)

        for cand in high_value[:top_n]:
            cid = cand.get("candidate_id", "")
            if not cid:
                continue
            if _is_recently_ab_tested(cand):
                summary["skipped_recent_ab"] += 1
                log(f"Skip {cid}: recently A/B'd (idempotent)")
                continue

            log(f"Auto promote-and-ab for high-LV candidate: {cid} (lv={cand.get('rich_avg_learning_value')})")
            try:
                if not dry_run:
                    # Safe: always prepare_ab + auto simulate A/B
                    res = promote_candidate(
                        cid,
                        copy_to_skills=True,
                        mark_reviewed=True,
                        dry_run=False,
                        prepare_ab=True,
                        auto_ab=True,
                    )
                    summary["promote_and_ab_count"] += 1
                    log(f"  promote-and-ab completed for {cid} -> {res}")
                else:
                    log(f"  [dry-run] would promote-and-ab {cid}")
                    summary["promote_and_ab_count"] += 1
            except Exception as e:
                log(f"  promote-and-ab failed for {cid} (non-fatal): {e}")

        # === Clear winner detection + conditional final promote (closes real A/B loop) ===
        # Only acts on candidates that already have real/sim A/B results showing treatment winner.
        all_cands = list_pending_candidates()
        for cand in all_cands:
            p = Path(cand.get("path", ""))
            winner_info = _has_clear_winner(p)
            if not winner_info:
                continue
            marker = p / ".autonomy_full_promoted"
            if marker.exists():
                continue
            log(f"DETECTED CLEAR WINNER for {cand.get('candidate_id')}: {winner_info}")
            if auto_promote_winners and not dry_run:
                try:
                    # Re-use promote (safe copy) + mark final
                    promote_candidate(
                        cand.get("candidate_id", ""),
                        copy_to_skills=True,
                        mark_reviewed=True,
                        dry_run=False,
                        prepare_ab=False,  # already done
                    )
                    marker.touch()
                    summary["clear_winner_promotes"] += 1
                    log(f"  AUTO full-promoted winner (safe) for {cand.get('candidate_id')}")
                except Exception as e:
                    log(f"  Winner promote failed (non-fatal): {e}")
            else:
                log(f"  Winner ready — manual approval or pass --auto-promote-winners (current: dry={dry_run})")
                # Touch a recommendation marker for humans / health
                (p / ".autonomy_winner_ready").touch(exist_ok=True)

        # Health snapshot for watchdog
        _write_health_snapshot(summary, high_value, all_cands)

        if hasattr(signal, "SIGALRM"):
            signal.alarm(0)

    finally:
        _release_lock(lock)

    summary["duration_sec"] = round(time.time() - start, 1)
    summary["finished_at"] = datetime.utcnow().isoformat() + "Z"
    log(f"Continuous step complete. Summary: {summary}")
    return summary


def _write_health_snapshot(step_summary: Dict, high_value: List[Dict], all_cands: List[Dict]) -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        now = time.time()
        last_hour_count = sum(1 for c in all_cands if _recently_generated(c, 1))
        high_lv_pending = len([c for c in high_value if float(c.get("rich_avg_learning_value") or 0) > 0.3])
        last_ab_ts = None
        for c in all_cands:
            p = Path(c.get("path", ""))
            for f in p.glob("ab_result*.json"):
                try:
                    mt = f.stat().st_mtime
                    if last_ab_ts is None or mt > last_ab_ts:
                        last_ab_ts = mt
                except Exception:
                    pass
        health = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "candidates_last_hour": last_hour_count,
            "high_lv_pending": high_lv_pending,
            "total_pending": len(all_cands),
            "last_ab_unix": last_ab_ts,
            "last_ab_age_min": round((now - last_ab_ts) / 60, 1) if last_ab_ts else None,
            "last_continuous": step_summary,
            "enable_marker_present": ENABLE_MARKER.exists(),
            # Safeguard fields (rich export health + continuous run outcome merged)
            "continuous_run_ok": True,
            "last_continuous_success_iso": datetime.utcnow().isoformat() + "Z",
        }
        # Merge rich stats if present (from trajectory bridge instrumentation)
        try:
            from learning.trajectory_dataset import get_flywheel_health as _gfh
            _fh = _gfh()
            if _fh.get("rich_exports"):
                health["rich_exports"] = _fh["rich_exports"]
            if _fh.get("degraded") is not None:
                health["degraded"] = _fh.get("degraded")
                health["degraded_reason"] = _fh.get("degraded_reason")
        except Exception:
            pass
        HEALTH_FILE.write_text(json.dumps(health, indent=2), encoding="utf-8")
        log(f"Health snapshot written: {HEALTH_FILE} (candidates_last_hour={last_hour_count})")
    except Exception as e:
        log(f"Health snapshot write skipped: {e}")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m agentforge.bin.run_continuous_flywheel",
        description="Continuous autonomous flywheel closer (15-30min cadence recommended). Safe, locked, reuses all ENABLE hooks. DEPRECATED: direct pure-Rust `agentforge-runner continuous [--top-n N] [--no-dry-run] [--shadow] [--json]` (complete surface, health + shadow fidelity for farm).",
    )
    parser.add_argument("--top-n", type=int, default=2, help="Max high-LV candidates to auto promote-and-ab per run")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Preview only (default for safety in timers)")
    parser.add_argument("--no-dry-run", action="store_true", help="Execute real promote-and-ab (still safe; A/Bs are simulate by default)")
    parser.add_argument("--min-lv", type=float, default=0.10, help="Min rich_avg_learning_value filter")
    parser.add_argument("--auto-promote-winners", action="store_true",
                        help="If a prior A/B result shows clear treatment winner (med/high conf), perform final safe promote (still timestamped). Use with caution.")
    parser.add_argument("--timeout", type=int, default=240, help="Hard timeout seconds for the step")
    parser.add_argument("--once", action="store_true", help="Alias for single invocation (default behavior)")
    args = parser.parse_args(argv)

    dry = not args.no_dry_run   # default True unless --no-dry-run
    if args.dry_run:
        dry = True

    try:
        summary = run_continuous_step(
            top_n=args.top_n,
            dry_run=dry,
            min_avg_lv=args.min_lv,
            auto_promote_winners=args.auto_promote_winners,
            timeout_sec=args.timeout,
        )
        print(json.dumps(summary, indent=2, default=str))
        return 0
    except TimeoutError as te:
        log(f"TIMEOUT: {te}")
        return 124
    except Exception as e:
        log(f"FATAL (non-blocking for caller): {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

# === PURE RUST FLYWHEEL DEFAULT (injected by make_pure_rust_flywheel_default.sh @ 2026-05-31T10:42:02+03:00) ===
# Pure Rust cutover (production excellence): when .pure_rust_flywheel or AGENTFORGE_PURE_RUST_FLYWHEEL=1 or FLYWHEEL_ENGINE=rust,
# force sole use of agentforge-runner binary for ALL flywheel/candidate/continuous orchestration.
# Complements env snippet + unit patches. Idempotent + guarded. Ultimate killswitch: DISABLE_RUST_FLYWHEEL=1.
PURE_MARKER="/home/eveselove/agentforge/.pure_rust_flywheel"
if [[ -f "$PURE_MARKER" ]] || [[ "${AGENTFORGE_PURE_RUST_FLYWHEEL:-0}" = "1" ]] || [[ "${AGENTFORGE_FLYWHEEL_ENGINE:-}" = "rust" ]]; then
    export AGENTFORGE_PURE_RUST_FLYWHEEL=1
    export AGENTFORGE_FLYWHEEL_ENGINE=rust
    if [ -x "/home/eveselove/agentforge/rust/target/release/agentforge-runner" ]; then
        export AGENTFORGE_RUST_RUNNER="/home/eveselove/agentforge/rust/target/release/agentforge-runner"
    fi
    export AGENTFORGE_FLYWHEEL_PROVENANCE="rust-agentforge-runner"
    # shellcheck disable=SC1091
    [ -f "/home/eveselove/agentforge/bin/rust_flywheel.env" ] && source "/home/eveselove/agentforge/bin/rust_flywheel.env" 2>/dev/null || true
fi
# End pure section — DISABLE_RUST_FLYWHEEL remains ultimate global off-switch everywhere.
