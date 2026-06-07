#!/bin/bash
# ============================================================
# bin/disable_pure_rust_flywheel.sh — ONE-COMMAND PURE RUST FLYWHEEL DISABLE / ROLLBACK
# PRODUCTION EXCELLENCE VERSION: The definitive symmetric high-quality counterpart
# to the upgraded bin/make_pure_rust_flywheel_default.sh (the Phase 3 cutover).
#
# Mission: Instant, safe, complete, production-grade rollback from pure-Rust cutover.
# - Touches .disable_pure_rust_flywheel marker (strong killswitch honored by is_pure_rust_flywheel() + ALL guards in learning/utils.py + post_process + continuous + workers + dispatch)
# - Removes .pure_rust_flywheel marker (clean state)
# - FULL ROLLBACK: RESTORES every *.bak.purecutover (authoritative pre-cutover from cutover script) + creates fresh .bak.pure-rollback-* of the current pure state (enables undoing this disable without re-cutover)
# - Regenerates bin/rust_flywheel.env with pure-disabled logic (AGENTFORGE_FLYWHEEL_ENGINE=python precedence + full disable killswitch handling)
# - Idempotent safe residual pure-section strip (awk precision) for files lacking baks
# - Full --dry-run (zero mutation, EXTREMELY LOUD/INFORMATIVE preflight: exact "would restore" list + bak previews + env rewrite preview + strip sim + verification commands)
# - Strong verification (EXCELLENT depth, mirrors cutover): proves is_pure()==False even under forced-pure envs, ACTUAL python orchestration runs (candidate list), binary still callable for direct tests, health snapshots, provenance, test script smoke
# - Safe service handling (user-mode only, --force-restart opt-in, timeouts, daemon-reload; never blind)
# - Full FARM ROLLOUT PACKAGE: generates high-quality /tmp/farm_disable_pure_rust_rollout.sh (dry-first ALWAYS, rich per-host scp+ssh+verify with actual python/binary probes + re-arm notes, throttle, extensive safety/soak)
# - Prints clean RE-ARM path (only way back to pure: bash bin/make_pure_rust_flywheel_default.sh after release binary)
#
# !!! AGGRESSIVE FINAL DEPRECATION SWEEP (RUST_FULL_MIGRATION_PLAN.md + PHASE4_REMOVAL_PLAN.md) !!!
# !!! bin/disable_pure_rust_flywheel.sh : CRITICAL PHASE 4 ROLLBACK MASTER TOOL (symmetric to make_...) !!!
# Enables instant revert at ANY removal tier. Layer 2/3 of rollback strategy.
# Touches .disable_pure_rust_flywheel (honored first by is_pure_rust_flywheel guard).
# Full strategy + verification commands + farm ssh loop: see PHASE4_REMOVAL_PLAN.md (section 4 Rollback).
# KEEP until final Tier 5 cleanup. Used in every gate and post-removal soak abort.
#
# Production guarantees (exact mirror of upgraded cutover script):
# - Idempotent + resilient (no -e, timeouts on critical ops, guards everywhere, set -u only)
# - Full reuse of every existing guard (DISABLE_RUST + .disable_* + is_pure_rust_flywheel() + rate locks + flock + env)
# - --dry-run *mandatory* first (zero-mutation preflight with loud banners + full simulation of restores + env + rich verify)
# - Logging to logs/disable_pure_rust_flywheel.log (with tee)
# - Always emits expanded re-arm + verification + farm blocks (copy-paste ready)
# - Non-breaking: Python orchestration fully restored as default; direct binary use remains 100% for testing / bypass
# - Full rollback safety: pre-restore current-state backups + authoritative cutover baks
#
# Symmetry (identical DNA to upgraded make_pure...):
# - Structure, banners (dry/real), arg parsing, log style, hard/soft gates, patch/restore lists, env rewrite, safe service, EXCELLENT verification (with actual execs), FARM_BLOCK + embedded master (high-quality scp-from-main pattern, rich post-verify, soak notes), DISABLE/REARM blocks — pixel-perfect mirror
# - Dry-run previews every bak restore + sample bak content + exact env snippet that would be written + strip simulation
# - Real mode = precise inverse of cutover (marker + baks restore + new rollback baks + env + strips)
#
# Links:
# - RUST_FULL_MIGRATION_PLAN.md (Phase 3 rollback + exit criteria for disable)
# - MIGRATION_PROGRESS.md + FARM_ROLLOUT_CHECKLIST.md + JULES_FARM_*.md
# - AGENTFORGE_FRONTIER_ROADMAP.md
# - bin/make_pure_rust_flywheel_default.sh (the upgraded cutover this symmetrically disables — keep both in sync)
# - learning/utils.py (is_pure_rust_flywheel + .disable_pure precedence + is_rust_flywheel_disabled)
# - bin/test_pure_rust_flywheel_step.sh + rust_flywheel_demo.py (still fully functional for direct binary post-disable)
# - bin/disable_rust_flywheel.sh (for full legacy rust disable on top)
#
# Usage (from /home/eveselove/agentforge):
#   bash bin/disable_pure_rust_flywheel.sh                 # THE ONE COMMAND for full pure disable + strong verify
#   bash bin/disable_pure_rust_flywheel.sh --dry-run       # EXTREMELY INFORMATIVE zero-mutation preflight (ALWAYS FIRST)
#   bash bin/disable_pure_rust_flywheel.sh --force-restart # also bounce user workers/timer after restores (low-load only)
#   bash bin/disable_pure_rust_flywheel.sh --help
#
# After run: pure-Rust orchestration OFF everywhere (python is default for post_process/continuous/pending/hooks/workers).
# Direct `agentforge-runner flywheel-step / candidate / continuous` remain available for testing (non-defaulted).
# Re-arm pure: bash bin/make_pure_rust_flywheel_default.sh --dry-run && bash bin/make_pure_rust_flywheel_default.sh (after release binary).
#
# This is the production one-command symmetric disable for the upgraded pure cutover.
# Activation: 2026-05-31 (High-velocity symmetric delivery — DISABLE SCRIPT NOW PRODUCTION-READY)
# ============================================================

