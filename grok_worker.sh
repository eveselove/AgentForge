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
MEMORY_HELPER="/home/agx/agentforge/memory_helper.py"

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

            # Поиск похожих задач в LanceDB для RAG-контекста
            MEMORY_CONTEXT=$(python3 "$MEMORY_HELPER" search "$TITLE" 2>/dev/null || true)
            if [ -n "$MEMORY_CONTEXT" ]; then
                PROMPT="$PROMPT\n$MEMORY_CONTEXT"
                log "🧠 Найден релевантный опыт для $TASK_ID"
            fi

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

            # Сохранение результата в LanceDB векторную память
            if [ "$STATUS" = "review" ] || [ "$STATUS" = "done" ]; then
                python3 "$MEMORY_HELPER" save "$TASK_ID" 2>&1 | tee -a "$TASK_LOG"
                log "🧠 Память LanceDB обновлена для $TASK_ID"
            fi

            # Guardian auto-review
            if [ "$STATUS" = "review" ]; then
                sleep 1
                REVIEW_RESULT=$(curl -s -X POST "$API/tasks/$TASK_ID/review" 2>/dev/null)
                log "🛡️ Guardian для $TASK_ID"

                # Auto-PR Merge: если Guardian одобрил — мёржим ветку в main
                VERDICT=$(echo "$REVIEW_RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('verdict',''))" 2>/dev/null)
                if [ "$VERDICT" = "approved" ]; then
                    log "🔀 Auto-merge: agentforge-$TASK_ID → main"
                    cd "$PROJECT_DIR" || true

                    # Получаем имя ветки из worktree (может быть agentforge-TASK_ID)
                    BRANCH_NAME="agentforge-$TASK_ID"

                    # Проверяем существует ли ветка
                    if git rev-parse --verify "$BRANCH_NAME" >/dev/null 2>&1; then
                        # Переключаемся на main и мёржим
                        git checkout main 2>/dev/null
                        MERGE_OUTPUT=$(git merge "$BRANCH_NAME" --no-ff -m "[AgentForge] Auto-merge $TASK_ID: $TITLE" 2>&1)
                        MERGE_EXIT=$?

                        if [ "$MERGE_EXIT" -eq 0 ]; then
                            log "✅ Auto-merge успешен: $BRANCH_NAME → main"
                            # Обновляем задачу с информацией о мёрже
                            curl -s -X PATCH "$API/tasks/$TASK_ID"                                 -H 'Content-Type: application/json'                                 -d "{"result": "$RESULT | Guardian: approved | Merged to main"}" > /dev/null
                            # Удаляем ветку после мёржа
                            git branch -d "$BRANCH_NAME" 2>/dev/null
                            log "🗑️ Ветка $BRANCH_NAME удалена после мёржа"
                        else
                            log "❌ Auto-merge КОНФЛИКТ: $BRANCH_NAME → main"
                            log "   Вывод: $MERGE_OUTPUT"
                            # Откатываем неудачный мёрж
                            git merge --abort 2>/dev/null
                            # Обновляем задачу — нужен ручной мёрж
                            curl -s -X PATCH "$API/tasks/$TASK_ID"                                 -H 'Content-Type: application/json'                                 -d "{"result": "$RESULT | Guardian: approved | Merge conflict - needs manual merge"}" > /dev/null
                            log "⚠️ Задача $TASK_ID требует ручного мёржа"
                        fi
                    else
                        log "⚠️ Ветка $BRANCH_NAME не найдена, пропускаем auto-merge"
                    fi
                else
                    log "ℹ️ Guardian не одобрил $TASK_ID (verdict=$VERDICT), auto-merge пропущен"
                fi
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
