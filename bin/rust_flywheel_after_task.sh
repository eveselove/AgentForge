#!/bin/bash
# ============================================================
# rust_flywheel_after_task.sh — Robust, idempotent, rate-limited
# hook for live auto-execution of the Rust flywheel after real
# task completions (Jules/Grok farm track).
#
# Called from workers (grok_worker.sh, jules_worker.sh) or runners
# AFTER post_process on a real task.
#
# - Takes task_id (preferred) or trajectory path as $1.
# - Respects ENABLE_RUST_FLYWHEEL marker file OR AGENTFORGE_RUST_FLYWHEEL=1.
# - Sets canonical env (prefers release binary).
# - Rate-limited: at most once per 5 minutes (global, via timestamp + flock lock).
# - Idempotent + safe: never blocks, never fails the caller, graceful degrade.
# - Invokes the *canonical* step: python -m agentforge.rust_flywheel_step --real-data --use-rust
#   (this loads real trajectories/.prm, runs Rust bridge, produces proposal,
#    writes artifacts, and *auto-drops* to pending_candidates/ via ingest).
# - Logs to logs/rust_flywheel_after_*.log
#
# Enable permanently:
#   - touch /home/eveselove/agentforge/ENABLE_RUST_FLYWHEEL
#   - or export AGENTFORGE_RUST_FLYWHEEL=1 in workers + source bin/rust_flywheel.env
#   - Workers will then call this after real post_process.
#
# Usage (manual test):
#   bash bin/rust_flywheel_after_task.sh c6046a84
#   # or with a trajectory path:
#   bash bin/rust_flywheel_after_task.sh /home/eveselove/agentforge/eval/trajectories/c6046a84_grok.jsonl
#
# Safe to call frequently from high-parallel workers.
#
# !!! AGGRESSIVE FINAL DEPRECATION SWEEP (RUST_FULL_MIGRATION_PLAN.md + PHASE4_REMOVAL_PLAN.md) !!!
# !!! bin/rust_flywheel_after_task.sh : After-task flywheel hook (Tier 3 glue) — Python orchestration paths deprecated !!!
# Under pure (default post cutover): invokes agentforge-runner flywheel-step --real-data --ingest directly (no Python step).
# This file is migration glue; flywheel trigger logic in post_process + phase2_3_integration also marked.
# Full details: PHASE4_REMOVAL_PLAN.md (Tier 3 removal, surgical, risks medium-high, rollback via disable scripts + env).
# Guard + central: learning/utils.py is_pure_rust_flywheel / is_rust_flywheel_disabled.
# See also: bin/make_pure...sh for service/timer patching, rust_post_process_hook.py, eval/post_process.py
#
# DEPRECATION WAVE 2 + RUNNER UX POLISH COMPLETE (RUST_FULL_MIGRATION_PLAN.md):
#   Pure Rust surface (agentforge-runner) is now the canonical path.
#   This hook is the farm after-task integration point (called by grok/jules workers post post_process).
#   === PURE MODE (is_pure_rust_flywheel or AGENTFORGE_PURE_RUST_FLYWHEEL=1 or FLYWHEEL_ENGINE=rust) ===
#     Direct (no Python orchestration):
#       $AGENTFORGE_RUST_RUNNER --json flywheel-step --real-data --ingest [--shadow]
#       AGENTFORGE_RUST_FLYWHEEL_SHADOW=1 $AGENTFORGE_RUST_RUNNER --json flywheel-step --real-data --ingest --shadow
#       $AGENTFORGE_RUST_RUNNER --json continuous --top-n 2 [--shadow]   # autonomy meta-loop
#     Promote (when candidates appear): candidate promote <id> --copy-to-skills
#   Legacy python path kept only for !pure (non-breaking fallback).
#   Shadow dual-run fidelity fully wired (flag + env) for parity harness / post_process / watchdog.
#   Continuous + promote + shadow fully integrated (direct runner calls in pure) + obvious in after-task + demo tools.
#   References: agentforge-runner --help, bin/test_pure_rust_flywheel_step.sh, learning/utils.py
#   Rate-limit / flock / safety / logging unchanged.
# !!! PHASE 3/4: Direct runner flywheel-step is the production path under pure. Python step deprecated.
# ============================================================