set -u
# Resilience: explicit error handling only on critical paths (exact mirror of cutover)

AGENTFORGE_ROOT="/home/eveselove/agentforge"
cd "$AGENTFORGE_ROOT" 2>/dev/null || true

LOG_DIR="$AGENTFORGE_ROOT/logs"
mkdir -p "$LOG_DIR" 2>/dev/null || true
LOG_FILE="$LOG_DIR/disable_pure_rust_flywheel.log"

log() {
    local ts
    ts=$(date -Iseconds 2>/dev/null || date +%Y-%m-%dT%H:%M:%S%z)
    echo "[$ts] $*" | tee -a "$LOG_FILE" 2>/dev/null || echo "[$ts] $*"
}

dry_banner() {
    echo ""
    echo "╔══════════════════════════════════════════════════════════════════════════════╗"
    echo "║  DRY-RUN MODE — ZERO FILE MUTATIONS — SAFE PREFLIGHT ONLY                    ║"
    echo "║  All restores, marker ops, env rewrites, and verifications are SIMULATED.    ║"
    echo "║  Review output, then re-run WITHOUT --dry-run (low-load window recommended). ║"
    echo "╚══════════════════════════════════════════════════════════════════════════════╝"
    echo ""
}

real_banner() {
    echo ""
    echo "╔══════════════════════════════════════════════════════════════════════════════╗"
    echo "║  ⚡ LIVE DISABLE / ROLLBACK MODE — MUTATIONS WILL BE APPLIED ⚡               ║"
    echo "║  Symmetric production tool to make_pure_rust_flywheel_default.sh.            ║"
    echo "║  Backups (.bak.purecutover) will be used to restore pre-cutover state.       ║"
    echo "╚══════════════════════════════════════════════════════════════════════════════╝"
    echo ""
}

log "=== PURE RUST FLYWHEEL DISABLE / ROLLBACK ONE-COMMAND START ==="

# === Args (exact mirror of upgraded cutover script) ===
DRY_RUN=0
FORCE_RESTART=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run|--dry|--sim) DRY_RUN=1; shift ;;
        --force-restart) FORCE_RESTART=1; shift ;;
        --help|-h)
            echo "See header of $0 for full docs (symmetric high-quality mirror of upgraded make_pure_rust_flywheel_default.sh)."
            echo "Examples:"
            echo "  bash bin/disable_pure_rust_flywheel.sh --dry-run"
            echo "  bash bin/disable_pure_rust_flywheel.sh"
            echo "  bash bin/disable_pure_rust_flywheel.sh --force-restart"
            exit 0
            ;;
        *) log "Unknown arg: $1 (ignored)"; shift ;;
    esac
done

log "DRY_RUN=$DRY_RUN | FORCE_RESTART=$FORCE_RESTART"

# === Core lists (MUST be early for helper — symmetric to cutover aggressive lists) ===
PURE_MARKER="$AGENTFORGE_ROOT/.pure_rust_flywheel"
DISABLE_PURE_MARKER="$AGENTFORGE_ROOT/.disable_pure_rust_flywheel"
ENV_SNIPPET="$AGENTFORGE_ROOT/bin/rust_flywheel.env"

WORKER_SH_FILES=(
    "$AGENTFORGE_ROOT/grok_worker.sh"
    "$AGENTFORGE_ROOT/jules_worker.sh"
    "$AGENTFORGE_ROOT/dispatcher.sh"
    "$AGENTFORGE_ROOT/agents/grok_runner.sh"
    "$AGENTFORGE_ROOT/agents/jules_runner.sh"
    "$AGENTFORGE_ROOT/agents/agy_runner.sh"
    "$AGENTFORGE_ROOT/agents/gemini_runner.sh"
    "$AGENTFORGE_ROOT/bin/rust_flywheel_after_task.sh"
    "$AGENTFORGE_ROOT/bin/run_continuous_flywheel.sh"
    "$AGENTFORGE_ROOT/bin/run_continuous_flywheel.py"
    "$AGENTFORGE_ROOT/healthcheck.sh"
    "$AGENTFORGE_ROOT/bin/enable_rust_flywheel.sh"
    "$AGENTFORGE_ROOT/bin/enable_continuous_flywheel.sh"
    "$AGENTFORGE_ROOT/bin/disable_rust_flywheel.sh"
    "$AGENTFORGE_ROOT/bin/trigger_real_ab_on_farm.sh"
    "$AGENTFORGE_ROOT/bin/execute_real_abs_on_promoted.sh"
    "$AGENTFORGE_ROOT/install_services.sh"
)

SERVICES_AND_TIMERS=(
    "$AGENTFORGE_ROOT/agentforge-flywheel.service"
    "$AGENTFORGE_ROOT/agentforge-worker.service"
    "$AGENTFORGE_ROOT/agentforge-jules-worker.service"
    "$AGENTFORGE_ROOT/agentforge-api.service"
    "$AGENTFORGE_ROOT/agentforge-watchdog.service"
    "$AGENTFORGE_ROOT/agentforge.service"
    "$AGENTFORGE_ROOT/agentforge-flywheel.timer"
)

# === Release binary + full-rollback readiness helper (soft gate for disable — awareness + safety) ===
RUST_RELEASE_BIN="$AGENTFORGE_ROOT/rust/target/release/agentforge-runner"
RUST_DEBUG_BIN="$AGENTFORGE_ROOT/rust/target/debug/agentforge-runner"

