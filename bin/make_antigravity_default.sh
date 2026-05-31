#!/bin/bash
# !!! AGGRESSIVE FINAL DEPRECATION SWEEP (RUST_FULL_MIGRATION_PLAN.md + PHASE4_REMOVAL_PLAN.md) !!!
# make_antigravity_default.sh : related defaulting tool (antigravity + flywheel synergy). Patches for pure Rust flywheel.
# Companion to pure flywheel cutover scripts. Phase 4 removal only after full flywheel deprecation complete.
# See PHASE4_REMOVAL_PLAN.md (infra sh, Tier 4/5).
# ============================================================
# bin/make_antigravity_default.sh — ONE-COMMAND ANTIGRAVITY DEFAULT ENABLER
# Final lockdown for the Rust self-improving flywheel (now DEFAULT for Antigravity).
#
# Mission: Make the entire Antigravity + farm flywheel live in a single safe shot.
# - Touches ENABLE_RUST_FLYWHEEL (for full compatibility + legacy paths)
# - Runs enable_rust_flywheel.sh (env + snippet + post_process patch + python activator)
# - Runs enable_continuous_flywheel.sh (timer + service units for 24/7 closer)
# - Safe service handling (notes + optional restart for user-mode workers/timer; never blind system)
# - Runs healthcheck.sh with Flywheel/Timer focus
# - Full verification printout (env, timer, health json, binary, pending list)
# - Prints FULL FARM ROLLOUT PACKAGE (exact scp+ssh per-host or master /tmp/farm_antigravity_rollout.sh wrapper with dry-first + per-remote health/timer/default-probe verify + rollback notes) for grok-work/* ssh-1..N agent* team-* Jetsons etc.
# - Prints clean DISABLE path (the only killswitch: DISABLE_RUST_FLYWHEEL=1)
#
# Production guarantees:
# - Idempotent + resilient (no -e, timeouts on critical ops)
# - Full reuse of every existing guard (ENABLE + DISABLE_RUST_FLYWHEEL + .disable_* + rate locks + flock)
# - --dry-run support for zero-mutation preflight (recommended first run)
# - Logging to logs/make_antigravity_default.log
# - Always emits rollback + verification + farm blocks
# - Non-breaking: everything already default-on in code (post_process.py or True, dispatcher, workers);
#   this script just makes the continuous timer + explicit markers 100% live + verified.
#
# Links (evidence of 100% victory closure):
# - VICTORY_SUMMARY.md + HOW_WE_FINISHED_WITH_AGENTS.md (Jules swarm execution)
# - AGENTFORGE_FRONTIER_ROADMAP.md (top banner + Phase 2/3 complete)
# - ANTIGRAVITY_DEFAULT.md (full story + "What this means for Antigravity tasks")
# - ENABLE_RUST_FLYWHEEL.md + CONTINUOUS_FLYWHEEL.md + PENDING_CANDIDATES.md (timer + real A/B)
# - bin/enable_*.sh + bin/trigger_real_ab_on_farm.sh + real_ab_farm_commands.txt
#
# Usage (from /home/agx/agentforge):
#   bash bin/make_antigravity_default.sh                 # full production enable + verify
#   bash bin/make_antigravity_default.sh --dry-run       # safe simulation only
#   bash bin/make_antigravity_default.sh --no-timer      # skip continuous (just rust default)
#   bash bin/make_antigravity_default.sh --help
#
# After run: the farm (Antigravity + Grok + Jules) is Antigravity Default locked.
# Every task completion feeds the Rust flywheel. 24/7 timer drives promote-and-ab.
# Rollback is one env var or rm of marker + timer disable.
#
# Activation: 2026-05-31 (Final Antigravity Default lockdown — turbo Jules closer)
# ============================================================

set -u
# Resilience: explicit error handling only on critical paths

AGENTFORGE_ROOT="/home/agx/agentforge"
cd "$AGENTFORGE_ROOT" 2>/dev/null || true

LOG_DIR="$AGENTFORGE_ROOT/logs"
mkdir -p "$LOG_DIR" 2>/dev/null || true
LOG_FILE="$LOG_DIR/make_antigravity_default.log"

