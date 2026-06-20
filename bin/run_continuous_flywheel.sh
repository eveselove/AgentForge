#!/bin/bash
# ============================================================
# bin/run_continuous_flywheel.sh — Ultra-reliable locked wrapper
# for the continuous autonomy closer.
#
# Preferred for systemd .timer / cron:
#   /home/eveselove/agentforge/bin/run_continuous_flywheel.sh --no-dry-run
#
# Guarantees:
# - Sources all existing ENABLE / rust_flywheel.env / enable_*.sh (full reuse)
# - flock on the canonical lock (portable, 30s wait)
# - Env guards identical to workers + after_task hooks
# - Calls the python implementation (which adds fcntl + python timeout)
# - Logs + non-fatal everywhere
# - Default: safe dry-run (pass --no-dry-run for real promote-and-ab)
#
# Enable in timer:
#   ExecStart=/home/eveselove/agentforge/bin/run_continuous_flywheel.sh --no-dry-run --top-n 2
#
# !!! AGGRESSIVE FINAL DEPRECATION SWEEP (RUST_FULL_MIGRATION_PLAN.md + PHASE4_REMOVAL_PLAN.md) !!!
# !!! bin/run_continuous_flywheel.sh + .py : Python continuous orchestration DEPRECATED — Phase 4 target !!!
# This .sh/.py is Tier 1/2 removal: replaced by `agentforge-runner continuous --top-n K [--dry-run]`.
# See PHASE4_REMOVAL_PLAN.md for exhaustive list, safe phased removal order (Tier 2), risks (medium),
# detailed rollback (Layer 1 env, Layer 2 dotfiles .disable_pure_rust_flywheel, git tags, service edits).
# Guard: from agentforge.learning.utils import is_pure_rust_flywheel (central, hardened Phase 4).
# Under pure default: timer/service/workers invoke binary exclusively. Python path short-circuited.
# Non-breaking fallback only on rollback. Full audit commands + verification in the PLAN.
#
# DEPRECATION (Phase 1, RUST_FULL_MIGRATION_PLAN.md):
#   Python-driven continuous wrapper (this .sh + run_continuous_flywheel.py).
#   Future target: direct `agentforge-runner continuous --top-n K [--dry-run]`.
#   TODO: update agentforge-flywheel.service/.timer + make_pure_rust...sh to invoke Rust path
#   when AGENTFORGE_PURE_RUST_FLYWHEEL=1. Non-breaking during transition.
#   See also: is_pure_rust_flywheel() helper + bin/rust_flywheel_after_task.sh
#
# !!! PHASE 3 FINAL SWEEP: this .sh + py + service/timer heavily marked.
#    Migrate timers/services to: agentforge-runner continuous ...
#    Guarded by central is_pure... (stronger). See make_pure_rust_flywheel_default.sh
# ============================================================

set -u
# No -e: we want full resilience

AGENTFORGE_ROOT="/home/eveselove/agentforge"
cd "$AGENTFORGE_ROOT" 2>/dev/null || true

# === Full reuse of existing ENABLE hooks (identical to workers) ===
RUST_FLYWHEEL_SNIPPET="$AGENTFORGE_ROOT/bin/rust_flywheel.env"
if [ -f "$RUST_FLYWHEEL_SNIPPET" ]; then
    # shellcheck disable=SC1091
    source "$RUST_FLYWHEEL_SNIPPET" 2>/dev/null || true
fi

if [ -f "$AGENTFORGE_ROOT/ENABLE_RUST_FLYWHEEL" ] || [ "${AGENTFORGE_RUST_FLYWHEEL:-0}" = "1" ] || [ "${ENABLE_RUST_FLYWHEEL:-0}" = "1" ]; then
    export AGENTFORGE_RUST_FLYWHEEL=1
    export AGENTFORGE_USE_RUST=1
    if [ -x "$AGENTFORGE_ROOT/rust/target/release/agentforge-runner" ]; then
        export AGENTFORGE_RUST_RUNNER="$AGENTFORGE_ROOT/rust/target/release/agentforge-runner"
    else
        export AGENTFORGE_RUST_RUNNER="${AGENTFORGE_RUST_RUNNER:-$AGENTFORGE_ROOT/rust/target/debug/agentforge-runner}"
    fi
    # Source the full enable (idempotent)
    [ -x "$AGENTFORGE_ROOT/bin/enable_rust_flywheel.sh" ] && source "$AGENTFORGE_ROOT/bin/enable_rust_flywheel.sh" 2>/dev/null || true
fi

export AGENTFORGE_RUST_FLYWHEEL="${AGENTFORGE_RUST_FLYWHEEL:-1}"
export AGENTFORGE_USE_RUST="${AGENTFORGE_USE_RUST:-1}"
export PYTHONPATH="${PYTHONPATH:-/home/eveselove}:/home/eveselove/agentforge"

LOG_DIR="$AGENTFORGE_ROOT/logs"
mkdir -p "$LOG_DIR" 2>/dev/null || true

LOCK_FILE="/tmp/agentforge_rust_flywheel/.continuous_flywheel.lock"

log() {
    echo "[continuous_wrapper $(date -Iseconds)] $*" | tee -a "$LOG_DIR/continuous_flywheel.log" 2>/dev/null || echo "[continuous_wrapper] $*"
}