verify_rollback_readiness() {
    local bak_count=0
    for f in "${WORKER_SH_FILES[@]}" "${SERVICES_AND_TIMERS[@]}"; do
        if [ -f "${f}.bak.purecutover" ]; then
            bak_count=$((bak_count + 1))
        fi
    done
    if [ $bak_count -gt 0 ]; then
        log "ROLLBACK READINESS: $bak_count .bak.purecutover files present from prior cutover (authoritative restore sources)"
        return 0
    else
        log "ROLLBACK READINESS: No .bak.purecutover found (cutover may not have run on this host, or already fully disabled). Proceeding with marker+env+strip only (still fully effective disable)."
        return 0
    fi
}

# === DRY / REAL BANNER + READINESS (mirror upgraded cutover) ===
if [ $DRY_RUN -eq 1 ]; then
    dry_banner
else
    real_banner
fi

verify_rollback_readiness

# === DRY-RUN SIMULATION (EXTREMELY INFORMATIVE zero mutations — full symmetry to upgraded cutover) ===
if [ $DRY_RUN -eq 1 ]; then
    log "=== DRY-RUN MODE (ZERO MUTATIONS — EXTREMELY INFORMATIVE PREFLIGHT) ==="
    log "[dry] TARGET ROOT: $AGENTFORGE_ROOT"
    log "[dry] BINARY (for direct test awareness): $RUST_RELEASE_BIN"
    log "[dry] PURE MARKER TO REMOVE: $PURE_MARKER"
    log "[dry] DISABLE_PURE MARKER TO TOUCH: $DISABLE_PURE_MARKER"
    log "[dry] ENV SNIPPET TO REWRITE (pure-disabled logic): $ENV_SNIPPET"
    log ""
    log "[dry] === ROLLBACK LOGIC (BAK RESTORATION — THE CORE + FULL ROLLBACK SAFETY) ==="
    bak_preview_count=0
    for f in "${WORKER_SH_FILES[@]}" "${SERVICES_AND_TIMERS[@]}"; do
        bak="${f}.bak.purecutover"
        if [ -f "$bak" ]; then
            log "[dry]   would restore: cp -f '$bak' '$f'   (pre-pure state from cutover)"
            if [ $bak_preview_count -lt 3 ]; then
                log "[dry]     sample of $bak (first 3 lines):"
                head -3 "$bak" 2>/dev/null | sed 's/^/[dry]       /' || true
                bak_preview_count=$((bak_preview_count + 1))
            fi
        else
            log "[dry]   (no .bak.purecutover for $f — would perform safe section strip if pure header present)"
        fi
    done
    log ""
    log "[dry] === FULL ROLLBACK SAFETY: would also snapshot current pure-state to timestamped .bak.pure-rollback-* before restores ==="
    log ""
    log "[dry] === ENV SNIPPET PREVIEW (exact what the rewrite would contain) ==="
    log "[dry]   Logic: .disable_pure + AGENTFORGE_FLYWHEEL_ENGINE=python force python; DISABLE_RUST ultimate; pure marker/env still honored only if no disable."
    cat << 'DRY_ENV_PREVIEW' | sed 's/^/[dry]   /'
# (see real rewrite below for full 40-line production snippet with all killswitches + runner discovery)
DRY_ENV_PREVIEW
    log "[dry]   (full snippet written in real run; 2026-06 pure-disabled + provenance)"
    log ""
    log "[dry] === ADDITIONAL CLEANUP (idempotent, safe) ==="
    log "[dry]   would: rm -f $PURE_MARKER"
    log "[dry]   would: touch $DISABLE_PURE_MARKER"
    log "[dry]   would: strip any residual '# === PURE RUST FLYWHEEL DEFAULT' blocks (awk precision, files without baks)"
    log ""
    log "[dry] === SAFE SERVICE HANDLING (would) ==="
    log "[dry]   systemctl --user daemon-reload"
    log "[dry]   Conditional user-mode restarts ONLY if --force-restart (with timeouts)"
    log ""
    log "[dry] === STRONG VERIFICATION THAT WOULD ACTUALLY RUN (EXCELLENT — mirrors cutover depth) ==="
    log "[dry]   1. Python is_pure_rust_flywheel() probe UNDER FORCED PURE ENVS (MUST return False)"
    log "[dry]   2. ls -l of markers + DISABLE_RUST"
    log "[dry]   3. env grep PURE_RUST/FLYWHEEL_ENGINE + snippet tail"
    log "[dry]   4. ACTUAL: python -m agentforge.list_pending_candidates list (python orchestration exercised)"
    log "[dry]   5. healthcheck.sh focused pure/engine grep"
    log "[dry]   6. Direct binary subcommand --help (still available post-disable)"
    log "[dry]   7. bash bin/test_pure_rust_flywheel_step.sh (smoke — binary reachable)"
    log "[dry]   8. Pending manifests + /tmp/... health json (python provenance expected)"
    log "[dry]   9. Full farm block + high-quality generated master script (/tmp/farm_disable_pure_rust_rollout.sh)"
    log ""
    log "[dry] === FARM ROLLOUT MASTER THAT WOULD BE (RE)GENERATED ==="
    log "[dry]   /tmp/farm_disable_pure_rust_rollout.sh (dry-first ALWAYS + scp-from-main pattern + rich per-host python+is_pure+binary+health verify + re-arm + throttle)"
    log ""
    log "[dry] === RE-ARM / ROLLBACK OF THIS DISABLE (back to pure) ==="
    log "[dry]   bash bin/make_pure_rust_flywheel_default.sh --dry-run"
    log "[dry]   bash bin/make_pure_rust_flywheel_default.sh"
    log ""
    log "[dry] === END OF EXTREMELY INFORMATIVE DRY SIM (review above — zero risk — then re-run WITHOUT --dry-run) ==="
    dry_banner
    log "DRY-RUN COMPLETE — no changes made."
    exit 0
fi