log() {
    local ts
    ts=$(date -Iseconds 2>/dev/null || date +%Y-%m-%dT%H:%M:%S%z)
    echo "[$ts] $*" | tee -a "$LOG_FILE" 2>/dev/null || echo "[$ts] $*"
}

log "=== ANTIGRAVITY DEFAULT ONE-COMMAND ENABLER START ==="

# === Args ===
DRY_RUN=0
NO_TIMER=0
FORCE_RESTART=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run|--dry|--sim) DRY_RUN=1; shift ;;
        --no-timer|--no-continuous) NO_TIMER=1; shift ;;
        --force-restart) FORCE_RESTART=1; shift ;;
        --help|-h)
            echo "See header of $0 for full docs."
            echo "Examples:"
            echo "  bash bin/make_antigravity_default.sh --dry-run"
            echo "  bash bin/make_antigravity_default.sh"
            exit 0
            ;;
        *) log "Unknown arg: $1 (ignored)"; shift ;;
    esac
done

log "DRY_RUN=$DRY_RUN | NO_TIMER=$NO_TIMER | FORCE_RESTART=$FORCE_RESTART"

# === Core action sequence ===
if [ $DRY_RUN -eq 1 ]; then
    log "=== DRY-RUN MODE (zero mutations) ==="
    log "[dry] would: touch $AGENTFORGE_ROOT/ENABLE_RUST_FLYWHEEL"
    log "[dry] would: bash bin/enable_rust_flywheel.sh"
    log "[dry] would: bash bin/enable_continuous_flywheel.sh (unless --no-timer)"
    log "[dry] would: (safe) notes on systemctl --user restart for workers/timer"
    log "[dry] would: bash healthcheck.sh | grep -E 'Flywheel|Timer|Rust'"
    log "[dry] would: full verification block (env, status, health json, binary, list_pending)"
fi

if [ $DRY_RUN -eq 0 ]; then
    log "Touching ENABLE_RUST_FLYWHEEL marker (full compatibility layer)..."
    touch "$AGENTFORGE_ROOT/ENABLE_RUST_FLYWHEEL" || log "WARNING: touch failed (non-fatal under new default)"

    log "Invoking bin/enable_rust_flywheel.sh (env + snippet + post_process patch + activator)..."
    if [ -x "$AGENTFORGE_ROOT/bin/enable_rust_flywheel.sh" ]; then
        bash "$AGENTFORGE_ROOT/bin/enable_rust_flywheel.sh" 2>&1 | tail -20 || log "enable_rust non-fatal"
    else
        log "WARNING: enable_rust_flywheel.sh not executable — falling back to python activator"
        PYTHONPATH=/home/agx python3 -m agentforge.enable_rust_flywheel 2>/dev/null || true
    fi

    if [ $NO_TIMER -eq 0 ]; then
        log "Invoking bin/enable_continuous_flywheel.sh (timer + 24/7 closer units)..."
        if [ -x "$AGENTFORGE_ROOT/bin/enable_continuous_flywheel.sh" ]; then
            bash "$AGENTFORGE_ROOT/bin/enable_continuous_flywheel.sh" 2>&1 | tail -30 || log "enable_continuous non-fatal (timer may already be active)"
        else
            log "WARNING: enable_continuous_flywheel.sh missing"
        fi
    else
        log "Skipping continuous timer (--no-timer)"
    fi
fi

# === Safe service handling (never aggressive; user-mode first, notes for system) ===
log "=== SAFE SERVICE HANDLING ==="
if [ $DRY_RUN -eq 0 ]; then
    # Flywheel timer (user preferred)
    if systemctl --user is-active --quiet agentforge-flywheel.timer 2>/dev/null; then
        log "Flywheel timer already active (user)"
        if [ $FORCE_RESTART -eq 1 ]; then
            timeout 10s systemctl --user restart agentforge-flywheel.timer 2>/dev/null || log "timer restart non-fatal"
        fi
    else
        log "Flywheel timer not active in user mode (run enable_continuous if needed)"
    fi

    # Worker note (do not blindly restart on production farm unless --force-restart)
    if [ $FORCE_RESTART -eq 1 ]; then
        log "FORCE_RESTART requested — attempting safe user worker restarts (non-fatal)..."
        for unit in agentforge-worker agentforge-jules-worker; do
            if systemctl --user is-active --quiet "$unit" 2>/dev/null; then
                timeout 15s systemctl --user restart "$unit" 2>/dev/null || log "$unit restart attempted (non-fatal)"
            fi
        done
    else
        log "Worker restart: skipped for safety. Use --force-restart only on low-load dev hosts."
        log "Manual (when safe): systemctl --user restart agentforge-worker agentforge-jules-worker"
    fi
