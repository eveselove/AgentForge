#!/bin/bash
# Тест параллельных сессий Grok Build CLI
# Запускает N сессий одновременно с простой задачей и мониторит 429/ошибки
#
# Использование: bash test_parallel_grok.sh [кол-во_сессий]
# По умолчанию: 5

set -u

GROK_BIN="/home/eveselove/.grok/bin/grok"
PROJECT_DIR="/home/eveselove/planlytasksko"
LOG_DIR="/tmp/agentforge_parallel_test"
NUM_SESSIONS="${1:-5}"
MAX_SESSIONS=15  # жёсткий предел для безопасности

if [ "$NUM_SESSIONS" -gt "$MAX_SESSIONS" ]; then
    echo "⚠️  Лимит $MAX_SESSIONS сессий (запрошено $NUM_SESSIONS)"
    NUM_SESSIONS=$MAX_SESSIONS
fi

mkdir -p "$LOG_DIR"
rm -f "$LOG_DIR"/session_*.log "$LOG_DIR"/result_*.txt

echo "╔══════════════════════════════════════════════════════╗"
echo "║  🧪 Тест параллельных сессий Grok Build CLI         ║"
echo "║  Сессий: $NUM_SESSIONS                                          ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""
echo "Задача для каждой сессии: минимальная (echo файл)"
echo "Логи: $LOG_DIR/"
echo ""

# Запускаем N сессий параллельно
PIDS=()
START_TIME=$(date +%s)

for i in $(seq 1 "$NUM_SESSIONS"); do
    SESSION_LOG="$LOG_DIR/session_${i}.log"
    RESULT_FILE="$LOG_DIR/result_${i}.txt"
    
    (
        S_START=$(date +%s)
        echo "[Session $i] Старт: $(date '+%H:%M:%S')" > "$SESSION_LOG"
        
        # Простейшая задача — не меняет код, просто проверяет связь
        timeout 120 "$GROK_BIN" --always-approve --cwd "$PROJECT_DIR" \
            -p "Напиши в stdout фразу 'Session $i OK' и больше ничего не делай. Не создавай файлов, не меняй код." \
            >> "$SESSION_LOG" 2>&1
        EXIT_CODE=$?
        
        S_END=$(date +%s)
        S_DURATION=$((S_END - S_START))
        
        # Проверяем на 429
        if grep -qi "429\|rate.limit\|too many\|resource.exhausted\|quota" "$SESSION_LOG" 2>/dev/null; then
            echo "429_RATE_LIMIT|${S_DURATION}s|exit=$EXIT_CODE" > "$RESULT_FILE"
        elif [ "$EXIT_CODE" -eq 0 ]; then
            echo "OK|${S_DURATION}s|exit=$EXIT_CODE" > "$RESULT_FILE"
        elif [ "$EXIT_CODE" -eq 124 ]; then
            echo "TIMEOUT|${S_DURATION}s|exit=$EXIT_CODE" > "$RESULT_FILE"
        else
            echo "ERROR|${S_DURATION}s|exit=$EXIT_CODE" > "$RESULT_FILE"
        fi
    ) &
    
    PID=$!
    PIDS+=($PID)
    echo "🚀 Сессия $i запущена (PID=$PID)"
    
    # Небольшая задержка между запусками чтобы не все стартовали в одну мс
    sleep 1
done

echo ""
echo "⏳ Ожидаю завершения всех $NUM_SESSIONS сессий (таймаут 120с каждая)..."
echo ""

# Ждём все процессы
for pid in "${PIDS[@]}"; do
    wait "$pid" 2>/dev/null
done

END_TIME=$(date +%s)
TOTAL_DURATION=$((END_TIME - START_TIME))

# Собираем результаты
echo "╔══════════════════════════════════════════════════════╗"
echo "║                    📊 РЕЗУЛЬТАТЫ                    ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

OK_COUNT=0
RATE_LIMIT_COUNT=0
ERROR_COUNT=0
TIMEOUT_COUNT=0

for i in $(seq 1 "$NUM_SESSIONS"); do
    RESULT_FILE="$LOG_DIR/result_${i}.txt"
    if [ -f "$RESULT_FILE" ]; then
        RESULT=$(cat "$RESULT_FILE")
        STATUS=$(echo "$RESULT" | cut -d'|' -f1)
        DURATION=$(echo "$RESULT" | cut -d'|' -f2)
        
        case "$STATUS" in
            OK)
                echo "  ✅ Сессия $i: OK ($DURATION)"
                OK_COUNT=$((OK_COUNT + 1))
                ;;
            429_RATE_LIMIT)
                echo "  🚫 Сессия $i: 429 RATE LIMIT ($DURATION)"
                RATE_LIMIT_COUNT=$((RATE_LIMIT_COUNT + 1))
                ;;
            TIMEOUT)
                echo "  ⏰ Сессия $i: TIMEOUT ($DURATION)"
                TIMEOUT_COUNT=$((TIMEOUT_COUNT + 1))
                ;;
            *)
                echo "  ❌ Сессия $i: ERROR ($RESULT)"
                ERROR_COUNT=$((ERROR_COUNT + 1))
                ;;
        esac
    else
        echo "  ❓ Сессия $i: нет результата"
        ERROR_COUNT=$((ERROR_COUNT + 1))
    fi
done

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Всего сессий:     $NUM_SESSIONS"
echo "  ✅ Успешных:       $OK_COUNT"
echo "  🚫 Rate Limited:   $RATE_LIMIT_COUNT"
echo "  ⏰ Timeout:        $TIMEOUT_COUNT"
echo "  ❌ Ошибок:         $ERROR_COUNT"
echo "  ⏱️  Общее время:   ${TOTAL_DURATION}с"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [ "$RATE_LIMIT_COUNT" -gt 0 ]; then
    SAFE_LIMIT=$((OK_COUNT))
    echo ""
    echo "  ⚡ ВЫВОД: при $NUM_SESSIONS параллельных — $RATE_LIMIT_COUNT получили 429"
    echo "  ⚡ Безопасный лимит: ~$SAFE_LIMIT одновременных сессий"
else
    echo ""
    echo "  ⚡ ВЫВОД: все $NUM_SESSIONS сессий прошли без 429!"
    echo "  ⚡ Можно попробовать больше: bash $0 $((NUM_SESSIONS + 3))"
fi

echo ""
echo "Детальные логи: ls $LOG_DIR/session_*.log"