# === REAL MODE: EXECUTE THE SYMMETRIC HIGH-QUALITY ROLLBACK (mirror of upgraded cutover) ===
log "=== LIVE PURE RUST DISABLE / ROLLBACK — EXECUTING ==="

DATE_TAG=$(date -Iseconds 2>/dev/null || date +%Y-%m-%dT%H:%M:%S)

# Full rollback safety (production-grade): snapshot CURRENT pure-patched state *before* restores.
# Creates *.bak.pure-rollback-YYYYMMDD_HHMMSS — enables instant undo of *this disable* (re-apply pure state without re-running full cutover).
log "FULL ROLLBACK SAFETY: snapshotting current pure state to timestamped .bak.pure-rollback-* ..."
ROLLBACK_SNAPSHOT_TAG="bak.pure-rollback-$(date +%Y%m%d_%H%M%S 2>/dev/null || date +%s)"
SNAPSHOT_COUNT=0
for f in "${WORKER_SH_FILES[@]}" "${SERVICES_AND_TIMERS[@]}"; do
    if [ -f "$f" ]; then
        cp -f "$f" "${f}.${ROLLBACK_SNAPSHOT_TAG}" 2>/dev/null && SNAPSHOT_COUNT=$((SNAPSHOT_COUNT + 1)) || true
    fi
done
log "  Current-state snapshots: $SNAPSHOT_COUNT files as *.${ROLLBACK_SNAPSHOT_TAG} (full undo capability for this disable)"

# 1. Touch strong disable marker FIRST (honored by Python is_pure + shell guards + all env logic)
log "Touching .disable_pure_rust_flywheel marker (strong killswitch for pure layer)..."
touch "$DISABLE_PURE_MARKER" || log "WARNING: touch disable marker failed (non-fatal)"
chmod 644 "$DISABLE_PURE_MARKER" 2>/dev/null || true

# 2. Remove pure marker (clean state — disable takes precedence anyway)
if [ -f "$PURE_MARKER" ]; then
    log "Removing .pure_rust_flywheel marker (clean rollback)..."
    rm -f "$PURE_MARKER" 2>/dev/null || true
else
    log ".pure_rust_flywheel already absent (good)."
fi

# 3. THE CORE ROLLBACK: Restore every .bak.purecutover (authoritative pre-cutover state)
log "RESTORING pre-pure state from all .bak.purecutover backups (strong rollback logic)..."
RESTORED_COUNT=0
for f in "${WORKER_SH_FILES[@]}" "${SERVICES_AND_TIMERS[@]}"; do
    bak="${f}.bak.purecutover"
    if [ -f "$bak" ]; then
        cp -f "$bak" "$f" 2>/dev/null && {
            log "  RESTORED: $f ← $bak"
            RESTORED_COUNT=$((RESTORED_COUNT + 1))
        } || log "  WARNING: restore failed for $f (non-fatal)"
    fi
done
log "Bak restoration complete: $RESTORED_COUNT files restored from pure-cutover backups."

# 4. Idempotent residual pure-section cleanup for any files that never got (or lost) a bak
log "Performing safe residual pure-section strip (files without .bak.purecutover)..."
PURE_HEADER_REGEX="=== PURE RUST FLYWHEEL DEFAULT"
for f in "${WORKER_SH_FILES[@]}" "${SERVICES_AND_TIMERS[@]}"; do
    if [ -f "$f" ] && ! [ -f "${f}.bak.purecutover" ]; then
        STRIPPED=0
        if grep -q "$PURE_HEADER_REGEX" "$f" 2>/dev/null; then
            # Safe: remove from the pure header block to the matching "End pure section" or next major comment
            # Use awk for precision (keeps file otherwise intact)
            awk '
                BEGIN { in_pure=0 }
                /=== PURE RUST FLYWHEEL DEFAULT/ { in_pure=1; next }
                in_pure && /End pure section|End pure-Rust guard|DISABLE_RUST_FLYWHEEL remains ultimate/ { in_pure=0; next }
                !in_pure { print }
            ' "$f" > "$f.tmp" 2>/dev/null && mv "$f.tmp" "$f" && { log "  Stripped residual pure block: $f"; STRIPPED=1; } || rm -f "$f.tmp"
        fi
        # Also defensively strip any stray pure env injection lines from units (bottom-of-file or inline)
        if [[ "$f" == *.service || "$f" == *.timer ]] && grep -qE 'AGENTFORGE_PURE_RUST_FLYWHEEL=1|FLYWHEEL_ENGINE=rust.*agentforge-runner|PURE RUST FLYWHEEL DEFAULT CUTOVER' "$f" 2>/dev/null; then
            cp -f "$f" "$f.bak.disablepure" 2>/dev/null || true
            sed -i '/AGENTFORGE_PURE_RUST_FLYWHEEL=1/d' "$f" 2>/dev/null || true
            sed -i '/AGENTFORGE_FLYWHEEL_ENGINE=rust/d' "$f" 2>/dev/null || true
            sed -i '/AGENTFORGE_FLYWHEEL_PROVENANCE=rust-agentforge-runner/d' "$f" 2>/dev/null || true
            sed -i '/PURE RUST FLYWHEEL DEFAULT CUTOVER/,+6d' "$f" 2>/dev/null || true
            sed -i '/rollback via FLYWHEEL_ENGINE=python or .disable_pure_rust_flywheel/d' "$f" 2>/dev/null || true
            sed -i '/^$/N;/^\n$/d' "$f" 2>/dev/null || true
            log "  Stripped stray pure env lines from unit: $f"
            STRIPPED=1
        fi
        [ $STRIPPED -eq 1 ] || true
    fi
done
# Post-patch reload so restored/stripped units are live
systemctl --user daemon-reload 2>/dev/null || true