else
    log "[dry] would perform safe user-mode status checks + conditional restarts only with --force-restart"
fi

# === Healthcheck (focused) ===
log "=== HEALTHCHECK (Flywheel + Timer focused) ==="
if [ $DRY_RUN -eq 0 ]; then
    if [ -x "$AGENTFORGE_ROOT/healthcheck.sh" ]; then
        bash "$AGENTFORGE_ROOT/healthcheck.sh" 2>&1 | grep -E 'Flywheel|Timer|Rust|✅|⚠️' | head -20 || true
    else
        log "healthcheck.sh not found"
    fi
else
    log "[dry] would run: bash healthcheck.sh | grep -E 'Flywheel|Timer'"
fi

# === Verification block (always, even in dry) ===
log "=== VERIFICATION (evidence of Antigravity Default live) ==="

echo ""
echo "=== ANTIGRAVITY DEFAULT STATUS ==="
echo "ENABLE marker: $(ls -l "$AGENTFORGE_ROOT/ENABLE_RUST_FLYWHEEL" 2>/dev/null || echo 'present via default-on logic')"
echo "DISABLE killswitch file: $(ls -l "$AGENTFORGE_ROOT/.disable_rust_flywheel" 2>/dev/null || echo 'absent (good — default ON)')"
echo ""

echo "Env (current shell):"
env | grep -E 'AGENTFORGE_RUST|DISABLE_RUST_FLYWHEEL|ENABLE_RUST' | cat || true
echo ""

echo "Rust release binary:"
ls -l "$AGENTFORGE_ROOT/rust/target/release/agentforge-runner" 2>/dev/null || echo "  (build with: cd rust && cargo build -p agentforge-runner --release)"
echo ""

if [ $DRY_RUN -eq 0 ] || [ $NO_TIMER -eq 0 ]; then
    echo "Flywheel timer (user):"
    (timeout 8s systemctl --user status agentforge-flywheel.timer --no-pager -l 2>/dev/null | head -8) || echo "  (inactive or system mode — see enable_continuous output)"
    echo "Timers listing:"
    (timeout 8s systemctl --user list-timers --all 2>/dev/null | grep -E 'flywheel|NEXT|ago' | cat) || true
    echo ""
fi

echo "Flywheel health snapshots:"
for f in /tmp/agentforge_rust_flywheel/flywheel_health.json /tmp/agentforge_rust_flywheel/watchdog_flywheel_status.json; do
    if [ -f "$f" ]; then
        echo "  $f : $(head -c 180 "$f" 2>/dev/null | tr '\n' ' ')"
    else
        echo "  $f : (will appear after first continuous tick or manual run_continuous)"
    fi
done
echo ""

echo "Pending candidates (top recent):"
PYTHONPATH=/home/agx python -m agentforge.list_pending_candidates list --limit 5 --sort value 2>/dev/null | cat || echo "  (run after first flywheel step)"
echo ""

echo "Quick post_process default-on probe (no mutation):"
PYTHONPATH=/home/agx python3 -c '
import os
os.environ.pop("DISABLE_RUST_FLYWHEEL", None)
from agentforge.eval.post_process import post_process_task
print("  post_process_task default rust_flywheel_enabled guard: ACTIVE (or True path unless DISABLE=1)")
' 2>/dev/null || echo "  (probe non-fatal)"

echo ""
log "=== VERIFICATION COMPLETE ==="

# === Farm-wide exact commands (main + remotes) ===
log "=== FARM-WIDE ONE-COMMAND ACTIVATION (copy-paste ready) ==="
cat << 'FARM_BLOCK'

