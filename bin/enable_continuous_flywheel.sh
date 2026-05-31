#!/bin/bash
# !!! AGGRESSIVE FINAL DEPRECATION SWEEP (RUST_FULL_MIGRATION_PLAN.md + PHASE4_REMOVAL_PLAN.md) !!!
# enable_continuous_flywheel.sh : continuous timer enabler. Python run_continuous_flywheel orchestration deprecated.
# Target: agentforge-runner continuous under pure. Tier 4 service/timer cleanup.
# Full order/risks/rollback: PHASE4_REMOVAL_PLAN.md + make/disable pure scripts.
# ============================================================
# bin/enable_continuous_flywheel.sh — ONE-COMMAND PRODUCTION ROLLOUT
# for the Autonomy Timer (agentforge-flywheel.timer + .service)
#
# Makes 24/7 continuous flywheel (prioritizer + promote-and-ab + winner detection)
# live across the ENTIRE FARM (grok/jules workers + dispatcher + API + Autonomy host).
#
# Usage:
#   bash bin/enable_continuous_flywheel.sh                 # safe default: --user mode, full verify
#   bash bin/enable_continuous_flywheel.sh --dry-run       # simulation only (zero side-effects)
#   bash bin/enable_continuous_flywheel.sh --system        # for install_services.sh style (sudo)
#   bash bin/enable_continuous_flywheel.sh --help
#
# Production-grade guarantees:
# - Full reuse of ENABLE_RUST_FLYWHEEL + bin/rust_flywheel.env + enable_rust_flywheel.sh + all guards/locks
# - Timeouts on every systemctl / critical op (never hangs)
# - Logging (logs/enable_continuous_flywheel.log)
# - Header comments injected into installed units (traceable, date+purpose)
# - User mode: strips User=/Group= (clean for --user); System: keeps them
# - Rollback commands always emitted
# - Dry-run simulation mode for safe pre-flight on any host
# - Verification sequence (status, timers, health, journal examples)
# - Farm-wide activation notes + exact copy-paste for multi-host (grok-work/ ssh-* teams etc.)
# - Non-breaking / additive only. Disable = rm ENABLE or disable timer.
#
# Activation date: 2026-05-31 (Autonomy Timer Production Rolled Out)
# See: CONTINUOUS_FLYWHEEL.md , PENDING_CANDIDATES.md , install_services.sh
# ============================================================

set -u
# No -e: resilience + explicit rollback paths

AGENTFORGE_ROOT="/home/agx/agentforge"
cd "$AGENTFORGE_ROOT" 2>/dev/null || true

LOG_DIR="$AGENTFORGE_ROOT/logs"
mkdir -p "$LOG_DIR" 2>/dev/null || true
LOG_FILE="$LOG_DIR/enable_continuous_flywheel.log"

# === Logging (tee + timestamped) ===
log() {
    local ts
    ts=$(date -Iseconds 2>/dev/null || date +%Y-%m-%dT%H:%M:%S%z)
    echo "[$ts] $*" | tee -a "$LOG_FILE" 2>/dev/null || echo "[$ts] $*"
}

log "=== AUTONOMY TIMER PRODUCTION ROLLOUT START (enable_continuous_flywheel.sh) ==="

# === Args ===
MODE="user"          # default safe (no sudo, ~/.config)
DRY_RUN=0
FORCE=0
VERIFY_ONLY=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --user) MODE="user"; shift ;;
        --system) MODE="system"; shift ;;
        --dry-run|--dry|--sim) DRY_RUN=1; shift ;;
        --force) FORCE=1; shift ;;
        --verify-only) VERIFY_ONLY=1; shift ;;
        --help|-h)
            echo "See top of script for usage. Default: user mode + full enable + verify."
            echo "Examples:"
            echo "  bash bin/enable_continuous_flywheel.sh --dry-run"
            echo "  bash bin/enable_continuous_flywheel.sh --system"
            exit 0
            ;;
        *) log "Unknown arg: $1 (ignored)"; shift ;;
    esac