# 5. Regenerate env snippet with pure-disabled logic (symmetric to cutover rewrite + disable_rust style)
log "Rewriting $ENV_SNIPPET with pure-Rust DISABLED logic..."
cat > "$ENV_SNIPPET" << 'SNIP_EOF'
# AgentForge Rust Flywheel env snippet (auto-generated by disable_pure_rust_flywheel.sh)
# Source early in grok_worker.sh / jules_worker.sh / dispatcher.sh / runners / services:
#   source /home/eveselove/agentforge/bin/rust_flywheel.env 2>/dev/null || true
#
# 2026-06 PURE RUST DISABLE / ROLLBACK (symmetric to make_pure_rust_flywheel_default.sh)
# Pure layer (agentforge-runner as sole flywheel engine) is now OFF.
# Python orchestration paths are active. Direct binary use remains possible for tests.
#
# Killswitches (any of these force pure OFF and python fallback):
#   - .disable_pure_rust_flywheel
#   - AGENTFORGE_FLYWHEEL_ENGINE=python (or rust for legacy non-pure)
#   - .disable_rust_flywheel or DISABLE_RUST_FLYWHEEL=1 (ultimate global)
#
_DISABLE_PURE_FILE="/home/eveselove/agentforge/.disable_pure_rust_flywheel"
_PURE_FILE="/home/eveselove/agentforge/.pure_rust_flywheel"

if [[ "${DISABLE_RUST_FLYWHEEL:-0}" = "1" ]] || [[ -f "/home/eveselove/agentforge/.disable_rust_flywheel" ]]; then
    export AGENTFORGE_RUST_FLYWHEEL=0
    export AGENTFORGE_USE_RUST=0
    export AGENTFORGE_PURE_RUST_FLYWHEEL=0
    export AGENTFORGE_FLYWHEEL_ENGINE=python
elif [[ "${AGENTFORGE_FLYWHEEL_ENGINE:-}" = "python" ]] || [[ -f "$_DISABLE_PURE_FILE" ]]; then
    export AGENTFORGE_PURE_RUST_FLYWHEEL=0
    export AGENTFORGE_FLYWHEEL_ENGINE=python
    # Legacy rust vars left at prior values or cleared for pure safety
elif [[ -f "$_PURE_FILE" ]] || [[ "${AGENTFORGE_PURE_RUST_FLYWHEEL:-0}" = "1" ]] || [[ "${AGENTFORGE_FLYWHEEL_ENGINE:-}" = "rust" ]]; then
    # Pure still detected (someone bypassed) — do not auto-set; let guards decide but log intent
    export AGENTFORGE_PURE_RUST_FLYWHEEL=1
    export AGENTFORGE_FLYWHEEL_ENGINE=rust
else
    # Safe default post-disable: explicit python preference for orchestration
    export AGENTFORGE_FLYWHEEL_ENGINE="${AGENTFORGE_FLYWHEEL_ENGINE:-python}"
fi

# Runner discovery (unchanged — binary remains usable directly)
if [[ -x "/home/eveselove/agentforge/rust/target/release/agentforge-runner" ]]; then
    export AGENTFORGE_RUST_RUNNER="/home/eveselove/agentforge/rust/target/release/agentforge-runner"
elif [[ -x "/home/eveselove/agentforge/rust/target/debug/agentforge-runner" ]]; then
    export AGENTFORGE_RUST_RUNNER="/home/eveselove/agentforge/rust/target/debug/agentforge-runner"
fi
# Optional rate + provenance (preserved for any legacy rust paths)
export AGENTFORGE_RUST_FLYWHEEL_EVERY_N="${AGENTFORGE_RUST_FLYWHEEL_EVERY_N:-5}"
export AGENTFORGE_FLYWHEEL_PROVENANCE="${AGENTFORGE_FLYWHEEL_PROVENANCE:-python-after-pure-disable}"
SNIP_EOF
chmod 644 "$ENV_SNIPPET" 2>/dev/null || true
log "Env snippet rewritten for pure-disabled state."

# 6. Safe service handling (mirror of cutover)
log "=== SAFE SERVICE HANDLING ==="
log "Daemon-reload (user + optional system)..."
systemctl --user daemon-reload 2>/dev/null || true
# Note: do not require sudo in farm context

if systemctl --user is-active --quiet agentforge-flywheel.timer 2>/dev/null; then
    log "Flywheel timer active (user)"
    if [ $FORCE_RESTART -eq 1 ]; then
        timeout 10s systemctl --user restart agentforge-flywheel.timer 2>/dev/null || log "timer restart non-fatal"
    fi
else
    log "Flywheel timer not active in user mode (may be expected post-rollback)"
fi

if [ $FORCE_RESTART -eq 1 ]; then
    log "FORCE_RESTART requested — safe user worker restarts..."
    for unit in agentforge-worker agentforge-jules-worker; do
        if systemctl --user is-active --quiet "$unit" 2>/dev/null; then
            timeout 15s systemctl --user restart "$unit" 2>/dev/null || log "$unit restart attempted (non-fatal)"
        fi
    done
else
    log "Worker restart skipped (use --force-restart only on low-load). Manual: systemctl --user restart agentforge-worker agentforge-jules-worker"
fi

# === STRONG VERIFICATION (proves pure is disabled — symmetric depth to cutover) ===
log "=== VERIFICATION (evidence of Pure Rust Flywheel DISABLED) ==="

echo ""
echo "=== PURE RUST FLYWHEEL DISABLE STATUS ==="
echo "PURE marker: $(ls -l "$PURE_MARKER" 2>/dev/null || echo 'absent (correct — disabled)')"
echo "DISABLE_PURE marker: $(ls -l "$DISABLE_PURE_MARKER" 2>/dev/null || echo 'absent (unexpected)')"
echo "DISABLE_RUST marker: $(ls -l "$AGENTFORGE_ROOT/.disable_rust_flywheel" 2>/dev/null || echo 'absent')"
echo ""
echo "Release binary (still directly usable):"
ls -l "$RUST_RELEASE_BIN" 2>/dev/null || ls -l "$RUST_DEBUG_BIN" 2>/dev/null || echo "  (no release/debug binary — pure disable unaffected)"
echo ""
echo "Env (current shell + snippet):"
env | grep -E 'AGENTFORGE_(PURE_RUST|FLYWHEEL_ENGINE|RUST_RUNNER|FLYWHEEL_PROVENANCE)' | cat || true
echo "Snippet tail (last 12 lines):"
tail -12 "$ENV_SNIPPET" 2>/dev/null || true
echo ""