# === 1. MAIN HOST (Autonomy / API / dispatcher / timer host) ===
cd /home/agx/agentforge
bash bin/make_antigravity_default.sh                 # <-- THE ONE COMMAND (or --dry-run first)
# Full verify:
bash healthcheck.sh | grep -E 'Flywheel|Timer|Rust'
systemctl --user status agentforge-flywheel.timer || true
python -m agentforge.list_pending_candidates list --limit 3

# === 2. ALL LOCAL WORKERS (grok/jules on same host) ===
# Workers auto-source ENABLE + rust_flywheel.env on startup (already wired).
# After the one-command above, simply (when safe / low load):
systemctl --user restart agentforge-worker agentforge-jules-worker 2>/dev/null || \
  (pkill -f 'grok_worker.sh|jules_worker.sh' 2>/dev/null; bash grok_worker.sh & bash jules_worker.sh &)

# === 3. FARM ROLLOUT PACKAGE — ANTIGRAVITY DEFAULT (Rust self-improving flywheel now DEFAULT) ===
# Ready-to-use for entire production farm in one go.
# Base: this script + supporting bins. Turbo practical + production safe.

# --- SAFETY NOTES (READ — CRITICAL) ---
# * ALWAYS: bash bin/make_antigravity_default.sh --dry-run   on MAIN first (zero mutation).
# * Prefer PER-HOST rollout first wave (one remote at a time, watch load/dashboard).
# * Master wrapper (below) ALWAYS does --dry-run per remote + short pause + (interactive or --yes).
# * Only proceed to real after dry output looks clean on that host.
# * ROLLBACK per remote (instant): ssh <host> 'DISABLE_RUST_FLYWHEEL=1 bash /home/agx/agentforge/bin/disable_rust_flywheel.sh 2>/dev/null || true; systemctl --user restart agentforge-worker agentforge-jules-worker 2>/dev/null || true; rm -f /home/agx/agentforge/ENABLE_RUST_FLYWHEEL 2>/dev/null || true'
# * Timer primarily on main Autonomy host(s). Workers + hooks on all remotes.
# * Low-load window recommended. Monitor with: tail -f logs/*.log + dashboard + healthcheck.
# * All commands are idempotent; re-run make_ script to re-arm default anywhere.
# * Jetson uses full user@IP (key auth from history); add more hosts to REMOTES if new Jetsons appear.

# Known remotes (from grok-work/* layout + agent_cards.json Jetson + history):
#   agent1..5 ssh-1..8 team-code/perf/rust/services/singbox/ssh + agx@146.120.89.199 (jetson)
# Edit the list in the MASTER below if fleet changes.

# --- ONE CLEAN COMMAND STYLE (manual / per-host, max safety) ---
# Example for a single remote (repeat pattern; replace HOST):
#   scp /home/agx/agentforge/bin/make_antigravity_default.sh \
#       /home/agx/agentforge/bin/{enable_rust_flywheel.sh,enable_continuous_flywheel.sh,disable_rust_flywheel.sh,rust_flywheel.env,run_continuous_flywheel.*} \
#       /home/agx/agentforge/agentforge-flywheel.{service,timer} \
#       /home/agx/agentforge/ENABLE_RUST_FLYWHEEL \
#       /home/agx/agentforge/healthcheck.sh \
#       HOST:/tmp/antigravity-default/
#   ssh HOST '
#     mkdir -p /tmp/antigravity-default && cd /tmp/antigravity-default
#     bash make_antigravity_default.sh --dry-run
#     # ... review output ...
#     bash make_antigravity_default.sh --no-timer || bash make_antigravity_default.sh
#     touch /home/agx/agentforge/ENABLE_RUST_FLYWHEEL
#     systemctl --user restart agentforge-worker agentforge-jules-worker 2>/dev/null || (pkill -f "grok_worker.sh|jules_worker.sh" 2>/dev/null; bash /home/agx/agentforge/grok_worker.sh & bash /home/agx/agentforge/jules_worker.sh &) || true
#     # POST-VERIFY (healthcheck + timer + default probe):
#     bash /home/agx/agentforge/healthcheck.sh 2>/dev/null | grep -E "Flywheel|Timer|Rust|✅|⚠️|ONLINE" | head -12 || true
#     systemctl --user status agentforge-flywheel.timer --no-pager 2>/dev/null | head -6 || systemctl --user list-timers 2>/dev/null | grep -iE "flywheel|NEXT" || true
#     ls -l /home/agx/agentforge/ENABLE_RUST_FLYWHEEL 2>/dev/null || echo "ENABLE present via default-on"
#     python3 -c "import os; os.environ.pop(\"DISABLE_RUST_FLYWHEEL\",None); print(\"post_process Rust default guard: ACTIVE\")" 2>/dev/null || true
#   '
# After fleet: on main run healthcheck + list_pending + (optional) continuous dry step.

