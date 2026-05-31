#!/bin/bash
# !!! AGGRESSIVE FINAL DEPRECATION SWEEP (RUST_FULL_MIGRATION_PLAN.md + PHASE4_REMOVAL_PLAN.md) !!!
# !!! PHASE 4 DELETION TARGET INFRA: jules_runner.sh flywheel post-process / env hooks !!!
# Python flywheel orchestration (rust_flywheel_step.py + phase2_3_integration glue + post_process triggers)
# is fully deprecated. All live farm paths MUST migrate to agentforge-runner flywheel-step/continuous/candidate.
# This runner still sources enable + sets env for transition; post-Phase4: direct binary or thin wrapper only.
# Guard: source enable + respect is_pure_rust_flywheel() everywhere (central in learning/utils.py).
# See PHASE4_REMOVAL_PLAN.md (Tier 4 infra sh cleanup, agents/*, services; risks + rollback via disable scripts).
# Full strategy + verification: PHASE4_REMOVAL_CHECKLIST.md + bin/make_pure... + bin/disable_pure...
#
# Запуск Jules для задачи AgentForge
# Jules работает в облаке Google — поддерживает --parallel N
# Git Worktrees: изоляция агентов (подготовка /tmp/agentforge/TASK_ID для consistency)
export PATH=/home/agx/.cargo/bin:/home/agx/bin:$PATH
export NVM_DIR=/home/agx/.nvm
[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"

# === Rust Flywheel + Trajectory integration (Jules live farm) ===
# Source snippet so AGENTFORGE_RUST_FLYWHEEL propagates; runner will trigger post_process hook on real completion.
# === Rust Flywheel now DEFAULT for Antigravity (unless DISABLE_RUST_FLYWHEEL=1) ===
RUST_FLYWHEEL_SNIPPET="/home/agx/agentforge/bin/rust_flywheel.env"
if [ -f "$RUST_FLYWHEEL_SNIPPET" ]; then
    source "$RUST_FLYWHEEL_SNIPPET" 2>/dev/null || true
fi
if [ "${DISABLE_RUST_FLYWHEEL:-0}" != "1" ]; then
    [ -x "/home/agx/agentforge/bin/enable_rust_flywheel.sh" ] && source "/home/agx/agentforge/bin/enable_rust_flywheel.sh" 2>/dev/null || true
    export AGENTFORGE_RUST_FLYWHEEL=1
    export AGENTFORGE_USE_RUST=1
fi
export AGENTFORGE_RUST_FLYWHEEL="${AGENTFORGE_RUST_FLYWHEEL:-0}"
export AGENTFORGE_USE_RUST="${AGENTFORGE_USE_RUST:-0}"
# Prefer release for prod polish
if [ -x "/home/agx/agentforge/rust/target/release/agentforge-runner" ]; then _R="/home/agx/agentforge/rust/target/release/agentforge-runner"; else _R="/home/agx/agentforge/rust/target/debug/agentforge-runner"; fi
export AGENTFORGE_RUST_RUNNER="${AGENTFORGE_RUST_RUNNER:-$_R}"

# Structured Trajectory + auto post_process for Jules (feeds PRM + Rust flywheel on completion)
export TASK_ID="$TASK_ID"
export AGENT="jules"
export TRAJECTORY_DIR="/home/agx/agentforge/eval/trajectories"
export AUTO_PRM="${AUTO_PRM:-1}"
export EVAL_AUTO_POSTPROCESS="${EVAL_AUTO_POSTPROCESS:-1}"
source "/home/agx/agentforge/eval/log_trajectory.sh" 2>/dev/null || true
log_task_start "${TASK_DESC:-jules-task}" "$PRIORITY" "${TAGS:-}" 2>/dev/null || true

TASK_ID="$1"
TASK_DESC="$2"
REPO="${3:-eveselove/planlytasksko}"
PRIORITY="${4:-medium}"
LOG_DIR="/home/agx/agentforge/logs"

echo "[AgentForge] Запуск Jules для задачи $TASK_ID" | tee -a $LOG_DIR/jules_$TASK_ID.log

# === Git Worktree Isolation (подготовка изолированной копии; jules cloud-based но для единообразия) ===
WORKTREE_DIR="/tmp/agentforge/${TASK_ID}"
mkdir -p /tmp/agentforge
# Non-fatal: Jules не редактирует локально (создаёт PR удалённо), но worktree обеспечивает чистую среду
git -C "/home/agx/planlytasksko" worktree add "$WORKTREE_DIR" -b "agentforge/$TASK_ID" 2>/dev/null || \
  git -C "/home/agx/planlytasksko" worktree add "$WORKTREE_DIR" "agentforge/$TASK_ID" 2>/dev/null || true

cleanup_worktree() {
  git -C "/home/agx/planlytasksko" worktree remove --force "$WORKTREE_DIR" 2>/dev/null || true
}
trap cleanup_worktree EXIT INT TERM

# Параллельные сессии (максимум снят)
JULES_FLAGS="--parallel 3"
if [ "$PRIORITY" = "critical" ]; then
    JULES_FLAGS="--parallel 5"
elif [ "$PRIORITY" = "high" ]; then
    JULES_FLAGS="--parallel 4"
fi

START_TIME=$(date +%s)

# Запуск Jules — создаёт PR в GitHub (облако Google)
JULES_OUTPUT=$(jules new $JULES_FLAGS --repo "$REPO" "$TASK_DESC. ВАЖНО: Все твои ответы, комментарии к коду и PR должны быть написаны строго на РУССКОМ языке." 2>&1)
echo "$JULES_OUTPUT" | tee -a $LOG_DIR/jules_$TASK_ID.log

END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))