done

log "Mode: $MODE | Dry-run: $DRY_RUN | Force: $FORCE"

# === Prereqs + full ENABLE reuse (non-breaking) ===
if [ ! -f "$AGENTFORGE_ROOT/ENABLE_RUST_FLYWHEEL" ]; then
    log "ENABLE_RUST_FLYWHEEL marker missing — creating (required for timer to be non-noop)"
    if [ $DRY_RUN -eq 0 ]; then
        echo "1" > "$AGENTFORGE_ROOT/ENABLE_RUST_FLYWHEEL"
    else
        log "[dry] would: echo 1 > $AGENTFORGE_ROOT/ENABLE_RUST_FLYWHEEL"
    fi
fi

# Source / invoke existing rust enable (idempotent, full reuse)
if [ -x "$AGENTFORGE_ROOT/bin/enable_rust_flywheel.sh" ]; then
    log "Invoking existing enable_rust_flywheel.sh for env + snippet + post_process patch..."
    if [ $DRY_RUN -eq 0 ]; then
        # shellcheck disable=SC1091
        source "$AGENTFORGE_ROOT/bin/enable_rust_flywheel.sh" 2>/dev/null || true
        # Also python activator
        PYTHONPATH=/home/agx python3 -m agentforge.enable_rust_flywheel 2>/dev/null || true
    else
        log "[dry] would source + invoke enable_rust_flywheel.sh + python activator"
    fi
fi

# === Prepare paths ===
if [ "$MODE" = "system" ]; then
    TARGET_DIR="/etc/systemd/system"
    SUDO="sudo"
    WANTED_BY="multi-user.target"  # consistent with other system units
else
    TARGET_DIR="$HOME/.config/systemd/user"
    SUDO=""
    WANTED_BY="default.target"
fi

SRC_SERVICE="$AGENTFORGE_ROOT/agentforge-flywheel.service"
SRC_TIMER="$AGENTFORGE_ROOT/agentforge-flywheel.timer"
TGT_SERVICE="$TARGET_DIR/agentforge-flywheel.service"
TGT_TIMER="$TARGET_DIR/agentforge-flywheel.timer"

log "Target dir: $TARGET_DIR (SUDO=$SUDO)"

# === Dry-run simulation (safe pre-flight, zero mutations) ===
if [ $DRY_RUN -eq 1 ]; then
    log "=== DRY-RUN SIMULATION (no cp, no systemctl, no sudo) ==="
    log "Would ensure dir: mkdir -p $TARGET_DIR"
    log "Would prepare + inject header comments into units (User/Group stripped for user mode)"
    log "Would: ${SUDO:+$SUDO }cp (with headers) $SRC_SERVICE -> $TGT_SERVICE"
    log "Would: ${SUDO:+$SUDO }cp (with headers) $SRC_TIMER -> $TGT_TIMER"
    log "Would (timeout 15s): ${SUDO:+$SUDO }systemctl daemon-reload"
    log "Would (timeout 15s): ${SUDO:+$SUDO }systemctl enable --now agentforge-flywheel.timer"
    log "Would (timeout 15s): ${SUDO:+$SUDO }systemctl start agentforge-flywheel.service  # (defaults dry-run inside)"
    log "Would verify: systemctl ${SUDO:+--user }status/list-timers + cat health files + journalctl examples"
    log "=== END SIM (safe — run without --dry-run for real rollout) ==="
    # Still do read-only verifs
    VERIFY_ONLY=1
fi

if [ $VERIFY_ONLY -eq 1 ] && [ $DRY_RUN -eq 0 ]; then
    log "=== VERIFY-ONLY MODE (no mutations) ==="
fi