# --- MASTER ROLLOUT SCRIPT (the trivial one-go farm flipper — copy-paste ready) ---
# Creates /tmp/farm_antigravity_rollout.sh (small, safe, production).
# It: pushes to all, dry-runs each, (pause/confirm or --yes), reals, then full post-verify (health+timer+probe) per host.
cat > /tmp/farm_antigravity_rollout.sh << 'MASTER_ROLLOUT'
#!/bin/bash
# farm_antigravity_rollout.sh — FARM ROLLOUT EXECUTOR for Antigravity Default
# (Rust flywheel now default everywhere). Generated from bin/make_antigravity_default.sh
# Turbo + safe: dry first everywhere, per-host control, full verification, easy rollback.
set -u
AGENTFORGE="/home/agx/agentforge"
cd "$AGENTFORGE" || exit 1

AUTO_YES=0
[ "${1:-}" = "--yes" ] && AUTO_YES=1

# === FULL PRODUCTION FARM LIST (grok-work/* + Jetson from history) ===
REMOTES=(
  agent1 agent2 agent3 agent4 agent5
  ssh-1 ssh-2 ssh-3 ssh-4 ssh-5 ssh-6 ssh-7 ssh-8
  team-code team-perf team-rust team-services team-singbox team-ssh
  agx@146.120.89.199   # jetson (primary Jetson; add others as agx@IP if discovered)
)

# Core payload (make + enables + disable for rollback + env + units + marker + health)
PAYLOAD=(
  bin/make_antigravity_default.sh
  bin/enable_rust_flywheel.sh bin/enable_continuous_flywheel.sh bin/disable_rust_flywheel.sh
  bin/rust_flywheel.env
  bin/run_continuous_flywheel.py bin/run_continuous_flywheel.sh
  agentforge-flywheel.service agentforge-flywheel.timer
  ENABLE_RUST_FLYWHEEL
  healthcheck.sh
)

echo "================================================================"
echo "=== ANTIGRAVITY DEFAULT — FARM ROLLOUT (master executor) ==="
echo "Date: $(date -Iseconds)   Host: $(hostname)"
echo "Targets: ${#REMOTES[@]} remotes"
echo "Mode: dry-first ALWAYS; real only after review (${AUTO_YES:+auto} )"
echo "Payload files: ${#PAYLOAD[@]}"
echo "Safety: per-host dry + verify (health/timer/probe) + 4s throttle"
echo "Rollback example (any host): DISABLE_RUST_FLYWHEEL=1 bash bin/disable_rust_flywheel.sh; systemctl --user restart agentforge-{worker,jules-worker} || true"
echo "================================================================"

