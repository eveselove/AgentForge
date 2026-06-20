#!/bin/bash
# ============================================
# AgentForge Grok XAI Cloud Worker v3 (WebSocket Push)
#
# Основной режим: WebSocket подписка на ws://localhost:9090/ws/tasks
# Fallback: HTTP polling (если websocat недоступен)
# Reconnect: exponential backoff (5s → 10s → 30s → 60s max)
#
# Запуск:
#   export XAI_API_KEY="xai-..."
#   nohup bash ~/agentforge/grok_xai_worker.sh &
# ============================================

set -euo pipefail

API="http://localhost:9090"
LOG_DIR="/home/eveselove/agentforge/logs"
POLL_INTERVAL=10
MAX_PARALLEL=6
TASK_TIMEOUT=600
TMP_DIR="/tmp/agentforge/xai"

# === Умная маршрутизация (Smart Routing) ===
XAI_MIN_COMPLEXITY="${XAI_MIN_COMPLEXITY:-complex}"
XAI_FORCE_MULTI_AGENT="${XAI_FORCE_MULTI_AGENT:-0}"

# === WebSocket конфиг ===
WEBSOCAT_BIN="$HOME/.cargo/bin/websocat"
WS_URL="ws://localhost:9090/ws/tasks?agent=grok"
WS_BACKOFF=5

mkdir -p "$LOG_DIR" "$TMP_DIR"

# === Ключ xAI ===
if [ -z "${XAI_API_KEY:-}" ]; then
    echo "ERROR: XAI_API_KEY не установлен."
    exit 1
fi

XAI_BASE="https://api.x.ai/v1"

log() {
    echo "[GrokXAI $(date '+%H:%M:%S')] $*" | tee -a "$LOG_DIR/grok_xai_worker.log"
}

running_tasks() {
    jobs -r 2>/dev/null | wc -l
}

# Вызов xAI Chat Completions API
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

# Выбор модели на основе сложности/приоритета
select_model() {
    local COMPLEXITY="$1" PRIORITY="$2" TAGS="$3"

    if [[ "$XAI_FORCE_MULTI_AGENT" == "1" ]]; then
        echo "grok-4.20-multi-agent-0309"; return
    fi
    if [[ "$TAGS" == *"multi-agent"* || "$TAGS" == *"a2a"* ]]; then
        echo "grok-4.20-multi-agent-0309"; return
    fi
    if [[ "$COMPLEXITY" == "complex" || "$PRIORITY" == "critical" ]]; then
        echo "grok-4.20-0309-reasoning"; return
    fi
    echo "grok-4.20-0309-non-reasoning"
}

# Обработка одной задачи (вызывается из WS и polling режимов)
process_task() {
    local TASK_ID="$1" TITLE="$2" DESC="$3" PRIORITY="$4" COMPLEXITY="$5" TAGS="$6"
    local TASK_LOG="$LOG_DIR/grok_xai_$TASK_ID.log"
    > "$TASK_LOG"

    local PROMPT="$TITLE"
    [ -n "$DESC" ] && PROMPT="$PROMPT. Детали: $DESC"

    local MODEL
    MODEL=$(select_model "$COMPLEXITY" "$PRIORITY" "$TAGS")

    log "🧠 XAI → $TASK_ID model=$MODEL"

    local START END DURATION RESPONSE STATUS RESULT
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

    # Обновляем задачу с результатом
    local RESULT_JSON
    RESULT_JSON=$(jq -n --arg result "$RESULT" --arg resp "$RESPONSE" \
        '{status: "'"$STATUS"'", assigned_agent: "grok-xai", result: $result, duration_seconds: '"$DURATION"'}')

    curl -s -X PATCH "$API/tasks/$TASK_ID" \
        -H 'Content-Type: application/json' \
        -d "$RESULT_JSON" > /dev/null

    log "✅ $TASK_ID завершена (model=$MODEL, ${DURATION}s)"
}

