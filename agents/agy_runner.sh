#!/bin/bash
# !!! AGGRESSIVE FINAL DEPRECATION SWEEP (RUST_FULL_MIGRATION_PLAN.md + PHASE4_REMOVAL_PLAN.md) !!!
# agy_runner.sh : legacy runner; may carry flywheel hooks via shared env (patched by make_pure scripts).
# Flywheel orchestration now canonical via agentforge-runner in patched units.
# See PHASE4_REMOVAL_PLAN.md (Tier 4 infra, agents/* runners).
# Запуск Antigravity CLI (legacy agy)
# Внимание: Antigravity сейчас в основном работает в ручном режиме (см. план рефакторинга).
# Этот раннер оставлен для совместимости и редких случаев.

export PATH=/home/eveselove/.cargo/bin:/home/eveselove/.grok/bin:/home/eveselove/bin:$PATH
export NVM_DIR=/home/eveselove/.nvm
[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"

# Rust Flywheel snippet (for completeness on all dispatch paths)
RUST_FLYWHEEL_SNIPPET="/home/eveselove/agentforge/bin/rust_flywheel.env"
[ -f "$RUST_FLYWHEEL_SNIPPET" ] && source "$RUST_FLYWHEEL_SNIPPET" 2>/dev/null || true
export AGENTFORGE_RUST_FLYWHEEL="${AGENTFORGE_RUST_FLYWHEEL:-0}"

TASK_ID="$1"
TASK_DESC="$2"
PROJECT_DIR="${3:-/home/eveselove/planlytasksko}"
LOG_DIR="/home/eveselove/agentforge/logs"

echo "[AgentForge] Запуск AGY (Antigravity legacy) для задачи $TASK_ID" | tee -a $LOG_DIR/agy_$TASK_ID.log

# Используем worktree для изоляции (как в grok_runner)
WORKTREE_DIR="/tmp/agentforge/${TASK_ID}"
mkdir -p /tmp/agentforge

if ! git -C "$PROJECT_DIR" worktree add "$WORKTREE_DIR" -b "agentforge/$TASK_ID" 2>/dev/null; then
    git -C "$PROJECT_DIR" worktree add "$WORKTREE_DIR" "agentforge/$TASK_ID" 2>/dev/null || true
fi

cd "$WORKTREE_DIR" 2>/dev/null || cd "$PROJECT_DIR"

cleanup_worktree() {
    git -C "$PROJECT_DIR" worktree remove --force "$WORKTREE_DIR" 2>/dev/null || true
}
trap cleanup_worktree EXIT INT TERM

# Запуск agy в headless режиме
agy --prompt "$TASK_DESC" --yes 2>&1 | tee -a $LOG_DIR/agy_$TASK_ID.log

# Обновляем статус
curl -s -X PATCH http://localhost:8080/tasks/$TASK_ID \
  -H 'Content-Type: application/json' \
  -d '{"status": "review", "assigned_agent": "antigravity"}' > /dev/null 2>&1 || true

echo "[AgentForge] AGY завершил задачу $TASK_ID"
echo "[AgentForge] Рекомендация: используй Antigravity IDE чат вместо этого раннера. См. AGENTFORGE_ROUTING_AND_EXECUTION_REFACTOR_PLAN.md"

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