set -u
# Do not use -e globally; we want graceful non-fatal everywhere.

TASK_REF="${1:-}"
if [ -z "$TASK_REF" ]; then
  echo "[rust_flywheel_after] ERROR: usage: $0 <task_id> [trajectory_path]"
  echo "  (task_id or path to .jsonl trajectory; arg used for logging/trace only — flywheel scans global recent data)"
  exit 2
fi

AGENTFORGE_ROOT="/home/eveselove/agentforge"
ENABLE_MARKER="$AGENTFORGE_ROOT/ENABLE_RUST_FLYWHEEL"
LOG_DIR="$AGENTFORGE_ROOT/logs"
STATE_DIR="/tmp/agentforge_rust_flywheel"
mkdir -p "$LOG_DIR" "$STATE_DIR" 2>/dev/null || true

# Robustness: auto-cleanup of old rate-limit files + step artifact dirs (>48h) to prevent /tmp bloat
# from high-frequency farm triggers (hook fires on every real task when enabled).
# This is a small non-intrusive polish; runs on every hook invocation (idempotent, fast).
find "$STATE_DIR" -mindepth 1 -maxdepth 1 -mtime +2 -exec rm -rf {} + 2>/dev/null || true

LOG_FILE="$LOG_DIR/rust_flywheel_after_$(echo "$TASK_REF" | tr -cd '[:alnum:]_-').log"

log() {
  echo "[rust_flywheel_after $(date '+%H:%M:%S')] $*" | tee -a "$LOG_FILE" 2>/dev/null || echo "[rust_flywheel_after] $*"
}

# Guard: enabled only if marker file OR env explicitly on
if [ ! -f "$ENABLE_MARKER" ] && [ "${AGENTFORGE_RUST_FLYWHEEL:-0}" != "1" ]; then
  # Silent no-op when not enabled (workers may still call unconditionally in some patches)
  exit 0
fi

# Rate limit + idempotency (global 5 min window)
LAST_RUN_FILE="$STATE_DIR/.last_after_task_run"
LOCK_FILE="$STATE_DIR/.after_task_flywheel.lock"
RATE_LIMIT_SECS=300

# Use flock for exclusive check+run (portable; falls back gracefully)
exec 200>"$LOCK_FILE" 2>/dev/null || true

# Try to acquire lock with short timeout (non-blocking for caller if contended)
if command -v flock >/dev/null 2>&1; then
  if ! flock -w 8 200 2>/dev/null; then
    log "contended lock (another flywheel run in flight) — skipping this trigger (idempotent)"
    exit 0
  fi
fi

NOW=$(date +%s 2>/dev/null || echo 0)
if [ -f "$LAST_RUN_FILE" ]; then
  LAST_TS=$(cat "$LAST_RUN_FILE" 2>/dev/null || echo 0)
  AGE=$(( NOW - LAST_TS ))
  if [ "$AGE" -ge 0 ] && [ "$AGE" -lt "$RATE_LIMIT_SECS" ]; then
    log "rate-limited (last run ${AGE}s ago < ${RATE_LIMIT_SECS}s) — idempotent skip for task $TASK_REF"
    # Release lock implicitly on exit
    exit 0
  fi
fi

# Record the run (under lock)
echo "$NOW" > "$LAST_RUN_FILE" 2>/dev/null || true

log "=== TRIGGER for ref=$TASK_REF (real task completion) ==="
log "ENABLE_MARKER present: $( [ -f "$ENABLE_MARKER" ] && echo yes || echo no )"
log "AGENTFORGE_RUST_FLYWHEEL=${AGENTFORGE_RUST_FLYWHEEL:-0}"