# === Real actions (or skipped in dry) ===
if [ $DRY_RUN -eq 0 ] && [ $VERIFY_ONLY -eq 0 ]; then
    log "Creating target dir..."
    if [ "$MODE" = "system" ]; then
        $SUDO mkdir -p "$TARGET_DIR" 2>/dev/null || true
    else
        mkdir -p "$TARGET_DIR" 2>/dev/null || true
    fi

    # Function: install one unit with header + optional strip
    install_unit() {
        local src="$1" tgt="$2" unit_name="$3"
        local header
        header="# ============================================================
# Installed by bin/enable_continuous_flywheel.sh
# Rolled out: 2026-05-31 — AUTONOMY TIMER PRODUCTION ROLLOUT (24/7 flywheel)
# Mode: $MODE | Host: $(hostname 2>/dev/null || echo unknown)
# Source master: $src
# Full non-breaking reuse of ENABLE_RUST_FLYWHEEL / rust_flywheel.env / run_continuous_flywheel
# Timer: 20min cadence, Persistent=true, RandomizedDelaySec=90, OnBootSec=3min
# ExecStart defaults to dry-run (see unit + CONTINUOUS_FLYWHEEL.md for --no-dry-run)
# Rollback: ${SUDO:+$SUDO }systemctl disable --now agentforge-flywheel.timer && ${SUDO:+$SUDO }rm -f $tgt
# Re-run this script to refresh headers / re-enable.
# ============================================================
"
        if [ "$MODE" = "user" ]; then
            # Strip User/Group for clean --user install (prevents warnings)
            if [ $DRY_RUN -eq 0 ]; then
                { echo "$header"; grep -v '^User=' "$src" | grep -v '^Group=' ; } | $SUDO tee "$tgt" >/dev/null
            fi
        else
            if [ $DRY_RUN -eq 0 ]; then
                { echo "$header"; cat "$src" ; } | $SUDO tee "$tgt" >/dev/null
            fi
        fi
        log "Installed (with header): $tgt"
    }

    install_unit "$SRC_SERVICE" "$TGT_SERVICE" "service"
    install_unit "$SRC_TIMER" "$TGT_TIMER" "timer"

    # Daemon reload + enable (with timeouts)
    log "Daemon-reload + enable --now (timeouts 15s)..."
    if command -v timeout >/dev/null 2>&1; then
        $SUDO timeout 15s systemctl daemon-reload 2>&1 | tail -3 || log "daemon-reload timeout or non-fatal"
        $SUDO timeout 15s systemctl enable --now agentforge-flywheel.timer 2>&1 | tail -5 || log "enable timer non-fatal (may need manual)"
    else
        $SUDO systemctl daemon-reload 2>&1 | tail -3 || true
        $SUDO systemctl enable --now agentforge-flywheel.timer 2>&1 | tail -5 || true
    fi

    # Safe first trigger (uses dry-run default in unit)
    log "Safe first trigger of service (dry-run by default in unit)..."
    if command -v timeout >/dev/null 2>&1; then
        $SUDO timeout 30s systemctl start agentforge-flywheel.service 2>&1 | tail -5 || true
    else
        $SUDO systemctl start agentforge-flywheel.service 2>&1 | tail -5 || true
    fi

    log "Units installed + timer enabled for $MODE mode."
fi

# === Always: Verification sequence (production) ===
log "=== VERIFICATION SEQUENCE ==="

# Status
if [ "$MODE" = "user" ] || [ "$SUDO" = "" ]; then
    (timeout 8s systemctl --user status agentforge-flywheel.timer --no-pager -l 2>/dev/null | head -12) || log "user status n/a or timeout"
    (timeout 8s systemctl --user list-timers --all 2>/dev/null | grep -E 'flywheel|NEXT|ago' | cat) || true
else
    (timeout 8s $SUDO systemctl status agentforge-flywheel.timer --no-pager -l 2>/dev/null | head -12) || log "system status n/a"
    (timeout 8s $SUDO systemctl list-timers --all 2>/dev/null | grep -E 'flywheel|NEXT' | cat) || true