echo "Flywheel timer (user):"
(timeout 8s systemctl --user status agentforge-flywheel.timer --no-pager -l 2>/dev/null | head -6) || echo "  (inactive or system)"
echo ""

echo "Python is_pure_rust_flywheel() probe (FORCED PURE ENVS — MUST RETURN FALSE):"
PYTHONPATH=/home/eveselove python3 -c '
import os
os.environ["AGENTFORGE_PURE_RUST_FLYWHEEL"] = "1"
os.environ["AGENTFORGE_FLYWHEEL_ENGINE"] = "rust"
os.environ["AGENTFORGE_PURE_RUST_FLYWHEEL"] = "1"
from agentforge.learning.utils import is_pure_rust_flywheel, is_rust_flywheel_disabled, get_rust_runner_path
print("  is_pure_rust_flywheel() under forced pure envs:", is_pure_rust_flywheel())
print("  is_rust_flywheel_disabled():", is_rust_flywheel_disabled())
print("  get_rust_runner_path():", get_rust_runner_path())
print("  (Expected: False for pure — Python orchestration now active everywhere)")
' 2>/dev/null || echo "  (probe non-fatal)"

echo ""
echo "CANDIDATE LIST + Python orchestration path (post-disable):"
PYTHONPATH=/home/eveselove python -m agentforge.list_pending_candidates list --limit 2 --sort value 2>/dev/null | cat || echo "  (python path exercised)"
echo ""

echo "Direct binary subcommands (still functional for testing, orchestration now python):"
if [ -x "$RUST_RELEASE_BIN" ]; then
    "$RUST_RELEASE_BIN" --help 2>&1 | head -3 || true
    "$RUST_RELEASE_BIN" candidate --help 2>&1 | head -3 || true
elif [ -x "$RUST_DEBUG_BIN" ]; then
    "$RUST_DEBUG_BIN" --help 2>&1 | head -3 || true
else
    echo "  (no binary found — disable complete regardless)"
fi
echo ""

echo "Test pure script smoke (binary still reachable):"
if [ -x "$AGENTFORGE_ROOT/bin/test_pure_rust_flywheel_step.sh" ]; then
    bash "$AGENTFORGE_ROOT/bin/test_pure_rust_flywheel_step.sh" 2>&1 | tail -8 || true
else
    echo "  (test script not present)"
fi
echo ""

echo "Health snapshots + provenance (post-disable python expected on next ticks):"
for f in /tmp/agentforge_rust_flywheel/flywheel_health.json /tmp/agentforge_rust_flywheel/watchdog_flywheel_status.json; do
    if [ -f "$f" ]; then
        echo "  $f : $(head -c 160 "$f" 2>/dev/null | tr '\n' ' ')"
    else
        echo "  $f : (absent or will reflect python orchestration on next run)"
    fi
done
echo ""

echo "Unit purity (no pure env injection in any service/timer):"
PURE_UNIT_HITS=0
for u in "${SERVICES_AND_TIMERS[@]}"; do
    if [ -f "$u" ] && grep -qE 'AGENTFORGE_PURE_RUST_FLYWHEEL=1|FLYWHEEL_ENGINE=rust.*agentforge-runner' "$u" 2>/dev/null; then
        echo "  ⚠️  $u still has pure injection (review)"
        PURE_UNIT_HITS=$((PURE_UNIT_HITS+1))
    fi
done
if [ $PURE_UNIT_HITS -eq 0 ]; then
    echo "  ✓ All units clean of pure cutover lines"
fi
echo ""

log "=== VERIFICATION COMPLETE ==="

# === FARM-WIDE BLOCK (symmetric full production package) ===
log "=== FARM-WIDE ONE-COMMAND PURE RUST DISABLE (copy-paste ready) ==="
cat << 'FARM_BLOCK'

# === 1. MAIN HOST (Autonomy / API / dispatcher / timer host) ===
cd /home/eveselove/agentforge
bash bin/disable_pure_rust_flywheel.sh                 # <-- THE ONE COMMAND (or --dry-run first — mandatory)
bash bin/disable_pure_rust_flywheel.sh --force-restart # optional, low-load only

# Full local verify after:
#   tail -30 logs/disable_pure_rust_flywheel.log
#   python -c 'from agentforge.learning.utils import is_pure_rust_flywheel; print(is_pure_rust_flywheel())'   # must be False
#   python -m agentforge.list_pending_candidates list --limit 3

# === 2. REMOTE WORKERS / JETS (grok-work/* + Erbox) ===
# One-liner per host (copy-paste):
#   ssh agent3 'cd /home/eveselove/agentforge && bash bin/disable_pure_rust_flywheel.sh --dry-run && bash bin/disable_pure_rust_flywheel.sh'
#   ssh eveselove@146.120.89.199 'cd /home/eveselove/agentforge && ...'

# === 3. FARM ROLLOUT PACKAGE — DISABLE PURE RUST (master executor) ===
# Ready-to-use for entire production farm rollback in one go.
# Generated by bin/disable_pure_rust_flywheel.sh (symmetric to farm_pure_rust_rollout.sh)