# Фильтрация задач по сложности/агенту
filter_tasks() {
    local json_file="$1"
    local max_count="$2"

    python3 << PYEOF
import json, sys
with open("$json_file") as f:
    data = json.load(f)

# Поддержка массива и одиночной WS-задачи
if isinstance(data, dict):
    inner = data.get("data", data)
    tasks = [inner] if isinstance(inner, dict) and "id" in inner else []
else:
    tasks = data

min_complexity = "$XAI_MIN_COMPLEXITY".lower()
complexity_order = {"simple": 0, "medium": 1, "high": 2, "complex": 3}
min_score = complexity_order.get(min_complexity, 2)

count = 0
for t in tasks:
    if t.get("status") not in ("pending", "dispatch", None, ""):
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
    if count >= $max_count:
        break
PYEOF
}

# Claim и запуск задач из файла selected.txt
dispatch_selected() {
    while IFS=$'\t' read -r TASK_ID TITLE DESC PRIORITY COMPLEXITY TAGS; do
        [ -z "$TASK_ID" ] && continue

        log "📋 Claim: $TASK_ID — $TITLE (priority=$PRIORITY, complexity=$COMPLEXITY)"
        curl -s -X POST "$API/tasks/$TASK_ID/dispatch" > /dev/null 2>&1

        process_task "$TASK_ID" "$TITLE" "$DESC" "$PRIORITY" "$COMPLEXITY" "$TAGS" &

    done < "$TMP_DIR/selected_xai.txt"
}

# ═══════════════════════════════════════════════════════
#  Главный цикл: WebSocket push + fallback на polling
# ═══════════════════════════════════════════════════════

log "🚀 Grok XAI Cloud Worker v3 запущен (max_parallel=$MAX_PARALLEL, mode=websocket+fallback)"

while true; do
    # === Режим 1: WebSocket push (если websocat доступен) ===
    if [ -x "$WEBSOCAT_BIN" ]; then
        log "🔌 WS подключение: $WS_URL"

        "$WEBSOCAT_BIN" "$WS_URL" --ping-interval 30 -t 2>/dev/null | while IFS= read -r line; do
            WS_BACKOFF=5  # Сброс backoff при успехе

            # Пропускаем пустые строки
            [ -z "$line" ] && continue

            # Проверяем что это валидный JSON
            echo "$line" | python3 -c "import sys,json; json.load(sys.stdin)" 2>/dev/null || continue

            RUNNING=$(running_tasks)
            FREE=$((MAX_PARALLEL - RUNNING))
            [ "$FREE" -le 0 ] && continue

            # Фильтруем задачу
            echo "$line" > "$TMP_DIR/ws_task.json"
            filter_tasks "$TMP_DIR/ws_task.json" "$FREE" > "$TMP_DIR/selected_xai.txt"

            if [ -s "$TMP_DIR/selected_xai.txt" ]; then
                dispatch_selected
            fi
        done

        # WS обрыв — reconnect с backoff
        log "⚠️ WS отключён, reconnect через ${WS_BACKOFF}s"
        sleep "$WS_BACKOFF"
        WS_BACKOFF=$((WS_BACKOFF * 2))
        [ "$WS_BACKOFF" -gt 60 ] && WS_BACKOFF=60

    else
        # === Режим 2: Polling fallback (если websocat не установлен) ===
        RUNNING=$(running_tasks)
        FREE=$((MAX_PARALLEL - RUNNING))
        if [ "$FREE" -le 0 ]; then
            sleep 4
            continue
        fi

        TASKS_FILE="$TMP_DIR/pending_xai.json"
        if ! curl -s "$API/tasks" 2>/dev/null > "$TASKS_FILE" || [ ! -s "$TASKS_FILE" ]; then
            # Backoff при недоступности API
            log "⚠️ API недоступен, retry через ${WS_BACKOFF}s"
            sleep "$WS_BACKOFF"
            WS_BACKOFF=$((WS_BACKOFF * 2))
            [ "$WS_BACKOFF" -gt 60 ] && WS_BACKOFF=60
            continue
        fi
        WS_BACKOFF=5  # Сброс backoff при успехе

        filter_tasks "$TASKS_FILE" "$FREE" > "$TMP_DIR/selected_xai.txt"

        if [ -s "$TMP_DIR/selected_xai.txt" ]; then
            dispatch_selected
        fi

        sleep "$POLL_INTERVAL"
    fi
done
