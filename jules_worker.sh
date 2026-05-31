#!/bin/bash
# AgentForge Jules Worker — подхватывает задачи с preferred_agent=jules
#
# STATUS: TEMPORARILY DISABLED (2026-05-31)
# Reason: Large backlog + unreliable session creation in Jules cloud.
# All active Jules processes have been stopped and pending tasks reassigned.
# Do not restart until the repo connection and worker reliability issues are resolved.
export PATH=/home/agx/.nvm/versions/node/v20.20.1/bin:/home/agx/.cargo/bin:/home/agx/bin:$PATH
export NVM_DIR=/home/agx/.nvm
[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"

# === Rust Flywheel auto-integration — FULL RUST-ONLY DIRECTION (2026-05-31) ===
# Python flywheel orchestration is being removed. Prefer agentforge-runner everywhere.
# Full Rust-powered self-improving flywheel is DEFAULT ON (no env needed).
# Strong simple rollback: DISABLE_RUST_FLYWHEEL=1 or /home/agx/agentforge/.disable_rust_flywheel
# Sources canonical enable + snippet. Release binary preferred. Rate limits/safety untouched.
#
# !!! AGGRESSIVE FINAL DEPRECATION SWEEP + PHASE 4 PLAN (RUST_FULL_MIGRATION_PLAN.md + PHASE4_REMOVAL_PLAN.md) !!!
# PHASE 3/4 FINAL: Python flywheel orchestration (after_task + continuous + step + candidate glue) DEPRECATED.
# Prefer direct: agentforge-runner flywheel-step --real-data --ingest inside workers when pure.
# See PHASE4_REMOVAL_PLAN.md (removal tiers, risks per file, rollback via FLYWHEEL_ENGINE=python + .disable* dotfiles).
# PHASE 3 FINAL DEPRECATION SWEEP: Python flywheel orchestration (after_task + continuous etc)
# heavily marked. Stronger guards in learning/utils.py:is_pure_rust_flywheel(). Prefer agentforge-runner.
RUST_FLYWHEEL_SNIPPET="/home/agx/agentforge/bin/rust_flywheel.env"
if [ -f "$RUST_FLYWHEEL_SNIPPET" ]; then
    source "$RUST_FLYWHEEL_SNIPPET" 2>/dev/null || true
fi
AGENTFORGE_DIR="/home/agx/agentforge"
DISABLE_FILE="$AGENTFORGE_DIR/.disable_rust_flywheel"
if [[ "${DISABLE_RUST_FLYWHEEL:-0}" != "1" ]] && [[ ! -f "$DISABLE_FILE" ]]; then
    export AGENTFORGE_RUST_FLYWHEEL=1
    export AGENTFORGE_USE_RUST=1
    # Prefer release binary for prod (if built)
    if [ -x "/home/agx/agentforge/rust/target/release/agentforge-runner" ]; then
      _RUST_RUNNER="/home/agx/agentforge/rust/target/release/agentforge-runner"
    else
      _RUST_RUNNER="/home/agx/agentforge/rust/target/debug/agentforge-runner"
    fi
    export AGENTFORGE_RUST_RUNNER="${AGENTFORGE_RUST_RUNNER:-$_RUST_RUNNER}"
    # shellcheck disable=SC1091
    [[ -x /home/agx/agentforge/bin/enable_rust_flywheel.sh ]] && source /home/agx/agentforge/bin/enable_rust_flywheel.sh 2>/dev/null || true
fi
# Final export default-on unless disabled
if [[ "${DISABLE_RUST_FLYWHEEL:-0}" = "1" ]] || [[ -f "$DISABLE_FILE" ]]; then
    export AGENTFORGE_RUST_FLYWHEEL="${AGENTFORGE_RUST_FLYWHEEL:-0}"
    export AGENTFORGE_USE_RUST="${AGENTFORGE_USE_RUST:-0}"
else
    export AGENTFORGE_RUST_FLYWHEEL="${AGENTFORGE_RUST_FLYWHEEL:-1}"
    export AGENTFORGE_USE_RUST="${AGENTFORGE_USE_RUST:-1}"
fi
# Prefer release binary for prod (idempotent)
if [ -x "/home/agx/agentforge/rust/target/release/agentforge-runner" ]; then
  _RUST_RUNNER="/home/agx/agentforge/rust/target/release/agentforge-runner"
else
  _RUST_RUNNER="/home/agx/agentforge/rust/target/debug/agentforge-runner"
fi
export AGENTFORGE_RUST_RUNNER="${AGENTFORGE_RUST_RUNNER:-$_RUST_RUNNER}"

API="http://localhost:8080"
LOG_DIR="/home/agx/agentforge/logs"
POLL_INTERVAL=15
RUNNER="/home/agx/agentforge/agents/jules_runner.sh"

mkdir -p $LOG_DIR /tmp/agentforge

log() { echo "[$(date '+%H:%M:%S')] $1" | tee -a $LOG_DIR/jules_worker.log; }

log "🚀 Jules Worker запущен (poll=${POLL_INTERVAL}s)"

while true; do
    # Получаем все задачи
    TASKS=$(curl -s "$API/tasks" 2>/dev/null)
    if [ -z "$TASKS" ]; then
        sleep $POLL_INTERVAL
        continue
    fi

    # Фильтруем pending задачи для Jules
    echo "$TASKS" | python3 -c '
import sys, json
try:
    tasks = json.load(sys.stdin)
except:
    sys.exit(0)
for t in tasks:
    if t.get("status") != "pending":
        continue
    pref = str(t.get("preferred_agent") or "").lower()
    if pref != "jules":
        continue
    tid = t["id"]
    title = (t.get("title") or "").replace("\t", " ")
    desc = (t.get("description") or "").replace("\n", " ").replace("\t", " ")[:200]
    priority = t.get("priority", "medium")
    repo = t.get("target_repo") or t.get("repo") or "eveselove/planlytasksko"
    print(f"{tid}\t{title}\t{desc}\t{priority}\t{repo}")
' > /tmp/agentforge/jules_pending.txt 2>/dev/null

    if [ ! -s /tmp/agentforge/jules_pending.txt ]; then
        sleep $POLL_INTERVAL
        continue
    fi

    # Обрабатываем по одной задаче за раз
    while IFS=$'\t' read -r TASK_ID TITLE DESC PRIORITY REPO; do
        [ -z "$TASK_ID" ] && continue

        REPO="${REPO:-eveselove/planlytasksko}"

        log "📋 Jules берёт задачу: $TASK_ID — $TITLE (repo: $REPO)"

        # Диспатчим
        curl -s -X POST "$API/tasks/$TASK_ID/dispatch" > /dev/null 2>&1

        # Обновляем статус на in_progress
        curl -s -X PATCH "$API/tasks/$TASK_ID" \
          -H 'Content-Type: application/json' \
          -d '{"status": "in_progress", "assigned_agent": "jules"}' > /dev/null 2>&1

        # Запускаем Jules runner
        bash "$RUNNER" "$TASK_ID" "$TITLE. $DESC" "$REPO" "$PRIORITY" >> $LOG_DIR/jules_worker.log 2>&1

        log "✅ Jules завершил задачу: $TASK_ID"

        # Direct robust canonical flywheel hook (rust_flywheel_after_task.sh) AFTER real task + post_process.
        # DEFAULT ON (unless DISABLE_RUST_FLYWHEEL=1 or .disable_rust_flywheel). 
        # Independent 5min rate-limit/lock + canonical step to pending_candidates. All safety kept.
        _RUST_DISABLED_JULES=0
        if [[ "${DISABLE_RUST_FLYWHEEL:-0}" = "1" ]] || [[ -f /home/agx/agentforge/.disable_rust_flywheel ]]; then
            _RUST_DISABLED_JULES=1
        fi
        if [[ $_RUST_DISABLED_JULES -eq 0 ]]; then
            (
                bash /home/agx/agentforge/bin/rust_flywheel_after_task.sh "$TASK_ID" \
                    >> "$LOG_DIR/rust_flywheel_after_${TASK_ID}.log" 2>&1 || true
            ) &
        fi

    done < /tmp/agentforge/jules_pending.txt

    sleep $POLL_INTERVAL
done

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