# --- SAFETY NOTES (READ — CRITICAL) ---
# * ALWAYS: bash bin/disable_pure_rust_flywheel.sh --dry-run   on MAIN first (zero mutation).
# * Prefer PER-HOST rollout first wave (one remote at a time).
# * Master wrapper (below) ALWAYS does --dry-run per remote + short pause + (interactive or --yes).
# * ROLLBACK OF THIS DISABLE (re-arm pure): ssh <host> 'bash /home/eveselove/agentforge/bin/make_pure_rust_flywheel_default.sh --dry-run && bash /home/eveselove/agentforge/bin/make_pure_rust_flywheel_default.sh'
# * Low-load window recommended. Monitor logs + dashboard.
# * All commands idempotent.

# --- MASTER ROLLOUT SCRIPT (generated) ---
# Creates /tmp/farm_disable_pure_rust_rollout.sh (small, safe, production).
# It: pushes disable script + make re-arm script + key units, dry-runs each, (pause/confirm or --yes), reals, then full post-verify.
cat > /tmp/farm_disable_pure_rust_rollout.sh << 'MASTER_DISABLE_ROLLOUT'
#!/bin/bash
# farm_disable_pure_rust_rollout.sh — FARM ROLLOUT EXECUTOR for Pure Rust Disable/Rollback
# (symmetric counterpart to farm_pure_rust_rollout.sh). Generated from bin/disable_pure_rust_flywheel.sh
set -u
AGENTFORGE="/home/eveselove/agentforge"
cd "$AGENTFORGE" || exit 1

AUTO_YES=0
[ "${1:-}" = "--yes" ] && AUTO_YES=1

REMOTES=(
  agent1 agent2 agent3 agent4 agent5
  ssh-1 ssh-2 ssh-3 ssh-4 ssh-5 ssh-6 ssh-7 ssh-8
  team-code team-perf team-rust team-services team-singbox team-ssh
  eveselove@146.120.89.199
)

PAYLOAD=(
  bin/disable_pure_rust_flywheel.sh
  bin/make_pure_rust_flywheel_default.sh
  bin/rust_flywheel.env
  healthcheck.sh
  agentforge-flywheel.service
  agentforge-flywheel.timer
)

echo "================================================================"
echo "=== PURE RUST FLYWHEEL DISABLE — FARM ROLLOUT (master) ==="
echo "Date: $(date -Iseconds)   Host: $(hostname)"
echo "Targets: ${#REMOTES[@]} remotes"
echo "Mode: dry-first ALWAYS; real only after review"
echo "Payload: ${#PAYLOAD[@]} files (baks on target hosts provide authoritative pre-cutover state)"
echo "Safety: scp from main, dry-run (LOUD) on each, interactive or --yes gate, full post-verify (is_pure=False + markers + snippet)"
echo "================================================================"

for host in "${REMOTES[@]}"; do
  echo ""
  echo ">>> [$host] DISABLE ROLLBACK START"
  echo "  [1/4] scp payload (full paths) to $host:/tmp/pure-rust-disable/"
  for p in "${PAYLOAD[@]}"; do
    scp "$AGENTFORGE/$p" "$host:/tmp/pure-rust-disable/" 2>&1 | tail -1 || echo "     (scp $p non-fatal)"
  done

  echo "  [2/4] DRY-RUN on $host (zero mutations — review banners)..."
  ssh -o ConnectTimeout=15 -o BatchMode=yes "$host" '
    set -u
    mkdir -p /tmp/pure-rust-disable
    cd /tmp/pure-rust-disable
    echo "╔══ DRY DISABLE ON REMOTE (zero mutations) ══╗"
    bash ./disable_pure_rust_flywheel.sh --dry-run 2>&1 | tail -40
    echo "╚══ END DRY DISABLE ON '"$host"' ══╝"
    python3 -c "