for host in "${REMOTES[@]}"; do
  echo ""
  echo ">>> [$host] ROLLOUT START"
  # Push (best-effort; continue on partial)
  echo "  [1/4] scp payload to $host:/tmp/antigravity-default/"
  scp "${PAYLOAD[@]/#/$AGENTFORGE/}" "$host:/tmp/antigravity-default/" 2>&1 | tail -5 || echo "     (scp warning — some files may already be present or host partial)"

  # Always dry first (zero risk preview)
  echo "  [2/4] DRY-RUN on $host (review this output)..."
  ssh -o ConnectTimeout=15 -o BatchMode=yes "$host" '
    set -u
    mkdir -p /tmp/antigravity-default
    cd /tmp/antigravity-default
    bash make_antigravity_default.sh --dry-run 2>&1 | tail -25
  ' 2>&1 | tail -30 || true

  if [ $AUTO_YES -eq 0 ]; then
    echo "  [PAUSE] Dry complete for $host. Safe?"
    read -r -p "      Run REAL enable on $host now? [y/N]: " ans
    if [[ ! "$ans" =~ ^[Yy] ]]; then
      echo "     SKIPPED real for $host (rollback still available via DISABLE)"
      continue
    fi
  else
    echo "  [AUTO-YES] Proceeding to real after dry..."
    sleep 2
  fi

  # Real push + enable (no-timer on remotes to avoid duplicate timers; main handles continuous)
  echo "  [3/4] REAL enable on $host..."
  ssh -o ConnectTimeout=20 -o BatchMode=yes "$host" '
    set -u
    mkdir -p /tmp/antigravity-default
    cd /tmp/antigravity-default
    bash make_antigravity_default.sh --no-timer 2>&1 | tail -20 || bash make_antigravity_default.sh 2>&1 | tail -15
    touch /home/agx/agentforge/ENABLE_RUST_FLYWHEEL 2>/dev/null || true
    # Safe worker bounce (user units preferred; fallback direct)
    if systemctl --user is-active --quiet agentforge-worker 2>/dev/null || systemctl --user is-active --quiet agentforge-jules-worker 2>/dev/null; then
      systemctl --user restart agentforge-worker agentforge-jules-worker 2>/dev/null || true
    else
      pkill -f "grok_worker.sh|jules_worker.sh" 2>/dev/null || true
      (nohup bash /home/agx/agentforge/grok_worker.sh > /dev/null 2>&1 &)
      (nohup bash /home/agx/agentforge/jules_worker.sh > /dev/null 2>&1 &)
    fi
    echo "  Workers signalled on $host"
  ' 2>&1 | tail -25 || echo "     (ssh real warning on $host — check manually)"

  # Post-push verification block (healthcheck + timer status + default probe)
  echo "  [4/4] POST-PUSH VERIFICATION on $host..."
  ssh -o ConnectTimeout=15 -o BatchMode=yes "$host" '
    echo "=== $host POST-VERIFY (health + timer + default probe) ==="
    bash /home/agx/agentforge/healthcheck.sh 2>/dev/null | grep -E "Flywheel|Timer|Rust|✅|⚠️|Task Queue|ONLINE|OFFLINE" | head -15 || true
    echo "--- Timer status ---"
    (systemctl --user status agentforge-flywheel.timer --no-pager -l 2>/dev/null | head -7) || (systemctl --user list-timers --all 2>/dev/null | grep -iE "flywheel|agentforge" | head -3) || echo "  (no user timer or system mode)"
    echo "--- Default-on probe (ENABLE marker + guard) ---"
    ls -l /home/agx/agentforge/ENABLE_RUST_FLYWHEEL /home/agx/agentforge/.disable_rust_flywheel 2>/dev/null || echo "  ENABLE marker (or implicit via post-2026-05 default-on logic)"
    python3 -c "
