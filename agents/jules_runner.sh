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
export PATH=/home/eveselove/.cargo/bin:/home/eveselove/bin:$PATH
export NVM_DIR=/home/eveselove/.nvm
[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"

# === Rust Flywheel + Trajectory integration (Jules live farm) ===
# Source snippet so AGENTFORGE_RUST_FLYWHEEL propagates; runner will trigger post_process hook on real completion.
# === Rust Flywheel now DEFAULT for Antigravity (unless DISABLE_RUST_FLYWHEEL=1) ===
RUST_FLYWHEEL_SNIPPET="/home/eveselove/agentforge/bin/rust_flywheel.env"
if [ -f "$RUST_FLYWHEEL_SNIPPET" ]; then
    source "$RUST_FLYWHEEL_SNIPPET" 2>/dev/null || true
fi
if [ "${DISABLE_RUST_FLYWHEEL:-0}" != "1" ]; then
    [ -x "/home/eveselove/agentforge/bin/enable_rust_flywheel.sh" ] && source "/home/eveselove/agentforge/bin/enable_rust_flywheel.sh" 2>/dev/null || true
    export AGENTFORGE_RUST_FLYWHEEL=1
    export AGENTFORGE_USE_RUST=1
fi
export AGENTFORGE_RUST_FLYWHEEL="${AGENTFORGE_RUST_FLYWHEEL:-0}"
export AGENTFORGE_USE_RUST="${AGENTFORGE_USE_RUST:-0}"
# Prefer release for prod polish
if [ -x "/home/eveselove/agentforge/rust/target/release/agentforge-runner" ]; then _R="/home/eveselove/agentforge/rust/target/release/agentforge-runner"; else _R="/home/eveselove/agentforge/rust/target/debug/agentforge-runner"; fi
export AGENTFORGE_RUST_RUNNER="${AGENTFORGE_RUST_RUNNER:-$_R}"

# Structured Trajectory + auto post_process for Jules (feeds PRM + Rust flywheel on completion)
export TASK_ID="$TASK_ID"
export AGENT="jules"
export TRAJECTORY_DIR="/home/eveselove/agentforge/eval/trajectories"
export AUTO_PRM="${AUTO_PRM:-1}"
export EVAL_AUTO_POSTPROCESS="${EVAL_AUTO_POSTPROCESS:-1}"
source "/home/eveselove/agentforge/eval/log_trajectory.sh" 2>/dev/null || true
log_task_start "${TASK_DESC:-jules-task}" "$PRIORITY" "${TAGS:-}" 2>/dev/null || true

TASK_ID="$1"
TASK_DESC="$2"
REPO="${3:-eveselove/planlytasksko}"
PRIORITY="${4:-medium}"
LOG_DIR="/home/eveselove/agentforge/logs"

echo "[AgentForge] Запуск Jules для задачи $TASK_ID" | tee -a $LOG_DIR/jules_$TASK_ID.log

# === Git Worktree Isolation (подготовка изолированной копии; jules cloud-based но для единообразия) ===
WORKTREE_DIR="/tmp/agentforge/${TASK_ID}"
mkdir -p /tmp/agentforge
# Non-fatal: Jules не редактирует локально (создаёт PR удалённо), но worktree обеспечивает чистую среду
git -C "/home/eveselove/planlytasksko" worktree add "$WORKTREE_DIR" -b "agentforge/$TASK_ID" 2>/dev/null || \
  git -C "/home/eveselove/planlytasksko" worktree add "$WORKTREE_DIR" "agentforge/$TASK_ID" 2>/dev/null || true

cleanup_worktree() {
  git -C "/home/eveselove/planlytasksko" worktree remove --force "$WORKTREE_DIR" 2>/dev/null || true
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

# === A1 (task 306644eb): Auto-create agent-review followup task (Jules path) ===
# Jules создаёт PR в облаке; сразу после — создаём задачу на обязательное ревью.
# Полный процесс: agent-review skill → handoff → PR review → merge (см. AGENTS.md).
# Guard (Jules review 95f27dd3): skip recursion if this task is itself agent-review/followup.
if echo "$TASK_DESC" | grep -qiE 'agent-review|followup|MANDATORY agent-review|review task'; then
    echo "[AgentForge A1 306644eb] Skipping Jules review-task creation (recursion guard — current is review/followup)" | tee -a "$LOG_DIR/jules_$TASK_ID.log" || true
else
    SAFE_DESC_J="${TASK_DESC:-unknown-jules-task}"
    REVIEW_TITLE_J="agent-review: ${TASK_ID} (Jules PR for ${SAFE_DESC_J:0:40})"
    REVIEW_DESC_J="MANDATORY agent-review (skill=agent-review) для Jules-сессии по задаче ${TASK_ID}.

Jules PR создан (см. логи + GitHub). 
Orig: Jules: ${DURATION}s, PR created ✅

Шаги:
1. Получи diff/PR: git fetch + git log --oneline -10 или через jules remote
2. Вызови: agent-review --to-jules (или /agent-review --to-jules внутри контекста)
3. Независимое ревью (второй агент), handoff в ~/.grok/handoffs/<id>/
4. Зафиксируй результат, address findings если нужно, только потом закрывай PR/таск.

Теги ссылаются на orig ${TASK_ID}. Обязательно перед merge в main (AGENTS.md + task 306644eb)."
    python3 -c '
import json, urllib.request, sys
tid = sys.argv[1]
desc = sys.argv[2]
data = {
    "title": sys.argv[3],
    "description": desc,
    "priority": "high",
    "preferred_agent": "jules",
    "tags": ["agent-review", "followup", "jules", "306644eb", tid],
    "skill": "agent-review"
}
req = urllib.request.Request(
    "http://localhost:8080/tasks",
    data=json.dumps(data, ensure_ascii=False).encode("utf-8"),
    headers={"Content-Type": "application/json"}
)
try:
    with urllib.request.urlopen(req, timeout=8) as resp:
        created = json.loads(resp.read().decode())
        print(f"[AgentForge A1 306644eb] ✅ Auto-created Jules agent-review task: {created.get(\"id\")}")
except Exception as e:
    print(f"[AgentForge A1 306644eb] Jules review task create non-fatal: {e}")
' "$TASK_ID" "$REVIEW_DESC_J" "$REVIEW_TITLE_J" 2>&1 | tee -a "$LOG_DIR/jules_$TASK_ID.log" || true
fi  # close the "else" of recursion guard skip-if (only one fi needed for the guard if/else)

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
os.environ.setdefault("PYTHONPATH","/home/eveselove")
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
        PYTHONPATH=/home/eveselove \
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

# === FINAL HANDOFF NOTE FOR MERGE (Grok clearance D-DAY, handoff 02d2727d) ===
# P2 A1 final merge (af331eee / 306644eb). Scope: only this file + grok_runner.sh.
# Pre-handoff checklist PASSED (see ~/.grok/handoffs/02d2727d/context.md).
# Recursion guard present and verified. Pre-commit green on branch.
# Manual completion note added by Grok on branch for this handoff.
# PR will ref this handoff ID + task + checklist. Merge + cleanup pending checks.
# P2 now fully closed in repo upon successful merge. (Jules path covered.)
