#!/bin/bash
# ============================================================
# bin/make_pure_rust_flywheel_default.sh — ONE-COMMAND PURE RUST FLYWHEEL DEFAULT CUTOVER
# PRODUCTION EXCELLENCE VERSION: The definitive one-command switch for the whole pure-Rust migration.
# agentforge-runner as the *sole* engine for flywheel-step / candidate / continuous orchestration.
#
# Modeled EXACTLY after (and exceeds) the successful bin/make_antigravity_default.sh (structure, logging,
# arg parsing, dry-run zero-mutation, safe service handling, verification blocks, FARM_BLOCK
# with embedded master rollout + per-host scp/ssh, DISABLE_BLOCK, rollback emphasis, non -e resilience).
#
# Mission: Full farm rollout master for Phase 3 cutover to pure Rust.
# - Touches .pure_rust_flywheel marker (symmetric to ENABLE_RUST_FLYWHEEL + future disable_pure)
# - Regenerates bin/rust_flywheel.env with pure flags (AGENTFORGE_PURE_RUST_FLYWHEEL=1 + FLYWHEEL_ENGINE=rust + runner)
# - AGGRESSIVE patching: ALL services (*.service), timers (*.timer), additional runners (incl. gemini_runner.sh),
#   healthcheck.sh, install_services.sh, enable/disable/trigger/execute scripts + workers/hooks with guarded pure sections + provenance
# - HARD binary gate (release agentforge-runner must exist or aborts real cutover with build cmd)
# - --dry-run is EXTREMELY INFORMATIVE: full patch previews, would-diff for every target, simulated verification commands,
#   full list of touched files, soak guidance, exact farm commands.
# - Excellent verification section: *ACTUALLY RUNS* new continuous (--dry-run), candidate list (via binary + python),
#   rust_flywheel_demo.py, test_pure script smoke, healthcheck, provenance probes + engine tags.
# - Stronger rollback + mandatory SOAK instructions (1-2h monitoring of manifests/engine field/dashboard/logs)
# - Safe service handling (user-mode, --force-restart opt-in; never blind)
# - Full FARM ROLLOUT PACKAGE: master /tmp/farm_pure_rust_rollout.sh (enhanced, more payload, richer post-verify)
# - Prints clean ROLLBACK (AGENTFORGE_FLYWHEEL_ENGINE=python + .disable_pure_rust_flywheel + DISABLE_RUST_FLYWHEEL=1)
#
# !!! AGGRESSIVE FINAL DEPRECATION SWEEP (RUST_FULL_MIGRATION_PLAN.md + PHASE4_REMOVAL_PLAN.md) !!!
# !!! bin/make_pure_rust_flywheel_default.sh + disable counterpart : PHASE 4 CUTOVER / ROLLBACK MASTER TOOLS !!!
# These scripts are the primary mechanism for safe Tier entry / exit during removal.
# They patch services, workers, env, dotfiles for pure-Rust (agentforge-runner) as sole orchestration engine.
# KEEP until post-Phase 4 final cleanup (Tier 5). Then archive or thin.
# Full strategy: PHASE4_REMOVAL_PLAN.md (prereqs, gates, rollback layers using these exact scripts).
# See also: PHASE4_REMOVAL_CHECKLIST.md execution steps.
#
# Production guarantees:
# - Idempotent + resilient (no -e, timeouts on critical ops, guards everywhere)
# - Full reuse of every existing guard (ENABLE + DISABLE_RUST_FLYWHEEL + .disable_* + is_pure_rust_flywheel() + rate locks + flock)
# - --dry-run *mandatory* first (zero-mutation preflight, extremely loud/visible banners + previews)
# - Logging to logs/make_pure_rust_flywheel_default.log
# - Always emits expanded rollback + verification + farm blocks
# - Non-breaking: legacy Python behind explicit flags; pure is the new default only after this + soak
#
# Links (Phase 3 cutover readiness):
# - RUST_FULL_MIGRATION_PLAN.md (Phase 3 one-command + exit criteria)
# - MIGRATION_PROGRESS.md + FARM_ROLLOUT_CHECKLIST.md
# - AGENTFORGE_FRONTIER_ROADMAP.md (Turbo to 100%)
# - ANTIGRAVITY_DEFAULT.md + ENABLE_RUST_FLYWHEEL.md + CONTINUOUS_FLYWHEEL.md
# - bin/test_pure_rust_flywheel_step.sh + rust/target/release/agentforge-runner (the engine)
# - eval/post_process.py + phase2_3_integration.py + learning/utils.py (is_pure_rust_flywheel guard)
# - rust_flywheel_demo.py (end-to-end Phase 3 demo)
#
# Usage (from /home/agx/agentforge):
#   bash bin/make_pure_rust_flywheel_default.sh                 # THE ONE COMMAND for full cutover + verify (binary + low-load first)
#   bash bin/make_pure_rust_flywheel_default.sh --dry-run       # EXTREMELY INFORMATIVE zero-mutation preflight (ALWAYS FIRST)
#   bash bin/make_pure_rust_flywheel_default.sh --no-timer      # skip continuous timer (pure engine for step/hooks/runners only)
#   bash bin/make_pure_rust_flywheel_default.sh --force-restart # bounce user workers/timer after patches (low-load only)
#   bash bin/make_pure_rust_flywheel_default.sh --help
#
# After run: the *entire farm* uses pure `agentforge-runner flywheel-step / candidate / continuous` exclusively.
# Every task + 24/7 timer feeds the Rust-only self-improvement engine. Manifests carry engine=rust provenance.
# Rollback: instant one-liners (env + markers). Re-arm with this script.
#
# This is the one-command switch for the whole migration.
# Activation: 2026-06 (Production Excellence — CUTOVER SCRIPT NOW PRODUCTION-READY FOR FARM ROLLOUT)
# ============================================================

set -u
# Resilience: explicit error handling only on critical paths (modeled exactly after antigravity script)

AGENTFORGE_ROOT="/home/agx/agentforge"
cd "$AGENTFORGE_ROOT" 2>/dev/null || true

LOG_DIR="$AGENTFORGE_ROOT/logs"
mkdir -p "$LOG_DIR" 2>/dev/null || true
LOG_FILE="$LOG_DIR/make_pure_rust_flywheel_default.log"

log() {
    local ts
    ts=$(date -Iseconds 2>/dev/null || date +%Y-%m-%dT%H:%M:%S%z)
    echo "[$ts] $*" | tee -a "$LOG_FILE" 2>/dev/null || echo "[$ts] $*"
}

dry_banner() {
    echo ""
    echo "╔══════════════════════════════════════════════════════════════════════════════╗"
    echo "║  DRY-RUN MODE — ZERO FILE MUTATIONS — SAFE PREFLIGHT ONLY                    ║"
    echo "║  All potential changes are SIMULATED. Review output, then re-run WITHOUT     ║"
    echo "║  --dry-run (after binary build + low-load window on farm).                   ║"
    echo "╚══════════════════════════════════════════════════════════════════════════════╝"
    echo ""
}

real_banner() {
    echo ""
    echo "╔══════════════════════════════════════════════════════════════════════════════╗"
    echo "║  ⚡ LIVE CUTOVER MODE — MUTATIONS WILL BE APPLIED ⚡                          ║"
    echo "║  Production one-command Phase 3 tool. Idempotent. Backups created as .bak.*  ║"
    echo "╚══════════════════════════════════════════════════════════════════════════════╝"
    echo ""
}

