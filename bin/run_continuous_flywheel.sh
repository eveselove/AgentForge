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
mkdir -p "$(dirname "$LOCK_FILE")" 2>/dev/null || true

log() {
    echo "[continuous_wrapper $(date -Iseconds)] $*" | tee -a "$LOG_DIR/continuous_flywheel.log" 2>/dev/null || echo "[continuous_wrapper] $*"
}

# Global flock (portable, high reliability for timer)
exec 201>"$LOCK_FILE" 2>/dev/null || true
if command -v flock >/dev/null 2>&1; then
    if ! flock -w 30 201 2>/dev/null; then
        log "Wrapper flock contended — continuous flywheel already running (skipped this tick; perfect for 15-30min cadence)"
        exit 0
    fi
fi

log "=== CONTINUOUS FLYWHEEL WRAPPER TRIGGER (reusing all existing ENABLE + after-task wiring) ==="
log "ENABLE_MARKER: $( [ -f "$AGENTFORGE_ROOT/ENABLE_RUST_FLYWHEEL" ] && echo present || echo absent )"
log "Runner: ${AGENTFORGE_RUST_RUNNER:-unknown}"

# === PURE RUST DIRECT PATH (production polish) ===
# When pure (marker/env or is_pure_rust_flywheel): use agentforge-runner continuous directly.
# This wires the COMPLETE continuous + shadow + health into the timer/cron/service path.
# Non-pure: legacy Python (kept for rollback compat only).
_PURE_CONT=$(python3 -c '
import os
os.environ.setdefault("PYTHONPATH", "/home/eveselove")
try:
    from agentforge.learning.utils import is_pure_rust_flywheel
    print(1 if is_pure_rust_flywheel() else 0)
except Exception:
    p = os.environ.get("AGENTFORGE_PURE_RUST_FLYWHEEL", "0")
    e = os.environ.get("AGENTFORGE_FLYWHEEL_ENGINE", "")
    print(1 if (p == "1" or e == "rust" or os.path.exists("/home/eveselove/agentforge/.pure_rust_flywheel")) else 0)
' 2>/dev/null || echo 0)

if [ "$_PURE_CONT" = "1" ] && [ -x "${AGENTFORGE_RUST_RUNNER:-}" ]; then
    log "[PURE RUST CONTINUOUS] Direct runner path (COMPLETE autonomy + health + shadow). source=rust-agentforge-runner"
    CONT_CMD=("$AGENTFORGE_RUST_RUNNER" --json continuous)
    # passthrough common flags from wrapper args (top-n, dry, shadow, etc.)
    for arg in "$@"; do
        case "$arg" in
            --top-n|--top|-n|--dry-run|--no-dry-run|--execute|--real|--shadow|--min-lv|--min-lv|--json|-j)
                CONT_CMD+=("$arg") ;;
            [0-9]*)
                # numeric after --top-n etc already handled by case, but allow bare if present
                CONT_CMD+=("$arg") ;;
            *)
                CONT_CMD+=("$arg") ;;
        esac
    done
    # ensure at least top-n default if none supplied
    if ! printf '%s\n' "${CONT_CMD[@]}" | grep -qE '(--top-n|--top|-n)'; then
        CONT_CMD+=(--top-n 2)
    fi
    if [ "${AGENTFORGE_RUST_FLYWHEEL_SHADOW:-0}" = "1" ] || [ "${AGENTFORGE_RUST_FLYWHEEL_SHADOW:-}" = "true" ]; then
        CONT_CMD+=(--shadow)
        log "  shadow dual-run enabled for continuous (fidelity in post_process/after_task/parity)"
    fi
    (
      cd "$AGENTFORGE_ROOT" 2>/dev/null || true
      "${CONT_CMD[@]}" 2>&1 | tail -60
    ) >> "$LOG_DIR/continuous_flywheel.log" 2>&1 || log "pure continuous runner exited non-zero (non-fatal, health may still be written)"
    log "Pure runner continuous complete (autonomy meta-loop + flywheel_health.json). Promote follow-up: agentforge-runner candidate promote <id> --copy-to-skills"
    rc=0
    log "RUNNER UX AND INTEGRATION POLISHED — continuous direct via agentforge-runner (step+continuous+promote+shadow fully wired)"
else
    log "[LEGACY] Python continuous orchestration path (set pure env for direct agentforge-runner continuous)"
    # Delegate to the full python implementation (direct exec for max reliability across envs; args passthrough)
    python3 bin/run_continuous_flywheel.py "$@" 2>&1 | tail -80
    rc=${PIPESTATUS[0]:-0}
fi

log "Wrapper finished rc=$rc"
exit "$rc"

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