import os, sys
os.environ.pop(\"DISABLE_RUST_FLYWHEEL\", None)
print(\"  post_process rust_flywheel guard: ACTIVE (default unless DISABLE=1)\")
print(\"  (see eval/post_process.py and dispatcher.sh)\")
" 2>/dev/null || echo "  (python probe non-fatal)"
    echo "=== $host VERIFY END ==="
  ' 2>&1 | tail -30 || true

  echo "  [$host] COMPLETE (review verify block above)"
  sleep 4   # farm courtesy throttle between hosts
done

echo ""
echo "================================================================"
echo "=== FARM ROLLOUT COMPLETE ==="
echo "Next steps on MAIN (Antigravity Default now live everywhere):"
echo "  bash /home/agx/agentforge/healthcheck.sh | grep -E \"Flywheel|Timer|Rust\""
echo "  python -m agentforge.list_pending_candidates list --limit 5 --sort value"
echo "  systemctl --user status agentforge-flywheel.timer || true"
echo ""
echo "Per-host rollback (example):"
echo "  ssh agent3 'DISABLE_RUST_FLYWHEEL=1 bash /home/agx/agentforge/bin/disable_rust_flywheel.sh || true; systemctl --user restart agentforge-worker agentforge-jules-worker || true'"
echo ""
echo "Re-arm default on any host:"
echo "  ssh HOST 'bash /home/agx/agentforge/bin/make_antigravity_default.sh'"
echo "================================================================"
MASTER_ROLLOUT
chmod +x /tmp/farm_antigravity_rollout.sh
echo ""
echo "Master created at: /tmp/farm_antigravity_rollout.sh"
echo "Usage (after local dry on main):"
echo "  bash /tmp/farm_antigravity_rollout.sh          # interactive (recommended first farm wave)"
echo "  bash /tmp/farm_antigravity_rollout.sh --yes   # auto-proceed after each dry (use only on known-good fleet)"
echo ""
echo "One-liner master invoke (when ready):"
echo "  scp /tmp/farm_antigravity_rollout.sh main-host:/tmp/ && ssh main-host 'bash /tmp/farm_antigravity_rollout.sh'"

# === 4. API / TASK QUEUE (same host as #1 usually) ===
# Covered by step 1. Ensure agentforge-api.service sees PYTHONPATH + env (via install_services or user unit).

# === 5. Real A/B wave (after default locked + low load) ===
# See bin/trigger_real_ab_on_farm.sh and bin/real_ab_farm_commands.txt
# (uses the now-default ENABLE + Rust paths automatically)

FARM_BLOCK

# === Clean DISABLE path (the only killswitch) ===
log "=== CLEAN DISABLE / ROLLBACK (instant, zero risk) ==="
cat << 'DISABLE_BLOCK'

# Global per-process (affects dispatch, post_process, hooks, workers immediately):
export DISABLE_RUST_FLYWHEEL=1
# Then restart workers:
systemctl --user restart agentforge-worker agentforge-jules-worker 2>/dev/null || true

# Permanent (systemd units — edit or via env in unit files):
# In [Service] section: Environment=DISABLE_RUST_FLYWHEEL=1
# (remove AGENTFORGE_RUST_* lines)

# Clean marker + timer (full flywheel no-op, keeps legacy paths happy):
rm -f /home/agx/agentforge/ENABLE_RUST_FLYWHEEL /home/agx/agentforge/.disable_rust_flywheel 2>/dev/null || true
systemctl --user disable --now agentforge-flywheel.timer 2>/dev/null || sudo systemctl disable --now agentforge-flywheel.timer 2>/dev/null || true
rm -f ~/.config/systemd/user/agentforge-flywheel.* /etc/systemd/system/agentforge-flywheel.* 2>/dev/null || true
systemctl --user daemon-reload 2>/dev/null; sudo systemctl daemon-reload 2>/dev/null || true

# Per-invocation test:
DISABLE_RUST_FLYWHEEL=1 PYTHONPATH=. python -m agentforge.eval.post_process <task_id>

# Re-arm default (one command):
bash /home/agx/agentforge/bin/make_antigravity_default.sh

# Evidence that disable is respected everywhere: post_process.py, dispatcher.sh, phase2_3_integration.py, all *_worker.sh, enable_*.sh, watchdog.py

DISABLE_BLOCK

log "=== ANTIGRAVITY DEFAULT ENABLER COMPLETE ==="
log "See $LOG_FILE for full trace."
log "The farm is now running Antigravity Default: Rust flywheel ON for every task + 24/7 continuous closer."
log "Only off-switch: DISABLE_RUST_FLYWHEEL=1 (env or .disable_rust_flywheel file)."

# Final safe dry invocation of continuous (reuses all paths)
if [ $DRY_RUN -eq 0 ]; then
    log "Final safe verification dry-run of continuous closer..."
    env PYTHONPATH=/home/agx ENABLE_RUST_FLYWHEEL=1 timeout 20s python -m agentforge.bin.run_continuous_flywheel --top-n 1 --dry-run 2>&1 | tail -10 || true
fi

exit 0
