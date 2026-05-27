#!/bin/bash
# ============================================
# AgentForge Grok Worker v3 — параллельный воркер
# Использует git worktree для изоляции задач
# Запускает до 5 задач параллельно через Grok
# Запуск: nohup bash ~/agentforge/grok_worker.sh &
# ============================================

export PATH=/home/agx/.local/bin:/home/agx/.cargo/bin:/home/agx/.grok/bin:/home/agx/bin:$PATH
export PROTOC=/home/agx/.local/bin/protoc
export NVM_DIR=/home/agx/.nvm
[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"

API="http://localhost:8080"
LOG_DIR="/home/agx/agentforge/logs"
PROJECT_DIR="/home/agx/planlytasksko"
POLL_INTERVAL=15
TASK_TIMEOUT=300
MAX_PARALLEL=5
TMP_DIR="/tmp/agentforge"

mkdir -p "$LOG_DIR" "$TMP_DIR"

log() {
    echo "[GrokWorker $(date '+%H:%M:%S')] $*" | tee -a "$LOG_DIR/grok_worker.log"
}

# Считаем сколько задач сейчас выполняется
running_tasks() {
    jobs -r 2>/dev/null | wc -l
}

log "🚀 Воркер v3 (parallel=$MAX_PARALLEL, poll=${POLL_INTERVAL}s, worktree)"

while true; do
    # Сколько слотов свободно?
    RUNNING=$(running_tasks)
    FREE=$((MAX_PARALLEL - RUNNING))
    if [ "$FREE" -le 0 ]; then
        sleep 5
        continue
    fi

    # Получаем задачи
    TASKS_FILE="$TMP_DIR/pending_tasks.json"
    curl -s "$API/tasks" 2>/dev/null > "$TASKS_FILE"

    if [ ! -s "$TASKS_FILE" ]; then
        sleep "$POLL_INTERVAL"
        continue
    fi

    # Парсим ВСЕ pending задачи (лимит = свободные слоты)
    PARSED_FILE="$TMP_DIR/parsed_tasks.txt"
    python3 << PYEOF > "$PARSED_FILE"
import json, sys

try:
    with open("$TMP_DIR/pending_tasks.json") as f:
        tasks = json.load(f)
except Exception:
    sys.exit(0)

count = 0
limit = $FREE
for t in tasks:
    if t.get("status") != "pending":
        continue
    if count >= limit:
        break
    tags = ",".join(t.get("tags", []))
    desc = (t.get("description") or "").replace("\n", " ").replace("\t", " ")[:200]
    title = (t.get("title") or "").replace("\t", " ")
    print(f"{t['id']}\t{title}\t{desc}\t{t.get('priority','medium')}\t{t.get('complexity','medium')}\t{tags}")
    count += 1
PYEOF

    if [ ! -s "$PARSED_FILE" ]; then
        sleep "$POLL_INTERVAL"
        continue
    fi

    # Обрабатываем задачи параллельно
    while IFS=$'\t' read -r TASK_ID TITLE DESC PRIORITY COMPLEXITY TAGS; do
        [ -z "$TASK_ID" ] && continue

        log "📋 [$RUNNING/$MAX_PARALLEL] $TASK_ID — $TITLE"

        # Диспатчим
        curl -s -X POST "$API/tasks/$TASK_ID/dispatch" > /dev/null 2>&1

        # Запускаем в фоне с worktree
        (
            TASK_LOG="$LOG_DIR/grok_$TASK_ID.log"
            > "$TASK_LOG"

            # Формируем промпт
            PROMPT="$TITLE"
            [ -n "$DESC" ] && [ "$DESC" != " " ] && PROMPT="$PROMPT. Детали: $DESC"
            [ -n "$TAGS" ] && PROMPT="$PROMPT. Теги: $TAGS"

            # Флаги Grok
            GROK_FLAGS="--always-approve"
            case "$PRIORITY" in
                critical) GROK_FLAGS="$GROK_FLAGS --check --best-of-n 3" ;;
                high)     GROK_FLAGS="$GROK_FLAGS --check" ;;
            esac

            START_TIME=$(date +%s)
            echo "[AgentForge] Задача: $TASK_ID" >> "$TASK_LOG"
            echo "[AgentForge] Промпт: $PROMPT" >> "$TASK_LOG"

            cd "$PROJECT_DIR" || exit 1

            # Запуск Grok с worktree (каждая задача в своей копии)
            log "⚡ Grok старт: $TASK_ID ($PRIORITY) [worktree]"
            timeout "$TASK_TIMEOUT" grok $GROK_FLAGS \
                -w "agentforge-$TASK_ID" \
                -p "$PROMPT" 2>&1 | tee -a "$TASK_LOG"
            GROK_EXIT=$?

            END_TIME=$(date +%s)
            DURATION=$((END_TIME - START_TIME))

            # Определяем статус
            if [ "$GROK_EXIT" -eq 124 ]; then
                STATUS="failed"
                RESULT="Grok: timeout (${TASK_TIMEOUT}s) ⏱️"
            elif [ "$DURATION" -le 3 ]; then
                STATUS="failed"
                RESULT="Grok: слишком быстро (${DURATION}s) — проверьте лог"
            else
                STATUS="review"
                RESULT="Grok: ${DURATION}s ✅"
            fi

            # Обновляем задачу
            curl -s -X PATCH "$API/tasks/$TASK_ID" \
                -H 'Content-Type: application/json' \
                -d "{\"status\": \"$STATUS\", \"assigned_agent\": \"grok\", \"result\": \"$RESULT\", \"duration_seconds\": $DURATION}" > /dev/null

            log "✅ $TASK_ID: $RESULT"

            # Guardian auto-review
            if [ "$STATUS" = "review" ]; then
                sleep 1
                curl -s -X POST "$API/tasks/$TASK_ID/review" > /dev/null 2>&1
                log "🛡️ Guardian для $TASK_ID"
            fi

            # Очищаем worktree
            cd "$PROJECT_DIR" 2>/dev/null
            git worktree remove "agentforge-$TASK_ID" --force 2>/dev/null

        ) &

        RUNNING=$((RUNNING + 1))

        # Проверяем лимит
        if [ "$RUNNING" -ge "$MAX_PARALLEL" ]; then
            log "⏸️ Достигнут лимит $MAX_PARALLEL параллельных задач, ждём..."
            break
        fi

        sleep 1

    done < "$PARSED_FILE"

    sleep "$POLL_INTERVAL"
done
