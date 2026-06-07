#!/bin/bash
# ============================================
# AgentForge Grok XAI Cloud Worker v2
# Использует официальный xAI API (Grok 4 + Multi-Agent модели)
#
# Возможности:
# - Умная маршрутизация (берёт только сложные задачи)
# - Поддержка grok-4.20-multi-agent-0309
# - Легко запускается через systemd
#
# Запуск вручную:
#   export XAI_API_KEY="xai-..."
#   export XAI_MIN_COMPLEXITY=complex
#   nohup bash ~/agentforge/grok_xai_worker.sh &
#
# Рекомендуется использовать systemd (см. bin/install_grok_xai_workers.sh)
# ============================================

set -euo pipefail

API="http://localhost:8080"
LOG_DIR="/home/eveselove/agentforge/logs"
POLL_INTERVAL=10
MAX_PARALLEL=6          # Сколько задач этот воркер может держать одновременно
TASK_TIMEOUT=600
TMP_DIR="/tmp/agentforge/xai"

# === Умная маршрутизация (Smart Routing) ===
# По умолчанию XAI-воркер берёт только сложные задачи, чтобы не жечь деньги на мелочи.
# Локальные воркеры должны обрабатывать simple/medium.
XAI_MIN_COMPLEXITY="${XAI_MIN_COMPLEXITY:-complex}"   # complex | high | medium
XAI_FORCE_MULTI_AGENT="${XAI_FORCE_MULTI_AGENT:-0}"   # 1 = всегда использовать multi-agent модель

mkdir -p "$LOG_DIR" "$TMP_DIR"

# === Ключ xAI ===
if [ -z "${XAI_API_KEY:-}" ]; then
    echo "ERROR: XAI_API_KEY не установлен. Экспортируй ключ перед запуском."
    exit 1
fi

XAI_BASE="https://api.x.ai/v1"

log() {
    echo "[GrokXAI $(date '+%H:%M:%S')] $*" | tee -a "$LOG_DIR/grok_xai_worker.log"
}

running_tasks() {
    jobs -r 2>/dev/null | wc -l
}

# Простая функция вызова xAI Chat Completions
call_xai() {
    local model="$1"
    local prompt="$2"
    local max_tokens="${3:-8000}"

    curl -s "$XAI_BASE/chat/completions" \
        -H "Authorization: Bearer $XAI_API_KEY" \
        -H "Content-Type: application/json" \
        -d '{
            "model": "'"$model"'",
            "messages": [{"role": "user", "content": '"$(jq -Rs . <<< "$prompt")"'}],
            "temperature": 0.6,
            "max_tokens": '"$max_tokens"'
        }' | python3 -c '
import sys, json
data = json.load(sys.stdin)
if "choices" in data and data["choices"]:
    print(data["choices"][0]["message"]["content"])
elif "error" in data:
    print("XAI_ERROR:", data["error"].get("message", data["error"]))
else:
    print(json.dumps(data)[:500])
'
}

log "🚀 Grok XAI Cloud Worker запущен (max_parallel=$MAX_PARALLEL, poll=${POLL_INTERVAL}s)"

while true; do
    RUNNING=$(running_tasks)
    FREE=$((MAX_PARALLEL - RUNNING))
    if [ "$FREE" -le 0 ]; then
        sleep 4
        continue
    fi

    # Получаем задачи
    TASKS_FILE="$TMP_DIR/pending_xai.json"
    curl -s "$API/tasks" 2>/dev/null > "$TASKS_FILE"

    if [ ! -s "$TASKS_FILE" ]; then
        sleep "$POLL_INTERVAL"
        continue
    fi

    # === Умная маршрутизация: XAI берёт только достаточно сложные задачи ===
    python3 << PYEOF > "$TMP_DIR/selected_xai.txt"
import json, sys
with open("$TASKS_FILE") as f:
    tasks = json.load(f)