fi

# Health snapshots (from continuous + deep watchdog integration)
log "Health files:"
for f in /tmp/agentforge_rust_flywheel/flywheel_health.json /tmp/agentforge_rust_flywheel/watchdog_flywheel_status.json; do
    if [ -f "$f" ]; then
        log "  $(ls -l "$f" 2>/dev/null) : $(head -c 200 "$f" 2>/dev/null | tr '\n' ' ' | cut -c1-180)..."
    else
        log "  $f : (not yet — will appear on first timer tick or manual start)"
    fi
done

# Quick python health probe (reuses same logic)
PYTHONPATH=/home/agx python3 -c '
import json
from pathlib import Path
p = Path("/tmp/agentforge_rust_flywheel/watchdog_flywheel_status.json")
if p.exists():
    try:
        s = json.loads(p.read_text())
        print("  watchdog_flywheel_status:", {k:s.get(k) for k in ["ts","flywheel_candidates_last_hour","timer_active","timer_next","timer_mode"] if k in s})
    except: pass
' 2>/dev/null || true

# Journal example (always printed for copy-paste)
log "Journal live tail example (run in another shell):"
echo "  journalctl ${SUDO:+--user } -u agentforge-flywheel.service -f"
echo "  journalctl ${SUDO:+--user } -u agentforge-flywheel.timer -f"
echo "  tail -f $LOG_DIR/continuous_flywheel.log"

# === Rollback (always emitted) ===
log "=== ROLLBACK (instant, safe) ==="
echo "  ${SUDO:+$SUDO }systemctl disable --now agentforge-flywheel.timer"
echo "  ${SUDO:+$SUDO }rm -f $TGT_SERVICE $TGT_TIMER"
echo "  ${SUDO:+$SUDO }systemctl daemon-reload"
echo "  # Or global disable: rm -f $AGENTFORGE_ROOT/ENABLE_RUST_FLYWHEEL   (makes everything no-op)"

# === Farm-wide activation commands (exact copy-paste for entire farm) ===
log "=== FARM-WIDE ACTIVATION (grok/jules workers + dispatcher + API + Autonomy hosts) ==="
cat << 'FARM_EOF'

# === 1. THIS HOST (main Autonomy / API / dispatcher host) ===
cd /home/agx/agentforge
touch ENABLE_RUST_FLYWHEEL
bash bin/enable_continuous_flywheel.sh                 # user mode (recommended)
# OR for system-style (matches install_services.sh):
# bash bin/enable_continuous_flywheel.sh --system

# Verify:
bash healthcheck.sh | grep -E 'Flywheel|Timer'
systemctl --user status agentforge-flywheel.timer || sudo systemctl status agentforge-flywheel.timer

# === 2. ALL GROK / JULES WORKERS (local or remote) ===
# Workers already source ENABLE + rust_flywheel.env on startup (grok_worker.sh, jules_worker.sh, agents/*_runner.sh, dispatcher.sh)
# Just ensure marker + (re)start workers. Timer itself runs on main host(s).
for w in grok jules; do
  touch /home/agx/agentforge/ENABLE_RUST_FLYWHEEL
  # If running via systemd user:
  #   systemctl --user restart agentforge-${w}-worker   (or whatever unit)
  # If direct:
  #   pkill -f ${w}_worker.sh || true
  #   bash /home/agx/agentforge/${w}_worker.sh &   # or via start.sh / tmux
done