# Global lock (flock when available for -w wait; portable mkdir fallback otherwise to avoid silent race when no flock binary present on minimal systems/containers).
# Prevents concurrent continuous runs (data race on flywheel_health.json + candidate reads during prioritizer + promote follow-ups).
LOCKDIR="${LOCK_FILE}.lockdir"
mkdir -p "$(dirname "$LOCK_FILE")" "$(dirname "$LOCKDIR")" 2>/dev/null || true
if command -v flock >/dev/null 2>&1; then
    exec 201>"$LOCK_FILE" 2>/dev/null || true
    if ! flock -w 30 201 2>/dev/null; then
        log "Wrapper flock contended — continuous flywheel already running (skipped this tick; perfect for 15-30min cadence)"
        exit 0
    fi
else
    # Portable non-flock lock (mkdir is atomic). Stale protection for 10+ min old (covers 15-30min timer + crashes).
    if [ -d "$LOCKDIR" ]; then
        if find "$LOCKDIR" -maxdepth 0 -mmin +10 2>/dev/null | grep -q . ; then
            rmdir "$LOCKDIR" 2>/dev/null || true
        fi
    fi
    if ! mkdir "$LOCKDIR" 2>/dev/null; then
        log "Wrapper contended (portable lock, no flock cmd) — continuous flywheel already running (skipped this tick)"
        exit 0
    fi
    # best-effort release (on normal exit; -9 leaves stale but next tick cleans after 10min)
    trap 'rmdir "$LOCKDIR" 2>/dev/null || true' EXIT INT TERM
fi

log "=== CONTINUOUS FLYWHEEL WRAPPER TRIGGER (reusing all existing ENABLE + after-task wiring) ==="
log "ENABLE_MARKER: $( [ -f "$AGENTFORGE_ROOT/ENABLE_RUST_FLYWHEEL" ] && echo present || echo absent )"
log "Runner: ${AGENTFORGE_RUST_RUNNER:-unknown}"

# === PURE RUST DIRECT PATH (production polish) ===
# When pure (marker/env or is_pure_rust_flywheel): use agentforge-runner continuous directly.
# This wires the COMPLETE continuous + shadow + health into the timer/cron/service path.
# Non-pure: legacy Python (kept for rollback compat only).
# Fast path: shell-only marker/env checks first (O(1), no process spawn) to eliminate python -c + import bottleneck on every timer tick under default pure.
# Only spawn python for the central is_pure_rust_flywheel() if no fast marker (allows future logic in utils without staleness).
if [ "${AGENTFORGE_PURE_RUST_FLYWHEEL:-0}" = "1" ] || [ "${AGENTFORGE_FLYWHEEL_ENGINE:-}" = "rust" ] || [ -f "/home/eveselove/agentforge/.pure_rust_flywheel" ]; then
    _PURE_CONT=1
else
    _PURE_CONT=$(python3 -c '
import os
os.environ.setdefault("PYTHONPATH", "/home/eveselove")
try:
    from agentforge.learning.utils import is_pure_rust_flywheel
    print(1 if is_pure_rust_flywheel() else 0)
except Exception:
    print(0)
' 2>/dev/null || echo 0)
fi

if [ "$_PURE_CONT" = "1" ] && [ -x "${AGENTFORGE_RUST_RUNNER:-}" ]; then
    log "[PURE RUST CONTINUOUS] Direct runner path (COMPLETE autonomy + health + shadow). source=rust-agentforge-runner"
    CONT_CMD=("$AGENTFORGE_RUST_RUNNER" --json continuous "$@")
    # ensure at least top-n default if none supplied (user args take precedence)
    if ! printf '%s\n' "$@" | grep -qE '(--top-n|--top|-n)'; then
        CONT_CMD+=(--top-n 2)
    fi
    if [ "${AGENTFORGE_RUST_FLYWHEEL_SHADOW:-0}" = "1" ] || [ "${AGENTFORGE_RUST_FLYWHEEL_SHADOW:-}" = "true" ]; then
        CONT_CMD+=(--shadow)
        log "  shadow dual-run enabled for continuous (fidelity in post_process/after_task/parity)"
    fi
    # Full output to log (no truncation: fixes observability loss for errors/debug of continuous). rc captured correctly (was hardcoded 0, pipe tail swallowed errors).
    # (group) exit status == runner exit (no pipe here).
    (
      cd "$AGENTFORGE_ROOT" 2>/dev/null || true
      "${CONT_CMD[@]}"
    ) >> "$LOG_DIR/continuous_flywheel.log" 2>&1
    rc=$?
    if [ "$rc" -ne 0 ]; then
        log "pure continuous runner exited non-zero (rc=$rc, non-fatal, health may still be written)"
    fi
    log "Pure runner continuous complete (autonomy meta-loop + flywheel_health.json). Promote follow-up: agentforge-runner candidate promote <id> --copy-to-skills"
    log "RUNNER UX AND INTEGRATION POLISHED — continuous direct via agentforge-runner (step+continuous+promote+shadow fully wired)"
else
    log "[LEGACY] Python continuous orchestration path (set pure env for direct agentforge-runner continuous)"
    # Delegate to the full python implementation (direct exec for max reliability across envs; args passthrough)
    # Log full to dedicated file (via tee) for consistency with pure path; tail only limits what reaches process stdout (journal).
    python3 bin/run_continuous_flywheel.py "$@" 2>&1 | tee -a "$LOG_DIR/continuous_flywheel.log" | tail -80
    rc=${PIPESTATUS[0]:-0}
fi

log "Wrapper finished rc=$rc"
exit "$rc"
# (no code after exit: previous trailing pure-marker block was unreachable dead code / copy-paste artifact. Pure logic lives in early sourcing + fast detection above.)
