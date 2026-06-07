#!/bin/bash
# !!! AGGRESSIVE FINAL DEPRECATION SWEEP (RUST_FULL_MIGRATION_PLAN.md + PHASE4_REMOVAL_PLAN.md) !!!
# gemini_runner.sh : runner patched by pure cutover scripts for flywheel env (prefers Rust binary).
# Python flywheel orchestration deprecated; hooks now delegate or short-circuit.
# See PHASE4_REMOVAL_PLAN.md (Tier 4, agents runners marked in final sweep).
# Запуск Gemini Agent для задачи AgentForge
export HTTPS_PROXY=socks5://127.0.0.1:12335
# Gemini 2.5 Pro через REST API (бесплатный тир)
export PATH=/home/eveselove/bin:/home/eveselove/.cargo/bin:/home/eveselove/.grok/bin:/home/eveselove/bin:$PATH

# Rust Flywheel snippet (for completeness on all paths)
RUST_FLYWHEEL_SNIPPET="/home/eveselove/agentforge/bin/rust_flywheel.env"
[ -f "$RUST_FLYWHEEL_SNIPPET" ] && source "$RUST_FLYWHEEL_SNIPPET" 2>/dev/null || true
export AGENTFORGE_RUST_FLYWHEEL="${AGENTFORGE_RUST_FLYWHEEL:-0}"

TASK_ID="$1"
TASK_DESC="$2"
LOG_DIR="/home/eveselove/agentforge/logs"

echo "[AgentForge] Запуск Gemini Agent для задачи $TASK_ID" | tee -a $LOG_DIR/gemini_$TASK_ID.log

# Запуск gemini-agent (бесплатный Gemini 2.5 Pro/Flash)
gemini-agent "$TASK_DESC. ВАЖНО: Все твои ответы и комментарии должны быть написаны строго на РУССКОМ языке." 2>&1 | tee -a $LOG_DIR/gemini_$TASK_ID.log

# Обновляем статус задачи
curl -s -X PATCH http://localhost:8080/tasks/$TASK_ID \
  -H 'Content-Type: application/json' \
  -d '{"status": "review", "assigned_agent": "gemini"}'

echo "[AgentForge] Gemini завершил задачу $TASK_ID"

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