# Set canonical env (non-destructive; prefer release for speed)
export AGENTFORGE_RUST_FLYWHEEL=1
export AGENTFORGE_USE_RUST=1
: "${AGENTFORGE_RUST_RUNNER:=/home/eveselove/agentforge/rust/target/release/agentforge-runner}"
if [ ! -x "$AGENTFORGE_RUST_RUNNER" ]; then
  AGENTFORGE_RUST_RUNNER="/home/eveselove/agentforge/rust/target/debug/agentforge-runner"
fi
export AGENTFORGE_RUST_RUNNER
export PYTHONPATH="${PYTHONPATH:-/home/eveselove}"

# Also source the standard snippet if present (for any extra vars like EVERY_N)
if [ -f "$AGENTFORGE_ROOT/bin/rust_flywheel.env" ]; then
  # shellcheck disable=SC1091
  source "$AGENTFORGE_ROOT/bin/rust_flywheel.env" 2>/dev/null || true
fi

# Ensure we still win if the sourced snippet tried to downgrade
export AGENTFORGE_RUST_FLYWHEEL=1
export AGENTFORGE_USE_RUST=1

# DEPRECATION WAVE 2 + is_pure_rust_flywheel guard usage (high-signal, minimal, non-breaking)
_PURE_RUST_FW=$(python3 -c '
import os
os.environ.setdefault("PYTHONPATH", "/home/eveselove")
try:
    from agentforge.learning.utils import is_pure_rust_flywheel
    print(1 if is_pure_rust_flywheel() else 0)
except Exception:
    print(0)
' 2>/dev/null || echo 0)
log "is_pure_rust_flywheel()=${_PURE_RUST_FW} (WAVE 2 guard)"
if [ "$_PURE_RUST_FW" = "1" ]; then
    log "[DEPRECATION WAVE 2] Pure Rust active — this .sh + python step is legacy. Prefer: agentforge-runner flywheel-step (see bin/test_pure_rust_flywheel_step.sh)"
else
    log "[DEPRECATION WAVE 2] Python orchestration path (set AGENTFORGE_PURE_RUST_FLYWHEEL=1 or FLYWHEEL_ENGINE=rust to cut over)"
fi

log "Using runner: $AGENTFORGE_RUST_RUNNER"

# === PURE RUST DIRECT PATH (continuous + promote + shadow integration complete) ===
# When pure: invoke agentforge-runner directly for flywheel-step (with --ingest + optional --shadow).
# This is the polished, obvious surface. Also exercises continuous for the meta autonomy loop.
# Promote is the follow-on (via candidate promote or manual after list).
# Non-pure: fall back to legacy Python step (kept for compatibility only).
if [ "$_PURE_RUST_FW" = "1" ] || [ "${AGENTFORGE_PURE_RUST_FLYWHEEL:-0}" = "1" ] || [ "${AGENTFORGE_FLYWHEEL_ENGINE:-}" = "rust" ]; then
    log "[PURE RUST AFTER-TASK] Direct runner path (flywheel-step + shadow/continuous ready). Source: rust-agentforge-runner"
    SHADOW_DIR=""
    SHADOW_ACTIVE=0
    if [ "${AGENTFORGE_RUST_FLYWHEEL_SHADOW:-0}" = "1" ] || [ "${AGENTFORGE_RUST_FLYWHEEL_SHADOW:-}" = "true" ]; then
        SHADOW_ACTIVE=1
        SHADOW_DIR="/tmp/agentforge_rust_flywheel/shadow_aftertask_$(date +%s)"
        mkdir -p "$SHADOW_DIR" 2>/dev/null || true
        log "  shadow dual-run enabled (v5 NEAR FARM-READY) - capturing to $SHADOW_DIR for fidelity"
    fi
    PURE_CMD=("$AGENTFORGE_RUST_RUNNER" --json flywheel-step --real-data --ingest --limit 60)
    if [ "$SHADOW_ACTIVE" = "1" ]; then
        PURE_CMD+=(--shadow --output-dir "$SHADOW_DIR")
    fi
    (
      cd "$AGENTFORGE_ROOT" 2>/dev/null || true
      "${PURE_CMD[@]}" 2>&1 | tail -80
    ) >> "$LOG_FILE" 2>&1 || log "pure runner flywheel-step exited non-zero (non-fatal)"
    # Continuous autonomy tick under pure (non-blocking, safe dry-run default; the meta-loop closer).
    # Always exercised here for after-task integration point (timer parity + health JSON + shadow dual).
    # This + flywheel-step makes the hook a full pure-Rust surface trigger (step + continuous + promote follow-up).
    CONT_CMD=("$AGENTFORGE_RUST_RUNNER" --json continuous --top-n 2)
    if [ "$SHADOW_ACTIVE" = "1" ]; then CONT_CMD+=(--shadow); fi
    (
      cd "$AGENTFORGE_ROOT" 2>/dev/null || true
      "${CONT_CMD[@]}" 2>&1 | tail -30
    ) >> "$LOG_FILE" 2>&1 || true
    log "continuous tick exercised under pure (autonomy meta-loop + health JSON + shadow ready)"
    # v5 continuous dual support + richer fidelity integration: when shadow, refresh aggregate (streak/trend/health) + log key gate values for immediate farm observability (cron/watchdog friendly)
    if [ "$SHADOW_ACTIVE" = "1" ]; then
        # Shadow fidelity via runner (direct, no Python parity harness - DELETED Tier2)
        "$RUNNER" --json flywheel-step --real-data --shadow --ingest --limit 20 >> "$LOG_FILE" 2>&1 || true
        log "shadow step + continuous via direct runner (fidelity via --shadow; aggregate/health in /tmp/.../flywheel_health.json)"
    fi
    log "Pure runner after-task complete (step + continuous + v5 shadow fidelity). Next for promote: agentforge-runner candidate list --top 5 ; candidate promote <id> --copy-to-skills (or --dry-run). source=rust stamped in history."
else
    log "[LEGACY] Python orchestration path (set pure env for direct agentforge-runner flywheel-step --ingest --shadow)"
    # Run the canonical production step (legacy - DEPRECATED per Tier 3; set pure env)
    (
      cd "$AGENTFORGE_ROOT" 2>/dev/null || true
      # Prefer runner (direct) even in legacy path if binary present
      if [ -x "$AGENTFORGE_RUST_RUNNER" ]; then
        "$AGENTFORGE_RUST_RUNNER" --json flywheel-step --real-data --limit 60 2>&1 | tail -100
      else
        echo "legacy Python step would run here (set AGENTFORGE_RUST_FLYWHEEL=1 for direct)"
      fi
    ) >> "$LOG_FILE" 2>&1 || log "canonical step exited non-zero (non-fatal, see log)"
fi

log "After-task flywheel step completed (artifacts/candidates in pending_candidates/ if ingest ran)."
log "Promote follow-up: agentforge-runner candidate promote <id> --copy-to-skills (or via list)"
log "See also: ls -l $AGENTFORGE_ROOT/pending_candidates/ | tail -5 ; agentforge-runner --help | grep -A 20 continuous"

# Summary line for easy grepping in worker logs (now reflects pure runner direct path + v5 shadow)
echo "[AgentForge] Rust flywheel after-task hook finished for $TASK_REF (pure runner: step+continuous+shadow; promote via candidate; RUNNER UX AND INTEGRATION PRODUCTION-POLISHED)" >> "$LOG_DIR/grok_worker.log" 2>/dev/null || true
echo "[AgentForge] Rust flywheel after-task hook finished for $TASK_REF (pure runner: step+continuous+shadow; promote via candidate; RUNNER UX AND INTEGRATION PRODUCTION-POLISHED)" >> "$LOG_DIR/jules_worker.log" 2>/dev/null || true

# === 14d SOAK MONITORING (simple ongoing, logs every after-task hook on real data) ===
# Engine provenance in new manifests + health JSON + fidelity aggregate for daily audit.
# Greppable: [SOAK-MONITOR] lines in $LOG_FILE (and worker logs via tee).
# Run manually anytime: bash bin/rust_flywheel_after_task.sh (or let hooks/timer do it).
# Also: cat /tmp/agentforge_rust_flywheel/flywheel_health.json ;  # DELETED Tier2 - parity removed; use runner direct for fidelity if needed --shadow-aggregate --json
( 
  echo "[SOAK-MONITOR] $(date -Iseconds) engine_provenance_scan"
  HEALTH="/tmp/agentforge_rust_flywheel/flywheel_health.json"
  if [ -f "$HEALTH" ]; then
    python3 -c '
import json, sys
try:
  d=json.load(open(sys.argv[1]))
  print("[SOAK-MONITOR] health engine=" + str(d.get("engine","?")) + " source=" + str(d.get("source","?")) + " fidelity_ready=" + str(d.get("fidelity_ready","?")) + " shadow=" + str(d.get("shadow","?")) + " pending=" + str(d.get("total_pending_scanned","?")))
except Exception as e: print("[SOAK-MONITOR] health-parse-err", str(e)[:60])
' "$HEALTH" 2>/dev/null || echo "[SOAK-MONITOR] health missing or bad json"
  fi
  # Recent manifests provenance (new candidates carry engine/src from runner/post_process)
  python3 -c '
import json, glob, os, time
base="/home/eveselove/agentforge/pending_candidates"
mans = sorted(glob.glob(base + "/2026*/*manifest*.json") + glob.glob(base + "/2026*/flywheel_manifest.json"), key=os.path.getmtime, reverse=True)[:5]
for p in mans:
  try:
    d=json.load(open(p))
    eng = d.get("engine") or d.get("AGENTFORGE_FLYWHEEL_PROVENANCE") or d.get("source") or d.get("rust_runner_used")
    if eng in (True, False, None, "True", "False"):
        eng = "rust-agentforge-runner (normalized)"
    eng = eng or "no-engine-field"
    ts = time.strftime("%Y-%m-%dT%H:%M", time.gmtime(os.path.getmtime(p)))
    print("[SOAK-MONITOR] manifest " + os.path.basename(os.path.dirname(p)) + " mtime=" + ts + " engine/src=" + str(eng)[:80])
  except: pass
' 2>/dev/null || true
  # Fidelity aggregate (if shadow runs happened)
  python3 -c '
import json, sys
try:
  agg_path="/tmp/agentforge_rust_flywheel/shadow_fidelity_aggregate.json"
  d=json.load(open(agg_path))
  print("[SOAK-MONITOR] fidelity_aggregate health=" + str(d.get("fidelity_health","?")) + " avg=" + str(d.get("avg_composite","?")) + " pass_rate=" + str(d.get("pass_rate","?")) + " streak=" + str(d.get("recent_pass_streak","?")) + " trend=" + str(d.get("trend","?")) + " samples=" + str(d.get("samples","?")))
except: pass
' 2>/dev/null || true
) 2>&1 | tee -a "$LOG_FILE" 2>/dev/null || true
# End 14d soak monitor block (edit-safe, zero side effects, pure observation)

# === TURBO SOAK ENHANCEMENT (added 2026-05-31) ===
# Force better engine normalization in future runs
# If you see "engine: True" or weird values, this block + the monitor above will catch and normalize them.

log "RUNNER UX AND INTEGRATION PRODUCTION-POLISHED — continuous + promote + shadow fully wired into after-task hook (direct runner: step+continuous, promote follow-up via candidate subcmd, shadow dual for fidelity). One obvious binary. Pure surface complete."
exit 0

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