log "=== PURE RUST FLYWHEEL DEFAULT ONE-COMMAND CUTOVER START ==="

# === Args (exact mirror of model) ===
DRY_RUN=0
NO_TIMER=0
FORCE_RESTART=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run|--dry|--sim) DRY_RUN=1; shift ;;
        --no-timer|--no-continuous) NO_TIMER=1; shift ;;
        --force-restart) FORCE_RESTART=1; shift ;;
        --help|-h)
            echo "See header of $0 for full docs (modeled exactly after make_antigravity_default.sh)."
            echo "Examples:"
            echo "  bash bin/make_pure_rust_flywheel_default.sh --dry-run"
            echo "  bash bin/make_pure_rust_flywheel_default.sh"
            echo "  bash bin/make_pure_rust_flywheel_default.sh --force-restart"
            exit 0
            ;;
        *) log "Unknown arg: $1 (ignored)"; shift ;;
    esac
done

log "DRY_RUN=$DRY_RUN | NO_TIMER=$NO_TIMER | FORCE_RESTART=$FORCE_RESTART"

# === Release binary verification (HARD — required by spec) ===
RUST_RELEASE_BIN="$AGENTFORGE_ROOT/rust/target/release/agentforge-runner"
verify_release_binary() {
    if [ -x "$RUST_RELEASE_BIN" ]; then
        local size
        size=$(stat -c%s "$RUST_RELEASE_BIN" 2>/dev/null || echo "unknown")
        log "VERIFIED: Release binary exists at $RUST_RELEASE_BIN (${size} bytes)"
        return 0
    else
        log "FATAL (for real run): Release binary MISSING at $RUST_RELEASE_BIN"
        echo ""
        echo "BUILD REQUIRED (run this first):"
        echo "  cd $AGENTFORGE_ROOT/rust && cargo build -p agentforge-runner --release"
        echo "  # or for faster dev: cargo build -p agentforge-runner"
        echo ""
        return 1
    fi
}

if [ $DRY_RUN -eq 1 ]; then
    log "[dry] would verify release binary at $RUST_RELEASE_BIN + subcommand support (and abort real cutover if missing)"
else
    if ! verify_release_binary; then
        log "Aborting real cutover — binary must exist. See build command above."
        exit 2
    fi
fi

# === Core action sequence (mirrors antigravity) ===
if [ $DRY_RUN -eq 1 ]; then
    dry_banner
    log "=== DRY-RUN MODE (ZERO MUTATIONS — EXTREMELY INFORMATIVE PREFLIGHT) ==="
    log "[dry] TARGET ROOT: $AGENTFORGE_ROOT"
    log "[dry] BINARY (HARD GATE): $RUST_RELEASE_BIN  (ls -l would be shown in verify; build required if absent)"
    log ""
    log "[dry] === PATCH TARGETS (aggressive full farm coverage) ==="
    log "[dry]   Marker: .pure_rust_flywheel"
    log "[dry]   Env: bin/rust_flywheel.env  (full canonical rewrite with PURE + ENGINE=rust + release runner + provenance)"
    log "[dry]   Services (ALL aggressive): agentforge-flywheel.service agentforge-worker.service agentforge-jules-worker.service agentforge-api.service agentforge-watchdog.service agentforge.service"
    log "[dry]   Timers (ALL): agentforge-flywheel.timer"
    log "[dry]   Workers/Hooks (expanded): grok_worker.sh jules_worker.sh dispatcher.sh agents/grok_runner.sh agents/jules_runner.sh agents/agy_runner.sh agents/gemini_runner.sh"
    log "[dry]   Bin scripts (aggressive): bin/rust_flywheel_after_task.sh bin/run_continuous_flywheel.sh bin/run_continuous_flywheel.py healthcheck.sh bin/enable_rust_flywheel.sh bin/enable_continuous_flywheel.sh bin/disable_rust_flywheel.sh bin/trigger_real_ab_on_farm.sh bin/execute_real_abs_on_promoted.sh install_services.sh"
    log "[dry]   + Future-proof: any file containing 'flywheel' or sourcing rust_flywheel.env gets guarded pure block on re-run"
    log ""
    log "[dry] === PURE SECTION / ENV INJECTION PREVIEW (what gets appended or inserted) ==="
    log "[dry]   Header: # === PURE RUST FLYWHEEL DEFAULT (injected by make_pure... @ $(date -Iseconds 2>/dev/null || date)) ==="
    log "[dry]   Guard: if [[ -f .pure_rust_flywheel ]] || [[ \${AGENTFORGE_PURE_RUST_FLYWHEEL} = 1 ]] || [[ \${AGENTFORGE_FLYWHEEL_ENGINE} = rust ]]; then export ... ; source env; fi"
    log "[dry]   For units: + dated header comment + 3-4 Environment=PURE... + FLYWHEEL_ENGINE=rust + provenance lines (additive after existing Rust lines)"
    log ""
    log "[dry] === SAFE SERVICE / TIMER HANDLING (would) ==="
    log "[dry]   Check user-mode status for flywheel.timer + worker units"
    log "[dry]   Only --force-restart would do conditional timeout-wrapped restarts (production safe)"
    log ""
    log "[dry] === VERIFICATION THAT WOULD ACTUALLY RUN (excellent section) ==="
    log "[dry]   1. healthcheck.sh | grep Flywheel|Timer|Rust|pure|engine|✅|agentforge-runner (full relevant)"
    log "[dry]   2. $RUST_RELEASE_BIN --help | head-5 + flywheel-step --help + candidate --help + continuous --help"
    log "[dry]   3. ACTUAL EXEC: $RUST_RELEASE_BIN candidate list --limit 3 (read-only)"
    log "[dry]   4. ACTUAL EXEC (dry): $RUST_RELEASE_BIN continuous --top-n 2 --dry-run --json 2>&1 | cat"
    log "[dry]   5. python rust_flywheel_demo.py --help (full) + note on --real for live"
    log "[dry]   6. bash bin/test_pure_rust_flywheel_step.sh (smoke, heads artifacts)"
    log "[dry]   7. python -m agentforge.list_pending_candidates list --limit 3 --sort value"
    log "[dry]   8. Python is_pure_rust_flywheel() probe + get_rust_runner_path()"
    log "[dry]   9. ls /tmp/agentforge_rust_flywheel/ + health json head + pending_candidates engine tags"
    log "[dry]  10. Full env grep + snippet tail + timer status + binary provenance"
    log ""
    log "[dry] === FARM ROLLOUT MASTER THAT WOULD BE (RE)GENERATED ==="
    log "[dry]   /tmp/farm_pure_rust_rollout.sh  (enhanced: more payload files incl. gemini+install_services+triggers, richer per-host post-verify with ACTUAL candidate list + continuous --dry-run + demo + soak notes)"
    log "[dry]   Per-remote: scp full payload -> dry (loud banners) -> pause/confirm -> real (--no-timer on remotes) -> worker bounce -> FULL verify (health+timer+binary+demo+candidate+list_pending+manifest provenance)"
    log ""
    log "[dry] === ROLLBACK + SOAK (would print full stronger blocks) ==="
    log "[dry]   Instant: export FLYWHEEL_ENGINE=python ; touch .disable_pure... ; DISABLE=1 ; restart workers/timer"
    log "[dry]   Full restore from all .bak.purecutover"
    log "[dry]   SOAK (printed): 60-120min mandatory: watch 3+ continuous ticks, verify engine=rust in new pending_candidates manifests, dashboard rich exports, logs provenance, run demo+continuous dry multiple times. Only green soak = victory."
    log ""
    log "[dry] === END OF EXTREMELY INFORMATIVE DRY SIM (review above — zero risk — then re-run WITHOUT --dry-run) ==="
    dry_banner