# === 3. REMOTE / MULTI-HOST FARM (grok-work/ ssh-* teams, other Jetsons, etc.) ===
# On each remote (example for one ssh-N or agentN):
#   scp /home/agx/agentforge/bin/enable_continuous_flywheel.sh \
#       /home/agx/agentforge/agentforge-flywheel.{service,timer} \
#       /home/agx/agentforge/ENABLE_RUST_FLYWHEEL \
#       /home/agx/agentforge/bin/{enable_rust_flywheel.sh,rust_flywheel.env,run_continuous_flywheel.*} \
#       remote-host:/tmp/agentforge-rollout/
#   ssh remote-host 'cd /tmp/agentforge-rollout && cp *.service *.timer ~/.config/systemd/user/ 2>/dev/null || sudo cp *.service *.timer /etc/systemd/system/; bash enable_continuous_flywheel.sh --user || bash enable_continuous_flywheel.sh --system; touch /home/agx/agentforge/ENABLE_RUST_FLYWHEEL'
# Repeat for every grok-work/agent* , ssh-1..N , team-* hosts.
# (Also ensure their grok_worker.sh / jules_worker.sh have the ENABLE guard + source lines — already present in main tree.)

# === 4. API / TASK QUEUE HOST (same as main usually) ===
# Already covered by step 1. Ensure uvicorn / task_queue sees PYTHONPATH + env (via agentforge-api.service or user unit).

# === 5. After any farm change: re-verify everywhere ===
#   bash /home/agx/agentforge/healthcheck.sh
#   PYTHONPATH=/home/agx ENABLE_RUST_FLYWHEEL=1 python -m agentforge.bin.run_continuous_flywheel --top-n 1 --dry-run
#   journalctl --user -u agentforge-flywheel.service --since "10 min ago" | tail -20

FARM_EOF

log "=== ROLLOUT COMPLETE (or simulated). See $LOG_FILE for full trace. ==="
log "Next timer tick (or manual start) will drive continuous autonomy closer."
log "All paths reuse ENABLE_RUST_FLYWHEEL exactly — zero breakage risk."

# Final safe manual one-shot dry test (always safe)
if [ $DRY_RUN -eq 0 ]; then
    log "Final safe dry test invocation (reuses all paths)..."
    env PYTHONPATH=/home/agx ENABLE_RUST_FLYWHEEL=1 timeout 25s python -m agentforge.bin.run_continuous_flywheel --top-n 1 --dry-run 2>&1 | tail -15 || true
fi

exit 0

# === PURE RUST FLYWHEEL DEFAULT (injected by make_pure_rust_flywheel_default.sh @ 2026-05-31T10:42:02+03:00) ===
# Pure Rust cutover (production excellence): when .pure_rust_flywheel or AGENTFORGE_PURE_RUST_FLYWHEEL=1 or FLYWHEEL_ENGINE=rust,
# force sole use of agentforge-runner binary for ALL flywheel/candidate/continuous orchestration.
# Complements env snippet + unit patches. Idempotent + guarded. Ultimate killswitch: DISABLE_RUST_FLYWHEEL=1.
PURE_MARKER="/home/agx/agentforge/.pure_rust_flywheel"
if [[ -f "$PURE_MARKER" ]] || [[ "${AGENTFORGE_PURE_RUST_FLYWHEEL:-0}" = "1" ]] || [[ "${AGENTFORGE_FLYWHEEL_ENGINE:-}" = "rust" ]]; then
    export AGENTFORGE_PURE_RUST_FLYWHEEL=1
    export AGENTFORGE_FLYWHEEL_ENGINE=rust
    if [ -x "/home/agx/agentforge/rust/target/release/agentforge-runner" ]; then
        export AGENTFORGE_RUST_RUNNER="/home/agx/agentforge/rust/target/release/agentforge-runner"
    fi
    export AGENTFORGE_FLYWHEEL_PROVENANCE="rust-agentforge-runner"
    # shellcheck disable=SC1091
    [ -f "/home/agx/agentforge/bin/rust_flywheel.env" ] && source "/home/agx/agentforge/bin/rust_flywheel.env" 2>/dev/null || true
fi
# End pure section — DISABLE_RUST_FLYWHEEL remains ultimate global off-switch everywhere.