# Проверяем, успешно ли создались сессии
if echo "$JULES_OUTPUT" | grep -qi "failed to create\|all sessions failed\|error"; then
    echo "[AgentForge] ERROR: Jules не смог создать сессии для задачи $TASK_ID" | tee -a $LOG_DIR/jules_$TASK_ID.log
    curl -s -X PATCH http://localhost:8080/tasks/$TASK_ID \
      -H 'Content-Type: application/json' \
      -d "{\"status\": \"failed\", \"assigned_agent\": \"jules\", \"result\": \"Jules failed to create sessions. Check logs and Jules repo connection.\", \"duration_seconds\": $DURATION}" > /dev/null 2>&1
    exit 1
fi

# Обновляем статус только при успехе
curl -s -X PATCH http://localhost:8080/tasks/$TASK_ID \
  -H 'Content-Type: application/json' \
  -d "{\"status\": \"review\", \"assigned_agent\": \"jules\", \"result\": \"Jules: ${DURATION}s, PR created ✅\", \"duration_seconds\": $DURATION}"

echo "[AgentForge] Jules отправил PR для задачи $TASK_ID (${DURATION}s)"

# Structured completion for trajectory (if sourced)
log_completion "review" "$DURATION" "0.0" 2>/dev/null || true
log_event "jules_execution_end" "{\"status\":\"review\",\"duration_seconds\":$DURATION}" 2>/dev/null || true

# !!! AGGRESSIVE FINAL DEPRECATION SWEEP (RUST_FULL_MIGRATION_PLAN.md + PHASE4_REMOVAL_PLAN.md) !!!
# Python flywheel orchestration post-task hook DEPRECATED — Phase 4 removal target (see tiers/risks/rollback in PLAN).
# Non-blocking. Direct agentforge-runner flywheel-step is the future (via strengthened is_pure... guard).
# Full details: PHASE4_REMOVAL_PLAN.md (Tier 3 glue/hooks).
# See learning/utils.py (Phase 3 stronger) + RUST_FULL_MIGRATION_PLAN.md
if [ "${DISABLE_RUST_FLYWHEEL:-0}" != "1" ]; then
    _PURE_J=$(python3 -c '
import os
os.environ.setdefault("PYTHONPATH","/home/agx")
try:
    from agentforge.learning.utils import is_pure_rust_flywheel as f
    print(1 if f() else 0)
except Exception:
    print(0)
' 2>/dev/null || echo 0)
    if [ "$_PURE_J" = "1" ]; then
        echo "[DEPRECATION PHASE 3 jules_runner] is_pure_rust_flywheel()=1 — legacy python post hook; prefer agentforge-runner flywheel-step" >> "$LOG_DIR/jules_$TASK_ID.log" 2>/dev/null || true
    fi
    (
        PYTHONPATH=/home/agx \
        python3 -m agentforge.bin.rust_post_process_hook "$TASK_ID" \
            >> "$LOG_DIR/rust_flywheel_hook_${TASK_ID}.log" 2>&1 || true
    ) &
fi

# Явная очистка worktree (изоляция завершена)
cleanup_worktree
echo "[AgentForge] Worktree $WORKTREE_DIR cleaned (jules isolation complete)" | tee -a $LOG_DIR/jules_$TASK_ID.log 2>/dev/null || true

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