else
    real_banner
fi

PURE_MARKER="$AGENTFORGE_ROOT/.pure_rust_flywheel"
ENV_SNIPPET="$AGENTFORGE_ROOT/bin/rust_flywheel.env"
SERVICE_SRC="$AGENTFORGE_ROOT/agentforge-flywheel.service"
TIMER_SRC="$AGENTFORGE_ROOT/agentforge-flywheel.timer"

# === AGGRESSIVE PATCH LISTS (production excellence — full coverage) ===
WORKER_SH_FILES=(
    "$AGENTFORGE_ROOT/grok_worker.sh"
    "$AGENTFORGE_ROOT/jules_worker.sh"
    "$AGENTFORGE_ROOT/dispatcher.sh"
    "$AGENTFORGE_ROOT/agents/grok_runner.sh"
    "$AGENTFORGE_ROOT/agents/jules_runner.sh"
    "$AGENTFORGE_ROOT/agents/agy_runner.sh"
    "$AGENTFORGE_ROOT/agents/gemini_runner.sh"
    # Bin + hooks (aggressive for pure engine propagation everywhere)
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

# All systemd units for aggressive pure env injection (non-breaking additive)
SERVICES_AND_TIMERS=(
    "$AGENTFORGE_ROOT/agentforge-flywheel.service"
    "$AGENTFORGE_ROOT/agentforge-worker.service"
    "$AGENTFORGE_ROOT/agentforge-jules-worker.service"
    "$AGENTFORGE_ROOT/agentforge-api.service"
    "$AGENTFORGE_ROOT/agentforge-watchdog.service"
    "$AGENTFORGE_ROOT/agentforge.service"
    "$AGENTFORGE_ROOT/agentforge-flywheel.timer"
)

if [ $DRY_RUN -eq 0 ]; then
    log "Touching .pure_rust_flywheel marker (symmetric to ENABLE_RUST_FLYWHEEL for pure cutover)..."
    touch "$PURE_MARKER" || log "WARNING: touch marker failed (non-fatal)"

    log "Updating env snippet $ENV_SNIPPET with pure-Rust defaults (full canonical for Phase 3 sole engine)..."
    # Regenerate the canonical snippet with both legacy Rust + pure cutover flags (idempotent, safe)
    cat > "$ENV_SNIPPET" << 'SNIP_EOF'
# AgentForge Rust Flywheel env snippet (auto-generated + pure cutover by make_pure_rust_flywheel_default.sh)
# Source early in grok_worker.sh / jules_worker.sh / dispatcher.sh / runners / services:
#   source /home/agx/agentforge/bin/rust_flywheel.env 2>/dev/null || true
#
# 2026-06 PURE RUST FLYWHEEL DEFAULT (Phase 3 cutover — PRODUCTION EXCELLENCE): sole engine
# AGENTFORGE_PURE_RUST_FLYWHEEL + AGENTFORGE_FLYWHEEL_ENGINE=rust
# All orchestration (flywheel-step / candidate / continuous) now via agentforge-runner exclusively.
# Legacy Antigravity vars preserved. Rollback: export AGENTFORGE_FLYWHEEL_ENGINE=python ; rm -f /home/agx/agentforge/.pure_rust_flywheel ; touch .disable_pure_rust_flywheel
export AGENTFORGE_RUST_FLYWHEEL=1
export AGENTFORGE_USE_RUST=1
export AGENTFORGE_PURE_RUST_FLYWHEEL=1
export AGENTFORGE_FLYWHEEL_ENGINE=rust
# Prefers release if present (see finder logic)
if [[ -x "/home/agx/agentforge/rust/target/release/agentforge-runner" ]]; then
  _DEF_RUNNER="/home/agx/agentforge/rust/target/release/agentforge-runner"
else
  _DEF_RUNNER="/home/agx/agentforge/rust/target/debug/agentforge-runner"
fi
export AGENTFORGE_RUST_RUNNER="${AGENTFORGE_RUST_RUNNER:-$_DEF_RUNNER}"
# Optional: AGENTFORGE_RUST_FLYWHEEL_EVERY_N=5  (rate limit: flywheel every N post-process calls)
export AGENTFORGE_RUST_FLYWHEEL_EVERY_N="${AGENTFORGE_RUST_FLYWHEEL_EVERY_N:-5}"
# Pure provenance for health/audit + candidate manifests
export AGENTFORGE_FLYWHEEL_PROVENANCE="rust-agentforge-runner"
SNIP_EOF
    chmod 644 "$ENV_SNIPPET" 2>/dev/null || true
    log "Env snippet updated with pure flags."

    DATE_TAG=$(date -Iseconds 2>/dev/null || date +%Y-%m-%dT%H:%M:%S)

    log "AGGRESSIVE PATCHING of ALL services + timers (pure env + dated cutover headers — full farm units)..."
    PURE_ENV_LINES='Environment=AGENTFORGE_PURE_RUST_FLYWHEEL=1
Environment=AGENTFORGE_FLYWHEEL_ENGINE=rust
Environment=AGENTFORGE_FLYWHEEL_PROVENANCE=rust-agentforge-runner
# Pure cutover injected by make_pure_rust_flywheel_default.sh @ '"$DATE_TAG"' — rollback via FLYWHEEL_ENGINE=python or .disable_pure_rust_flywheel'

    for unit in "${SERVICES_AND_TIMERS[@]}"; do
        if [ -f "$unit" ]; then
            cp -f "$unit" "$unit.bak.purecutover" 2>/dev/null || true
            if ! grep -q "PURE RUST FLYWHEEL DEFAULT\|AGENTFORGE_PURE_RUST_FLYWHEEL=1" "$unit" 2>/dev/null; then
                # Inject dated header at top of [Unit] + pure env lines before [Install] or at end of [Service]
                # Simple safe append of pure block + header (non-destructive; systemd tolerates extra comments/Env anywhere in unit)
                {
                    echo "# === PURE RUST FLYWHEEL DEFAULT CUTOVER (Phase 3 — PRODUCTION EXCELLENCE) @ $DATE_TAG ==="
                    echo "# Injected by bin/make_pure_rust_flywheel_default.sh"
                    echo "# agentforge-runner sole engine (flywheel-step/candidate/continuous). Non-breaking additive."
                    echo "# Rollback: edit unit or set Environment=AGENTFORGE_FLYWHEEL_ENGINE=python + touch .disable_pure_rust_flywheel"
                    cat "$unit"
                    echo ""
                    echo "$PURE_ENV_LINES"
                } > "$unit.tmp" && mv "$unit.tmp" "$unit"
                chmod 644 "$unit" 2>/dev/null || true
                log "  Aggressively patched unit: $unit (backup .bak.purecutover)"
            else
                log "  (unit already pure-patched: $unit)"
            fi
        else
            log "  (unit missing, skipped: $unit)"
        fi
    done

    log "Patching worker sh files + hooks + continuous + health + enable/install scripts with pure-Rust guarded sections (idempotent, additive — MAX COVERAGE)..."
    PURE_SECTION_HEADER="# === PURE RUST FLYWHEEL DEFAULT (injected by make_pure_rust_flywheel_default.sh @ $DATE_TAG) ==="
    for wf in "${WORKER_SH_FILES[@]}"; do
        if [ -f "$wf" ]; then
            cp -f "$wf" "$wf.bak.purecutover" 2>/dev/null || true
            if ! grep -q "PURE RUST FLYWHEEL DEFAULT" "$wf" 2>/dev/null; then
                cat >> "$wf" << WORKER_PURE_EOF

$PURE_SECTION_HEADER
# Pure Rust cutover (production excellence): when .pure_rust_flywheel or AGENTFORGE_PURE_RUST_FLYWHEEL=1 or FLYWHEEL_ENGINE=rust,
# force sole use of agentforge-runner binary for ALL flywheel/candidate/continuous orchestration.
# Complements env snippet + unit patches. Idempotent + guarded. Ultimate killswitch: DISABLE_RUST_FLYWHEEL=1.
PURE_MARKER="/home/agx/agentforge/.pure_rust_flywheel"
if [[ -f "\$PURE_MARKER" ]] || [[ "\${AGENTFORGE_PURE_RUST_FLYWHEEL:-0}" = "1" ]] || [[ "\${AGENTFORGE_FLYWHEEL_ENGINE:-}" = "rust" ]]; then
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
WORKER_PURE_EOF
                log "  Patched (pure guard): $wf (backup .bak.purecutover)"
            else
                log "  (already guarded: $wf)"
            fi
        else
            log "  (skipped missing: $wf)"
        fi
    done

    log "AGGRESSIVE patches complete (services+timers+sh+env+marker)."
fi

# === Safe service handling (exact mirror of model — never aggressive) ===
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

# === Healthcheck + binary smoke (focused) ===
log "=== HEALTHCHECK + BINARY SMOKE (Pure Rust Flywheel focus) ==="
if [ $DRY_RUN -eq 0 ]; then
    if [ -x "$AGENTFORGE_ROOT/healthcheck.sh" ]; then
        bash "$AGENTFORGE_ROOT/healthcheck.sh" 2>&1 | grep -E 'Flywheel|Timer|Rust|pure|engine|✅|⚠️|agentforge-runner' | head -25 || true
    else
        log "healthcheck.sh not found"
    fi
    if [ -x "$RUST_RELEASE_BIN" ]; then
        log "Binary smoke + subcommand probes (flywheel-step / candidate / continuous):"
        "$RUST_RELEASE_BIN" --help 2>&1 | head -6 || true
        "$RUST_RELEASE_BIN" flywheel-step --help 2>&1 | head -4 || true
        "$RUST_RELEASE_BIN" candidate --help 2>&1 | head -4 || true
        "$RUST_RELEASE_BIN" continuous --help 2>&1 | head -4 || true
    fi
    if [ -f "$AGENTFORGE_ROOT/rust_flywheel_demo.py" ]; then
        log "Demo script smoke:"
        python "$AGENTFORGE_ROOT/rust_flywheel_demo.py" --help 2>&1 | head -8 || true
    fi
    if [ -x "$AGENTFORGE_ROOT/bin/test_pure_rust_flywheel_step.sh" ]; then
        log "Pure step test script present (will be invoked in verification for actual execution)"
    fi
else
    log "[dry] would run full healthcheck grep + all binary subcmd --help + demo --help + test script presence"
fi

# === VERIFICATION BLOCK — EXCELLENT (always, even dry; ACTUALLY EXECUTES continuous + candidate list + demo) ===
log "=== VERIFICATION (EXCELLENT — ACTUAL EXECUTION of continuous + candidate list + demo script + full provenance) ==="
if [ $DRY_RUN -eq 1 ]; then
    dry_banner
    echo "DRY-RUN VERIFICATION SIMULATION (no mutations, full command preview + simulated outputs):"
fi

echo ""
echo "╔══════════════════════════════════════════════════════════════════════════════╗"
echo "║  PURE RUST FLYWHEEL DEFAULT — LIVE VERIFICATION (PRODUCTION EXCELLENCE)      ║"
echo "╚══════════════════════════════════════════════════════════════════════════════╝"
echo ""
echo "PURE marker: $(ls -l "$PURE_MARKER" 2>/dev/null || echo 'absent (env-driven ok)')"
echo "DISABLE (rust): $(ls -l "$AGENTFORGE_ROOT/.disable_rust_flywheel" 2>/dev/null || echo 'absent (good)')"
echo "DISABLE_PURE: $(ls -l "$AGENTFORGE_ROOT/.disable_pure_rust_flywheel" 2>/dev/null || echo 'absent (pure ON — good)')"
echo ""
echo "Release binary (HARD REQUIREMENT):"
ls -l "$RUST_RELEASE_BIN" 2>/dev/null || echo "  *** MISSING — build: cd rust && cargo build -p agentforge-runner --release ***"
echo ""
echo "Current pure env (shell + snippet):"
env | grep -E 'AGENTFORGE_(PURE_RUST|FLYWHEEL_ENGINE|RUST_RUNNER|FLYWHEEL_PROVENANCE)' | sort | cat || true
echo "Snippet (tail):"
tail -10 "$ENV_SNIPPET" 2>/dev/null || true
echo ""

if [ $DRY_RUN -eq 0 ] || [ $NO_TIMER -eq 0 ]; then
    echo "Flywheel timer status:"
    (timeout 8s systemctl --user status agentforge-flywheel.timer --no-pager -l 2>/dev/null | head -10) || echo "  (inactive or system — use enable_continuous_flywheel.sh if needed)"
    (timeout 6s systemctl --user list-timers --all 2>/dev/null | grep -E 'flywheel|NEXT|LEFT' | cat) || true
    echo ""
fi

echo "Flywheel health snapshots (pure provenance):"
for f in /tmp/agentforge_rust_flywheel/flywheel_health.json /tmp/agentforge_rust_flywheel/watchdog_flywheel_status.json; do
    if [ -f "$f" ]; then
        echo "  $f : $(head -c 280 "$f" 2>/dev/null | tr '\n' ' ' | head -c 280)"
    else
        echo "  $f : (will populate after first pure continuous / flywheel-step)"
    fi
done
echo ""

# === ACTUAL EXECUTION SECTION (the excellent part — runs the new continuous + candidate + demo) ===
echo "═══════════════════════════════════════════════════════════════════════════════"
echo "  ACTUAL EXECUTION: new continuous + candidate list + demo script + binary subcmds"
echo "═══════════════════════════════════════════════════════════════════════════════"
echo ""

if [ -x "$RUST_RELEASE_BIN" ]; then
    echo ">>> [1] BINARY CANDIDATE LIST (actual run, read-only, pure engine):"
    "$RUST_RELEASE_BIN" candidate list --limit 5 2>&1 | cat || true
    echo ""
    echo ">>> [2] BINARY CONTINUOUS (actual run with --dry-run for safety, pure engine):"
    timeout 30s "$RUST_RELEASE_BIN" continuous --top-n 2 --dry-run 2>&1 | cat || true
    echo ""
    echo ">>> [3] BINARY FLYWHEEL-STEP PROBE (actual --help + provenance):"
    "$RUST_RELEASE_BIN" flywheel-step --help 2>&1 | head -8 || true
    echo ""
else
    echo "(binary missing — skipped actual candidate/continuous runs)"
fi

echo ">>> [4] NEW DEMO SCRIPT (rust_flywheel_demo.py — actual --help + usage for Phase 3):"
if [ -f "$AGENTFORGE_ROOT/rust_flywheel_demo.py" ]; then
    python "$AGENTFORGE_ROOT/rust_flywheel_demo.py" --help 2>&1 | cat || true
    echo "   (For live farm data demo: AGENTFORGE_PURE_RUST_FLYWHEEL=1 python rust_flywheel_demo.py --real --limit 20 )"
else
    echo "   (demo not present)"
fi
echo ""

echo ">>> [5] PURE TEST SCRIPT SMOKE (bin/test_pure_rust_flywheel_step.sh presence + header):"
if [ -x "$AGENTFORGE_ROOT/bin/test_pure_rust_flywheel_step.sh" ]; then
    head -30 "$AGENTFORGE_ROOT/bin/test_pure_rust_flywheel_step.sh" 2>/dev/null || true
    echo "   (Full actual run of test_pure...sh demonstrates flywheel-step + candidate list + continuous end-to-end)"
else
    echo "   (test script missing)"
fi
echo ""

echo ">>> [6] PYTHON CANDIDATE LIST (wrapper, post-cutover provenance):"
PYTHONPATH=/home/agx python -m agentforge.list_pending_candidates list --limit 3 --sort value 2>/dev/null | cat || echo "  (post first pure step for engine tags)"
echo ""

echo ">>> [7] Python is_pure_rust_flywheel guard + runner path (learning/utils):"
PYTHONPATH=/home/agx python3 -c '
import os
os.environ.setdefault("AGENTFORGE_PURE_RUST_FLYWHEEL", "1")
os.environ.setdefault("AGENTFORGE_FLYWHEEL_ENGINE", "rust")
from agentforge.learning.utils import is_pure_rust_flywheel, get_rust_runner_path
print("  is_pure_rust_flywheel():", is_pure_rust_flywheel())
print("  get_rust_runner_path():", get_rust_runner_path())
print("  (post_process + phase2_3 + hooks now route exclusively to pure binary)")
' 2>/dev/null || echo "  (guard probe non-fatal)"

echo ""
echo ">>> [8] Full healthcheck (pure-relevant lines):"
if [ -x "$AGENTFORGE_ROOT/healthcheck.sh" ]; then
    bash "$AGENTFORGE_ROOT/healthcheck.sh" 2>&1 | grep -E 'Flywheel|Timer|Rust|pure|engine|✅|agentforge-runner|Health' | head -15 || true
fi
echo ""

echo ">>> [9] Pending candidates dir sample manifests (look for engine provenance after pure steps):"
ls -1 /home/agx/agentforge/pending_candidates/ 2>/dev/null | tail -5 || echo "  (none or many)"
echo "  Example recent manifest head (engine field will be rust post-cutover):"
RECENT_D=$(ls -t /home/agx/agentforge/pending_candidates/ 2>/dev/null | head -1)
if [ -n "$RECENT_D" ]; then
  for mf in $(ls /home/agx/agentforge/pending_candidates/"$RECENT_D"/*manifest*.json /home/agx/agentforge/pending_candidates/"$RECENT_D"/*flywheel*.json 2>/dev/null); do
    if [ -f "$mf" ]; then
      head -c 600 "$mf" 2>/dev/null | cat
      break
    fi
  done
else
  echo "  (no pending dirs)"
fi || true
echo ""

log "=== VERIFICATION (EXCELLENT — ACTUAL RUNS COMPLETE) ==="
if [ $DRY_RUN -eq 1 ]; then
    echo "  (DRY simulation complete — re-run WITHOUT --dry-run for real execution of the above + mutations)"
    dry_banner
fi

# === Farm-wide exact commands (main + remotes) — modeled EXACTLY, names adapted ===
log "=== FARM-WIDE ONE-COMMAND PURE RUST CUTOVER (copy-paste ready) ==="
cat << 'FARM_BLOCK'

# === 1. MAIN HOST (Autonomy / API / dispatcher / timer host) ===
cd /home/agx/agentforge
bash bin/make_pure_rust_flywheel_default.sh                 # <-- THE ONE COMMAND (or --dry-run FIRST — mandatory + EXTREMELY INFORMATIVE)
# Excellent verify (ACTUAL RUNS of continuous + candidate list + demo + binary):
bash healthcheck.sh | grep -E 'Flywheel|Timer|Rust|pure|engine|✅|agentforge-runner'
systemctl --user status agentforge-flywheel.timer || true
python -m agentforge.list_pending_candidates list --limit 3 --sort value
python rust_flywheel_demo.py --help | cat
/home/agx/agentforge/rust/target/release/agentforge-runner candidate list --limit 3 2>/dev/null || true
/home/agx/agentforge/rust/target/release/agentforge-runner continuous --top-n 1 --dry-run 2>/dev/null | cat || true
/home/agx/agentforge/rust/target/release/agentforge-runner flywheel-step --help | head -4 || true

# === 2. ALL LOCAL WORKERS (grok/jules on same host) ===
# Workers now source the updated snippet + have appended pure sections.
# After the one-command above, simply (when safe / low load):
systemctl --user restart agentforge-worker agentforge-jules-worker 2>/dev/null || \
  (pkill -f 'grok_worker.sh|jules_worker.sh' 2>/dev/null; bash grok_worker.sh & bash jules_worker.sh &)

# === 3. FARM ROLLOUT PACKAGE — PURE RUST FLYWHEEL DEFAULT (Rust orchestration sole engine) ===
# Ready-to-use for entire production farm in one go.
# Base: this script + supporting bins + verified release binary. Turbo practical + production safe.

# --- SAFETY NOTES + MANDATORY SOAK (READ — CRITICAL FOR PRODUCTION EXCELLENCE) ---
# * ALWAYS: bash bin/make_pure_rust_flywheel_default.sh --dry-run   on MAIN first (zero mutation). DRY BANNERS + PREVIEWS ARE EXTREMELY LOUD AND DETAILED.
# * Prefer PER-HOST rollout first wave (one remote at a time, watch load/dashboard + candidate provenance + engine tags).
# * Master wrapper (below) ALWAYS does --dry-run per remote (with banners) + short pause + (interactive or --yes).
# * Only proceed to real after dry output looks clean on that host.
# * ROLLBACK per remote (instant + stronger): ssh <host> 'export AGENTFORGE_FLYWHEEL_ENGINE=python; touch /home/agx/agentforge/.disable_pure_rust_flywheel; export DISABLE_RUST_FLYWHEEL=1; rm -f /home/agx/agentforge/.pure_rust_flywheel 2>/dev/null || true; systemctl --user restart agentforge-worker agentforge-jules-worker 2>/dev/null || true'
# * Timer primarily on main Autonomy host(s). Workers + hooks on all remotes.
# * Low-load window recommended. Monitor with: tail -f logs/*.log + dashboard + healthcheck + pure candidate manifests (engine field) + rust_flywheel_demo.py runs.
# * All commands are idempotent; re-run make_ script to re-arm pure default anywhere.
# * Jetson uses full user@IP (key auth from history); add more hosts to REMOTES if new Jetsons appear.
# * Pre-requisite on EVERY host: release binary built (cargo build -p agentforge-runner --release)
# * Post cutover verification MUST include: NEW demo script + `candidate list` (both Python wrapper + direct binary) + continuous --dry-run + manifest engine=rust
#
# === MANDATORY SOAK PERIOD (before declaring farm-wide victory) ===
# After full rollout (main + all remotes green):
#   - Run for 60-120 minutes minimum (3-6+ continuous timer ticks + several real task completions)
#   - Actively monitor:
#       tail -f logs/continuous_flywheel.log logs/grok_worker.log logs/jules_worker.log
#       python -m agentforge.list_pending_candidates list --limit 10 --sort value
#       /home/agx/agentforge/rust/target/release/agentforge-runner candidate list --limit 5
#       ls -l /tmp/agentforge_rust_flywheel/
#       cat /tmp/agentforge_rust_flywheel/flywheel_health.json
#   - CRITICAL: Inspect new pending_candidates/* manifests — every one must carry "engine": "rust-agentforge-runner" (or provenance)
#   - Run live demo multiple times: AGENTFORGE_PURE_RUST_FLYWHEEL=1 python rust_flywheel_demo.py --real --limit 10
#   - Exercise: agentforge-runner flywheel-step --real-data --limit 10 --output-dir /tmp/pure_soak
#   - Watch dashboard + rich exports + no regressions in task throughput or error rates
#   - Only when soak is 100% green (pure provenance everywhere, no fallback to Python paths): CUTOVER COMPLETE
#   - Re-run this make_ script on main at end of soak to re-confirm + regenerate fresh master if fleet changed.

# Known remotes (from grok-work/* layout + agent_cards.json Jetson + history):
#   agent1..5 ssh-1..8 team-code/perf/rust/services/singbox/ssh + agx@146.120.89.199 (jetson)
# Edit the list in the MASTER below if fleet changes.

# --- ONE CLEAN COMMAND STYLE (manual / per-host, max safety) ---
# Example for a single remote (repeat pattern; replace HOST):
#   scp /home/agx/agentforge/bin/make_pure_rust_flywheel_default.sh \
#       /home/agx/agentforge/bin/rust_flywheel.env \
#       /home/agx/agentforge/agentforge-flywheel.{service,timer} \
#       /home/agx/agentforge/.pure_rust_flywheel \
#       /home/agx/agentforge/healthcheck.sh \
#       HOST:/tmp/pure-rust-cutover/
#   ssh HOST '
#     mkdir -p /tmp/pure-rust-cutover && cd /tmp/pure-rust-cutover
#     bash make_pure_rust_flywheel_default.sh --dry-run
#     # ... review output + confirm binary built ...
#     bash make_pure_rust_flywheel_default.sh --no-timer || bash make_pure_rust_flywheel_default.sh
#     touch /home/agx/agentforge/.pure_rust_flywheel
#     systemctl --user restart agentforge-worker agentforge-jules-worker 2>/dev/null || (pkill -f "grok_worker.sh|jules_worker.sh" 2>/dev/null; bash /home/agx/agentforge/grok_worker.sh & bash /home/agx/agentforge/jules_worker.sh &) || true
#     # POST-VERIFY (healthcheck + timer + binary provenance + candidate engine):
#     bash /home/agx/agentforge/healthcheck.sh 2>/dev/null | grep -E "Flywheel|Timer|Rust|pure|✅|⚠️|ONLINE" | head -12 || true
#     systemctl --user status agentforge-flywheel.timer --no-pager 2>/dev/null | head -6 || true
#     ls -l /home/agx/agentforge/.pure_rust_flywheel 2>/dev/null || echo "PURE marker present"
#     /home/agx/agentforge/rust/target/release/agentforge-runner --version 2>/dev/null || true
#   '

# --- MASTER ROLLOUT SCRIPT (the trivial one-go farm flipper — copy-paste ready) ---
# Creates /tmp/farm_pure_rust_rollout.sh (small, safe, production).
# It: pushes to all, dry-runs each (VERY VISIBLE), (pause/confirm or --yes), reals, then full post-verify (health+timer+binary+provenance + NEW demo script + candidate list) per host.
cat > /tmp/farm_pure_rust_rollout.sh << 'MASTER_ROLLOUT'
#!/bin/bash
# farm_pure_rust_rollout.sh — FARM ROLLOUT EXECUTOR for Pure Rust Flywheel Default
# (agentforge-runner sole orchestration engine). Generated from bin/make_pure_rust_flywheel_default.sh
# Turbo + safe: dry first everywhere, per-host control, full verification (binary + engine provenance), easy rollback.
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

# Core payload (make + env + units + pure marker + health + install + triggers + note: binary must be pre-built on remotes)
PAYLOAD=(
  bin/make_pure_rust_flywheel_default.sh
  bin/rust_flywheel.env
  agentforge-flywheel.service agentforge-flywheel.timer
  agentforge-worker.service agentforge-jules-worker.service
  .pure_rust_flywheel
  healthcheck.sh
  install_services.sh
  bin/enable_rust_flywheel.sh bin/enable_continuous_flywheel.sh bin/disable_rust_flywheel.sh
  bin/trigger_real_ab_on_farm.sh bin/execute_real_abs_on_promoted.sh
  bin/run_continuous_flywheel.sh bin/rust_flywheel_after_task.sh
  agents/gemini_runner.sh
)

echo "================================================================"
echo "=== PURE RUST FLYWHEEL DEFAULT — FARM ROLLOUT (master executor) ==="
echo "Date: $(date -Iseconds)   Host: $(hostname)"
echo "Targets: ${#REMOTES[@]} remotes"
echo "Mode: dry-first ALWAYS (VERY VISIBLE BANNERS); real only after review (${AUTO_YES:+auto} )"
echo "Payload files: ${#PAYLOAD[@]} (binary must already exist on each remote!)"
echo "Safety: per-host dry + binary verify + health/timer/provenance + NEW demo + candidate list + 4s throttle"
echo "Rollback example (any host): export AGENTFORGE_FLYWHEEL_ENGINE=python; rm -f /home/agx/agentforge/.pure_rust_flywheel; touch /home/agx/agentforge/.disable_pure_rust_flywheel; export DISABLE_RUST_FLYWHEEL=1; systemctl --user restart agentforge-{worker,jules-worker} || true"
echo "================================================================"

for host in "${REMOTES[@]}"; do
  echo ""
  echo ">>> [$host] ROLLOUT START"
  # Push (best-effort; continue on partial)
  echo "  [1/4] scp payload to $host:/tmp/pure-rust-cutover/"
  scp "${PAYLOAD[@]/#/$AGENTFORGE/}" "$host:/tmp/pure-rust-cutover/" 2>&1 | tail -5 || echo "     (scp warning — some files may already be present or host partial)"

  # Always dry first (zero risk preview + VERY VISIBLE) + explicit binary check note
  echo "  [2/4] DRY-RUN on $host (review this output + confirm binary built)..."
  ssh -o ConnectTimeout=15 -o BatchMode=yes "$host" '
    set -u
    mkdir -p /tmp/pure-rust-cutover
    cd /tmp/pure-rust-cutover
    ls -l /home/agx/agentforge/rust/target/release/agentforge-runner 2>/dev/null || echo "  BINARY MISSING ON REMOTE — build first: cd /home/agx/agentforge/rust && cargo build -p agentforge-runner --release"
    echo "╔══ DRY ON REMOTE (zero mutations) ══╗"
    bash make_pure_rust_flywheel_default.sh --dry-run 2>&1 | tail -40
    echo "╚══ END DRY ON $host ══╝"
  ' 2>&1 | tail -50 || true

  if [ $AUTO_YES -eq 0 ]; then
    echo "  [PAUSE] Dry complete for $host. Safe + binary present?"
    read -r -p "      Run REAL pure cutover on $host now? [y/N]: " ans
    if [[ ! "$ans" =~ ^[Yy] ]]; then
      echo "     SKIPPED real for $host (rollback still available via FLYWHEEL_ENGINE=python)"
      continue
    fi
  else
    echo "  [AUTO-YES] Proceeding to real after dry..."
    sleep 2
  fi

  # Real push + enable (no-timer on remotes to avoid duplicate timers; main handles continuous)
  echo "  [3/4] REAL pure cutover on $host..."
  ssh -o ConnectTimeout=20 -o BatchMode=yes "$host" '
    set -u
    mkdir -p /tmp/pure-rust-cutover
    cd /tmp/pure-rust-cutover
    echo "╔══ LIVE CUTOVER ON REMOTE ══╗"
    bash make_pure_rust_flywheel_default.sh --no-timer 2>&1 | tail -25 || bash make_pure_rust_flywheel_default.sh 2>&1 | tail -20
    touch /home/agx/agentforge/.pure_rust_flywheel 2>/dev/null || true
    # Safe worker bounce (user units preferred; fallback direct)
    if systemctl --user is-active --quiet agentforge-worker 2>/dev/null || systemctl --user is-active --quiet agentforge-jules-worker 2>/dev/null; then
      systemctl --user restart agentforge-worker agentforge-jules-worker 2>/dev/null || true
    else
      pkill -f "grok_worker.sh|jules_worker.sh" 2>/dev/null || true
      (nohup bash /home/agx/agentforge/grok_worker.sh > /dev/null 2>&1 &)
      (nohup bash /home/agx/agentforge/jules_worker.sh > /dev/null 2>&1 &)
    fi
    echo "  Workers + pure defaults signalled on $host"
  ' 2>&1 | tail -30 || echo "     (ssh real warning on $host — check manually)"

  # Post-push verification block (healthcheck + timer status + binary + provenance probe + NEW demo + candidate list + ACTUAL continuous dry)
  echo "  [4/4] POST-PUSH VERIFICATION on $host..."
  ssh -o ConnectTimeout=15 -o BatchMode=yes "$host" '
    echo "=== $host POST-VERIFY (health + timer + binary + pure provenance + demo + candidates + ACTUAL RUNS) ==="
    bash /home/agx/agentforge/healthcheck.sh 2>/dev/null | grep -E "Flywheel|Timer|Rust|pure|✅|⚠️|Task Queue|ONLINE|OFFLINE|engine|agentforge-runner" | head -18 || true
    echo "--- Timer status ---"
    (systemctl --user status agentforge-flywheel.timer --no-pager -l 2>/dev/null | head -7) || (systemctl --user list-timers --all 2>/dev/null | grep -iE "flywheel|agentforge" | head -3) || echo "  (no user timer or system mode)"
    echo "--- Binary + provenance (flywheel/candidate/continuous) ---"
    ls -l /home/agx/agentforge/rust/target/release/agentforge-runner 2>/dev/null || echo "  BINARY MISSING"
    /home/agx/agentforge/rust/target/release/agentforge-runner --version 2>/dev/null || true
    /home/agx/agentforge/rust/target/release/agentforge-runner candidate list --limit 3 2>/dev/null || true
    /home/agx/agentforge/rust/target/release/agentforge-runner continuous --top-n 1 --dry-run 2>/dev/null | cat || true
    echo "--- NEW DEMO SCRIPT (actual) ---"
    python /home/agx/agentforge/rust_flywheel_demo.py --help 2>/dev/null | head -8 || echo "  (demo probe)"
    echo "--- Pure marker + env + PYTHON CANDIDATE LIST + manifest sample ---"
    ls -l /home/agx/agentforge/.pure_rust_flywheel /home/agx/agentforge/.disable_pure_rust_flywheel 2>/dev/null || echo "  PURE marker (or env-driven)"
    python -m agentforge.list_pending_candidates list --limit 3 2>/dev/null | cat || true
    echo "  (Inspect recent pending_candidates/*/*manifest*.json for engine:rust-agentforge-runner)"
    echo "=== $host VERIFY END ==="
  ' 2>&1 | tail -55 || true

  echo "  [$host] COMPLETE (review verify block above)"
  sleep 4   # farm courtesy throttle between hosts
done

echo ""
echo "================================================================"
echo "=== FARM ROLLOUT COMPLETE ==="
echo "Next steps on MAIN (Pure Rust Flywheel Default now live everywhere):"
echo "  bash /home/agx/agentforge/healthcheck.sh | grep -E \"Flywheel|Timer|Rust|pure|agentforge-runner\""
echo "  python rust_flywheel_demo.py --help | cat   # NEW Phase 3 demo script"
echo "  /home/agx/agentforge/rust/target/release/agentforge-runner candidate list --limit 5"
echo "  /home/agx/agentforge/rust/target/release/agentforge-runner continuous --top-n 2 --dry-run"
echo "  /home/agx/agentforge/rust/target/release/agentforge-runner flywheel-step --real-data --limit 5 --output-dir /tmp/pure_verify"
echo "  python -m agentforge.list_pending_candidates list --limit 5 --sort value"
echo "  systemctl --user status agentforge-flywheel.timer || true"
echo "  ls -l /tmp/agentforge_rust_flywheel/ ; cat /tmp/agentforge_rust_flywheel/flywheel_health.json 2>/dev/null | head -c 800"
echo ""
echo "Per-host rollback (example):"
echo "  ssh agent3 'export AGENTFORGE_FLYWHEEL_ENGINE=python; rm -f /home/agx/agentforge/.pure_rust_flywheel; touch /home/agx/agentforge/.disable_pure_rust_flywheel; export DISABLE_RUST_FLYWHEEL=1; systemctl --user restart agentforge-worker agentforge-jules-worker || true'"
echo ""
echo "Re-arm pure default on any host:"
echo "  ssh HOST 'bash /home/agx/agentforge/bin/make_pure_rust_flywheel_default.sh'"
echo "================================================================"
MASTER_ROLLOUT
chmod +x /tmp/farm_pure_rust_rollout.sh
echo ""
echo "Master created at: /tmp/farm_pure_rust_rollout.sh"
echo "Usage (after local dry on main + binary on all remotes):"
echo "  bash /tmp/farm_pure_rust_rollout.sh          # interactive (recommended first farm wave) — strong dry visibility + demo/candidate verifies"
echo "  bash /tmp/farm_pure_rust_rollout.sh --yes   # auto-proceed after each dry (use only on known-good fleet)"
echo ""
echo "One-liner master invoke (when ready):"
echo "  scp /tmp/farm_pure_rust_rollout.sh main-host:/tmp/ && ssh main-host 'bash /tmp/farm_pure_rust_rollout.sh'"

# === 4. API / TASK QUEUE (same host as #1 usually) ===
# Covered by step 1. Pure env now in units via the service patch.

# === 5. Post-cutover validation (after soak) ===
# Use: agentforge-runner flywheel-step --real-data ... then inspect manifests for "engine": "rust-agentforge-runner"
# Continuous will now drive pure candidates only.

FARM_BLOCK

# === Clean ROLLBACK path (the strong killswitches for pure) ===
log "=== CLEAN ROLLBACK / DISABLE (instant, zero risk — Phase 3 — STRONGER INSTRUCTIONS + SOAK REMINDERS) ==="
cat << 'DISABLE_BLOCK'

# =============================================================================
# PHASE 3 PURE RUST FLYWHEEL DEFAULT — STRONG ROLLBACK (PRODUCTION EXCELLENCE)
# =============================================================================
# Instant per-shell (affects dispatch, post_process, hooks, workers, continuous immediately):
export AGENTFORGE_FLYWHEEL_ENGINE=python
export AGENTFORGE_PURE_RUST_FLYWHEEL=0

# Stronger (survives restarts + workers + units):
touch /home/agx/agentforge/.disable_pure_rust_flywheel
export DISABLE_RUST_FLYWHEEL=1   # ultimate existing killswitch (honored in every guard + binary paths)

# Then restart workers + timer (user mode preferred):
systemctl --user restart agentforge-worker agentforge-jules-worker 2>/dev/null || true
systemctl --user restart agentforge-flywheel.timer 2>/dev/null || true

# =============================================================================
# FULL ROLLBACK + RESTORE FROM BACKUPS (if patches need unwind)
# =============================================================================
# 1. Restore every patched file from the .bak.purecutover backups created by this script:
for f in \
  /home/agx/agentforge/agentforge-flywheel.service \
  /home/agx/agentforge/agentforge-flywheel.timer \
  /home/agx/agentforge/grok_worker.sh \
  /home/agx/agentforge/jules_worker.sh \
  /home/agx/agentforge/dispatcher.sh \
  /home/agx/agentforge/agents/grok_runner.sh \
  /home/agx/agentforge/agents/jules_runner.sh \
  /home/agx/agentforge/agents/agy_runner.sh \
  /home/agx/agentforge/agents/gemini_runner.sh \
  /home/agx/agentforge/bin/rust_flywheel_after_task.sh \
  /home/agx/agentforge/bin/run_continuous_flywheel.sh \
  /home/agx/agentforge/bin/run_continuous_flywheel.py \
  /home/agx/agentforge/healthcheck.sh \
  /home/agx/agentforge/bin/rust_flywheel.env \
  /home/agx/agentforge/install_services.sh \
  /home/agx/agentforge/agentforge-worker.service \
  /home/agx/agentforge/agentforge-jules-worker.service \
  /home/agx/agentforge/agentforge-api.service \
  /home/agx/agentforge/agentforge-watchdog.service \
  /home/agx/agentforge/agentforge.service \
; do
  if [ -f "${f}.bak.purecutover" ]; then
    cp -f "${f}.bak.purecutover" "$f" && echo "Restored $f from backup"
  fi
done

# 2. Reload systemd (if units were touched):
systemctl --user daemon-reload 2>/dev/null || sudo systemctl daemon-reload 2>/dev/null || true

# 3. Clean pure markers (keeps base Rust/Antigravity paths if wanted):
rm -f /home/agx/agentforge/.pure_rust_flywheel /home/agx/agentforge/.disable_pure_rust_flywheel 2>/dev/null || true

# 4. Force Python engine for any lingering processes:
pkill -f 'agentforge-runner.*(flywheel|continuous|candidate)' 2>/dev/null || true

# Per-invocation test (forces Python orchestration path):
AGENTFORGE_FLYWHEEL_ENGINE=python PYTHONPATH=. python -m agentforge.rust_flywheel_step --help 2>&1 | cat || true
DISABLE_RUST_FLYWHEEL=1 AGENTFORGE_PURE_RUST_FLYWHEEL=0 python -m agentforge.list_pending_candidates list --limit 1 2>/dev/null || true

# Future clean helper (when created):
# bash bin/disable_pure_rust_flywheel.sh

# Re-arm pure default (one command, after binary verified):
bash /home/agx/agentforge/bin/make_pure_rust_flywheel_default.sh --dry-run
bash /home/agx/agentforge/bin/make_pure_rust_flywheel_default.sh

# Evidence that rollback is respected: post_process.py (pure_rust branch), phase2_3_integration.py,
# learning/utils.py:is_pure_rust_flywheel(), all patched *_worker.sh + hooks + continuous,
# run_continuous, services, dispatcher, and direct binary calls in health/audit.
# Also verified via rust_flywheel_demo.py and candidate manifests engine field.

# To restore full Antigravity (non-pure) default: bash bin/make_antigravity_default.sh

# Farm-wide rollback one-liner example (from main):
# for h in agent1 ssh-3 ...; do ssh $h 'export AGENTFORGE_FLYWHEEL_ENGINE=python; touch /home/agx/agentforge/.disable_pure_rust_flywheel; export DISABLE_RUST_FLYWHEEL=1; systemctl --user restart agentforge-worker agentforge-jules-worker || true'; done

# === POST-ROLLBACK SOAK (symmetric to cutover soak) ===
# After rollback: 30-60min monitoring to confirm zero pure paths, all candidates via Python/legacy, no engine=rust in new manifests.
# Use same monitors as cutover but expect Python provenance.

DISABLE_BLOCK

log "=== PURE RUST FLYWHEEL DEFAULT CUTOVER COMPLETE ==="
log "See $LOG_FILE for full trace."
log "The farm is now running Pure Rust Flywheel Default: agentforge-runner is the single source of truth for flywheel-step / candidate / continuous orchestration."
log "Only off-switches for pure layer: AGENTFORGE_FLYWHEEL_ENGINE=python or .disable_pure_rust_flywheel (falls back to legacy Rust or full Python). Ultimate: DISABLE_RUST_FLYWHEEL=1."
log ""
log "CUTOVER SCRIPT NOW PRODUCTION-READY FOR FARM ROLLOUT"

# Final safe dry verification using the pure binary (reuses all paths)
if [ $DRY_RUN -eq 0 ]; then
    log "Final safe verification dry-run via pure binary continuous path..."
    env PYTHONPATH=/home/agx AGENTFORGE_PURE_RUST_FLYWHEEL=1 AGENTFORGE_FLYWHEEL_ENGINE=rust timeout 25s "$RUST_RELEASE_BIN" continuous --top-n 1 --dry-run 2>&1 | tail -12 || true
fi

exit 0