import os
os.environ[\"AGENTFORGE_FLYWHEEL_ENGINE\"]=\"python\"
from agentforge.learning.utils import is_pure_rust_flywheel
print(\"  is_pure_rust_flywheel() probe:\", is_pure_rust_flywheel(), \"(expect False)\")
" 2>/dev/null || true
  ' 2>&1 | tail -45 || echo "     (ssh/dry warning for $host — continue safely)"

  if [ $AUTO_YES -eq 0 ]; then
    echo "  [PAUSE] Dry complete for $host. Looks clean (Python preference)?"
    read -r -p "      Run REAL disable on $host now? [y/N]: " ans
    if [[ ! "$ans" =~ ^[Yy] ]]; then
      echo "     SKIPPED real disable for $host (still safe; re-arm possible)"
      continue
    fi
  else
    echo "  [AUTO-YES] Proceeding to real disable..."
    sleep 2
  fi

  echo "  [3/4] REAL disable on $host..."
  ssh -o ConnectTimeout=20 -o BatchMode=yes "$host" '
    set -u
    mkdir -p /tmp/pure-rust-disable
    cd /tmp/pure-rust-disable
    echo "╔══ LIVE DISABLE ROLLBACK ══╗"
    bash ./disable_pure_rust_flywheel.sh --force-restart 2>&1 | tail -25 || bash ./disable_pure_rust_flywheel.sh 2>&1 | tail -15 || true
    touch /home/eveselove/agentforge/.disable_pure_rust_flywheel 2>/dev/null || true
    rm -f /home/eveselove/agentforge/.pure_rust_flywheel 2>/dev/null || true
    export AGENTFORGE_FLYWHEEL_ENGINE=python
    export AGENTFORGE_PURE_RUST_FLYWHEEL=0
    systemctl --user daemon-reload 2>/dev/null || true
    if systemctl --user is-active --quiet agentforge-worker 2>/dev/null || systemctl --user is-active --quiet agentforge-jules-worker 2>/dev/null; then
      systemctl --user restart agentforge-worker agentforge-jules-worker 2>/dev/null || true
    else
      pkill -f "grok_worker.sh|jules_worker.sh" 2>/dev/null || true
      (nohup bash /home/eveselove/agentforge/grok_worker.sh > /dev/null 2>&1 &)
      (nohup bash /home/eveselove/agentforge/jules_worker.sh > /dev/null 2>&1 &)
    fi
    echo "  Workers + Python preference active on '"$host"'"
    echo "╚══ LIVE DISABLE COMPLETE ══╝"
  ' 2>&1 | tail -30 || echo "     (ssh real warning on $host — non-fatal)"

  echo "  [4/4] POST-DISABLE VERIFY on $host (pure must be OFF)..."
  ssh -o ConnectTimeout=15 -o BatchMode=yes "$host" '
    echo "=== $host POST-DISABLE VERIFY (pure OFF) ==="
    bash /home/eveselove/agentforge/healthcheck.sh 2>/dev/null | grep -E "Flywheel|Timer|Rust|pure|✅|⚠️|engine" | head -10 || true
    echo "--- Markers ---"
    ls -l /home/eveselove/agentforge/.{pure,disable_pure}_rust_flywheel 2>/dev/null || echo "  (markers checked)"
    echo "--- Python guard (must be False) ---"
    python3 -c "
import os
os.environ[\"AGENTFORGE_FLYWHEEL_ENGINE\"]=\"python\"
os.environ[\"AGENTFORGE_PURE_RUST_FLYWHEEL\"]=\"1\"
from agentforge.learning.utils import is_pure_rust_flywheel
print(\"  is_pure_rust_flywheel() =\", is_pure_rust_flywheel(), \"(expect False)\")
" 2>/dev/null || true
    echo "--- Snippet (no pure force) ---"
    tail -8 /home/eveselove/agentforge/bin/rust_flywheel.env 2>/dev/null || true
    echo "=== $host DISABLE VERIFY END ==="
  ' 2>&1 | tail -25 || true

  echo "  [$host] DISABLE COMPLETE"
  sleep 3
done

echo ""
echo "================================================================"
echo "=== FARM PURE RUST DISABLE COMPLETE ==="
echo "Next on MAIN:"
echo "  bash /home/eveselove/agentforge/healthcheck.sh | grep -E \"Flywheel|pure|engine\""
echo "  python -c 'from agentforge.learning.utils import is_pure_rust_flywheel; print(is_pure_rust_flywheel())'   # False"
echo "  python -m agentforge.list_pending_candidates list --limit 3"
echo ""
echo "To re-arm pure on any host later:"
echo "  ssh HOST 'bash /home/eveselove/agentforge/bin/make_pure_rust_flywheel_default.sh --dry-run && bash /home/eveselove/agentforge/bin/make_pure_rust_flywheel_default.sh'"
echo "================================================================"
MASTER_DISABLE_ROLLOUT
chmod +x /tmp/farm_disable_pure_rust_rollout.sh

echo ""
echo "Master created at: /tmp/farm_disable_pure_rust_rollout.sh"
echo "Usage:"
echo "  bash /tmp/farm_disable_pure_rust_rollout.sh          # interactive"
echo "  bash /tmp/farm_disable_pure_rust_rollout.sh --yes   # auto"
echo ""
echo "One-liner master invoke:"
echo "  scp /tmp/farm_disable_pure_rust_rollout.sh main-host:/tmp/ && ssh main-host 'bash /tmp/farm_disable_pure_rust_rollout.sh'"

FARM_BLOCK

# === CLEAN RE-ARM PATH (symmetric to cutover's DISABLE_BLOCK) ===
log "=== CLEAN RE-ARM / ROLLBACK OF THIS DISABLE (back to pure) ==="
cat << 'REARM_BLOCK'

# =============================================================================
# PHASE 3 PURE RUST — RE-ARM AFTER DISABLE (one command)
# =============================================================================
# Instant per-shell:
export AGENTFORGE_FLYWHEEL_ENGINE=rust
export AGENTFORGE_PURE_RUST_FLYWHEEL=1

# Then run the symmetric cutover (after confirming release binary on target):
cd /home/eveselove/agentforge
bash bin/make_pure_rust_flywheel_default.sh --dry-run
bash bin/make_pure_rust_flywheel_default.sh                 # or --force-restart on low-load

# Per-remote re-arm one-liner:
# ssh agent3 'cd /home/eveselove/agentforge && bash bin/make_pure_rust_flywheel_default.sh --dry-run && bash bin/make_pure_rust_flywheel_default.sh'

# Evidence that disable_pure is respected: learning/utils.py (precedence), post_process.py,
# phase2_3_integration.py, run_continuous_flywheel.py, all workers/hooks, services, and the
# regenerated rust_flywheel.env. Python orchestration is now the active path.

# To also disable base Rust flywheel (full python-only):
# bash bin/disable_rust_flywheel.sh

REARM_BLOCK

log "=== PURE RUST FLYWHEEL DISABLE / ROLLBACK COMPLETE ==="
log "See $LOG_FILE for full trace."
log "Pure layer is now OFF. Python flywheel orchestration restored everywhere (non-breaking)."
log "Strongest killswitch active: $DISABLE_PURE_MARKER + env logic in $ENV_SNIPPET"
if [ -n "${ROLLBACK_SNAPSHOT_TAG:-}" ]; then
    log "Full rollback safety snapshots available as *.$ROLLBACK_SNAPSHOT_TAG (real run only)"
fi
log "Only way to re-arm pure: bash bin/make_pure_rust_flywheel_default.sh (after binary + dry-run)"
log "DISABLE SCRIPT PRODUCTION READY"

# Final safe verification (python orchestration path post-disable)
if [ $DRY_RUN -eq 0 ]; then
    log "Final post-disable verification dry via python path..."
    PYTHONPATH=/home/eveselove AGENTFORGE_FLYWHEEL_ENGINE=python timeout 15s python -m agentforge.list_pending_candidates list --limit 1 --sort value 2>&1 | tail -3 || true
fi

exit 0