min_complexity = "$XAI_MIN_COMPLEXITY".lower()
complexity_order = {"simple": 0, "medium": 1, "high": 2, "complex": 3}
min_score = complexity_order.get(min_complexity, 2)

count = 0
for t in tasks:
    if t.get("status") != "pending":
        continue
    pref = str(t.get("preferred_agent") or "").lower()
    if pref not in ("auto", "grok", ""):
        continue

    complexity = str(t.get("complexity") or "medium").lower()
    priority = str(t.get("priority") or "medium").lower()

    score = complexity_order.get(complexity, 1)
    if priority in ("critical", "high"):
        score += 1

    if score < min_score:
        continue

    tags = ",".join(t.get("tags", []))
    print(f"{t['id']}\t{t.get('title','')}\t{t.get('description','')[:300]}\t{priority}\t{complexity}\t{tags}")
    count += 1
    if count >= $FREE:
        break
PYEOF

    if [ ! -s "$TMP_DIR/selected_xai.txt" ]; then
        sleep "$POLL_INTERVAL"
        continue
    fi

    while IFS=$'\t' read -r TASK_ID TITLE DESC PRIORITY COMPLEXITY TAGS; do
        [ -z "$TASK_ID" ] && continue

        log "📋 Cloud claim: $TASK_ID — $TITLE (priority=$PRIORITY, complexity=$COMPLEXITY)"

        # Claim задачу
        curl -s -X POST "$API/tasks/$TASK_ID/dispatch" > /dev/null 2>&1

        (
            TASK_LOG="$LOG_DIR/grok_xai_$TASK_ID.log"
            > "$TASK_LOG"

            PROMPT="$TITLE"
            [ -n "$DESC" ] && PROMPT="$PROMPT. Детали: $DESC"

            # === Выбор модели (с поддержкой Multi-Agent) ===
            if [[ "$XAI_FORCE_MULTI_AGENT" == "1" ]]; then
                MODEL="grok-4.20-multi-agent-0309"
            elif [[ "$COMPLEXITY" == "complex" || "$PRIORITY" == "critical" ]]; then
                # Для самых тяжёлых задач используем reasoning или multi-agent
                if [[ "$XAI_FORCE_MULTI_AGENT" != "1" ]]; then
                    MODEL="grok-4.20-0309-reasoning"
                else
                    MODEL="grok-4.20-multi-agent-0309"
                fi
            else
                MODEL="grok-4.20-0309-non-reasoning"
            fi

            # Если в тегах есть признаки multi-agent работы — переключаемся
            if [[ "$TAGS" == *"multi-agent"* || "$TAGS" == *"a2a"* || "$TITLE" == *"multi agent"* || "$TITLE" == *"оркестрац"* ]]; then
                MODEL="grok-4.20-multi-agent-0309"
            fi

            log "🧠 XAI → $TASK_ID model=$MODEL"

            START=$(date +%s)

            RESPONSE=$(call_xai "$MODEL" "$PROMPT" 12000)

            END=$(date +%s)
            DURATION=$((END - START))

            echo "$RESPONSE" >> "$TASK_LOG"

            if [[ "$RESPONSE" == XAI_ERROR:* ]]; then
                STATUS="failed"
                RESULT="XAI error: ${RESPONSE:10}"
            else
                STATUS="done"
                RESULT="XAI Grok ($MODEL) ответил за ${DURATION}s"
            fi

            # Обновляем задачу (кладём результат)
            RESULT_JSON=$(jq -n --arg result "$RESULT" --arg resp "$RESPONSE" \
                '{status: "'$STATUS'", assigned_agent: "grok-xai", result: $result, duration_seconds: '$DURATION'}')

            curl -s -X PATCH "$API/tasks/$TASK_ID" \
                -H 'Content-Type: application/json' \
                -d "$RESULT_JSON" > /dev/null

            log "✅ $TASK_ID завершена (model=$MODEL, ${DURATION}s)"

        ) &

    done < "$TMP_DIR/selected_xai.txt"

    sleep "$POLL_INTERVAL"
done
