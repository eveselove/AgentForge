#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# Тест параллельных сессий: Grok Build + AGY + Grok XAI
# Каждый агент — в отдельном tmux окне, своя квота
#
# Запуск: bash test_multi_agent_parallel.sh [grok_count] [agy_count]
# По умолчанию: 3 Grok + 2 AGY (= 5 параллельных агентов)
# ═══════════════════════════════════════════════════════════════

set -u

GROK_BIN="/home/eveselove/.grok/bin/grok"
AGY_BIN="/home/eveselove/.local/bin/agy"
PROJECT_DIR="/home/eveselove/planlytasksko"
LOG_DIR="/tmp/agentforge_multi_test"
TMUX_SESSION="agent-test"

GROK_COUNT="${1:-3}"
AGY_COUNT="${2:-2}"
TOTAL=$((GROK_COUNT + AGY_COUNT))

mkdir -p "$LOG_DIR"
rm -f "$LOG_DIR"/*.log "$LOG_DIR"/*.txt

echo "╔═════════════════════════════════════════════════════════╗"
echo "║  🧪 Мульти-агент параллельный тест                     ║"
echo "║  Grok Build:  $GROK_COUNT сессий (квота: xAI/SuperGrok)          ║"
echo "║  AGY:         $AGY_COUNT сессий (квота: Google Cloud)             ║"
echo "║  Всего:       $TOTAL агентов в $TOTAL терминалах                  ║"
echo "╚═════════════════════════════════════════════════════════╝"
echo ""

# Убиваем старую tmux-сессию если есть
tmux kill-session -t "$TMUX_SESSION" 2>/dev/null || true
sleep 0.5

# Создаём новую tmux-сессию
tmux new-session -d -s "$TMUX_SESSION" -x 200 -y 50

WINDOW_IDX=0

# === Запуск Grok Build сессий ===
for i in $(seq 1 "$GROK_COUNT"); do
    LABEL="grok-$i"
    SESSION_LOG="$LOG_DIR/${LABEL}.log"
    RESULT_FILE="$LOG_DIR/${LABEL}_result.txt"
    
    if [ "$WINDOW_IDX" -eq 0 ]; then
        tmux rename-window -t "$TMUX_SESSION" "$LABEL"
    else
        tmux new-window -t "$TMUX_SESSION" -n "$LABEL"
    fi
    
    # Скрипт для запуска внутри tmux-окна
    tmux send-keys -t "$TMUX_SESSION:$LABEL" "
echo '🚀 [$LABEL] Старт: \$(date \"+%H:%M:%S\")' | tee '$SESSION_LOG'
START=\$(date +%s)
timeout 120 $GROK_BIN --always-approve --cwd $PROJECT_DIR \
    -p 'Выведи в stdout фразу \"Session $LABEL parallel test OK\" и больше ничего не делай. Не создавай и не редактируй файлы.' \
    >> '$SESSION_LOG' 2>&1
EXIT_CODE=\$?
END=\$(date +%s)
DUR=\$((END - START))
if grep -qi '429\|rate.limit\|too many\|resource.exhausted\|quota' '$SESSION_LOG' 2>/dev/null; then
    echo '429_RATE_LIMIT|\${DUR}s|exit=\${EXIT_CODE}' > '$RESULT_FILE'
    echo '🚫 [$LABEL] RATE LIMITED (\${DUR}s)'
elif [ \"\$EXIT_CODE\" -eq 0 ]; then
    echo 'OK|\${DUR}s|exit=\${EXIT_CODE}' > '$RESULT_FILE'
    echo '✅ [$LABEL] OK (\${DUR}s)'
elif [ \"\$EXIT_CODE\" -eq 124 ]; then
    echo 'TIMEOUT|\${DUR}s|exit=\${EXIT_CODE}' > '$RESULT_FILE'
    echo '⏰ [$LABEL] TIMEOUT (\${DUR}s)'
else
    echo 'ERROR|\${DUR}s|exit=\${EXIT_CODE}' > '$RESULT_FILE'
    echo '❌ [$LABEL] ERROR exit=\${EXIT_CODE} (\${DUR}s)'
fi
echo '--- [$LABEL] Готово ---'
" Enter

    WINDOW_IDX=$((WINDOW_IDX + 1))
    echo "  🟦 Grok Build сессия $i → tmux окно '$LABEL'"
    sleep 1
done

# === Запуск AGY (Antigravity) сессий ===
for i in $(seq 1 "$AGY_COUNT"); do
    LABEL="agy-$i"
    SESSION_LOG="$LOG_DIR/${LABEL}.log"
    RESULT_FILE="$LOG_DIR/${LABEL}_result.txt"
    
    tmux new-window -t "$TMUX_SESSION" -n "$LABEL"
    
    tmux send-keys -t "$TMUX_SESSION:$LABEL" "
echo '🚀 [$LABEL] Старт: \$(date \"+%H:%M:%S\")' | tee '$SESSION_LOG'
START=\$(date +%s)
timeout 120 $AGY_BIN --dangerously-skip-permissions --prompt \
    'Выведи в stdout фразу \"Session $LABEL parallel test OK\" и больше ничего не делай. Не создавай и не редактируй файлы.' \
    >> '$SESSION_LOG' 2>&1
EXIT_CODE=\$?
END=\$(date +%s)
DUR=\$((END - START))
if grep -qi '429\|rate.limit\|too many\|resource.exhausted\|quota' '$SESSION_LOG' 2>/dev/null; then
    echo '429_RATE_LIMIT|\${DUR}s|exit=\${EXIT_CODE}' > '$RESULT_FILE'
    echo '🚫 [$LABEL] RATE LIMITED (\${DUR}s)'
elif [ \"\$EXIT_CODE\" -eq 0 ]; then
    echo 'OK|\${DUR}s|exit=\${EXIT_CODE}' > '$RESULT_FILE'
    echo '✅ [$LABEL] OK (\${DUR}s)'
elif [ \"\$EXIT_CODE\" -eq 124 ]; then
    echo 'TIMEOUT|\${DUR}s|exit=\${EXIT_CODE}' > '$RESULT_FILE'
    echo '⏰ [$LABEL] TIMEOUT (\${DUR}s)'
else
    echo 'ERROR|\${DUR}s|exit=\${EXIT_CODE}' > '$RESULT_FILE'
    echo '❌ [$LABEL] ERROR exit=\${EXIT_CODE} (\${DUR}s)'
fi
echo '--- [$LABEL] Готово ---'
" Enter

    WINDOW_IDX=$((WINDOW_IDX + 1))
    echo "  🟩 AGY сессия $i → tmux окно '$LABEL'"
    sleep 1
done

# === Окно-мониторинг ===
tmux new-window -t "$TMUX_SESSION" -n "monitor"
tmux send-keys -t "$TMUX_SESSION:monitor" "
echo '📊 Мониторинг результатов ($TOTAL агентов)...'
echo 'Ожидаю завершения всех сессий (таймаут 120с каждая)...'
echo ''

# Ждём пока все результаты появятся
WAITED=0
while [ \$(ls $LOG_DIR/*_result.txt 2>/dev/null | wc -l) -lt $TOTAL ] && [ \$WAITED -lt 150 ]; do
    DONE=\$(ls $LOG_DIR/*_result.txt 2>/dev/null | wc -l)
    echo -ne \"\\r⏳ Готово: \$DONE / $TOTAL (прошло \${WAITED}с)   \"
    sleep 3
    WAITED=\$((WAITED + 3))
done

echo ''
echo ''
echo '╔═════════════════════════════════════════════════════════╗'
echo '║                    📊 РЕЗУЛЬТАТЫ                       ║'
echo '╚═════════════════════════════════════════════════════════╝'
echo ''

OK=0; RL=0; TO=0; ER=0
for f in $LOG_DIR/*_result.txt; do
    NAME=\$(basename \$f _result.txt)
    RESULT=\$(cat \$f 2>/dev/null || echo 'NO_RESULT|?|?')
    STATUS=\$(echo \$RESULT | cut -d'|' -f1)
    DUR=\$(echo \$RESULT | cut -d'|' -f2)
    case \$STATUS in
        OK) echo \"  ✅ \$NAME: OK (\$DUR)\"; OK=\$((OK+1)) ;;
        429_RATE_LIMIT) echo \"  🚫 \$NAME: 429 RATE LIMIT (\$DUR)\"; RL=\$((RL+1)) ;;
        TIMEOUT) echo \"  ⏰ \$NAME: TIMEOUT (\$DUR)\"; TO=\$((TO+1)) ;;
        *) echo \"  ❌ \$NAME: ERROR (\$RESULT)\"; ER=\$((ER+1)) ;;
    esac
done

echo ''
echo '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'
echo \"  Grok Build: $GROK_COUNT сессий  |  AGY: $AGY_COUNT сессий  |  Всего: $TOTAL\"
echo \"  ✅ OK: \$OK  |  🚫 429: \$RL  |  ⏰ Timeout: \$TO  |  ❌ Error: \$ER\"
echo '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'
echo ''
if [ \$RL -gt 0 ]; then
    echo '⚡ ВЫВОД: Есть 429 — квоты недостаточно для такого параллелизма'
    echo '   Grok безопасно: '\$((OK - \$(ls $LOG_DIR/agy-*_result.txt 2>/dev/null | xargs grep -l OK 2>/dev/null | wc -l)))' сессий'
else
    echo '⚡ ВЫВОД: ВСЕ прошли без 429! Можно увеличить параллелизм.'
fi
" Enter

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  Все $TOTAL агентов запущены в tmux-сессии '$TMUX_SESSION'"
echo ""
echo "  Подключиться:  tmux attach -t $TMUX_SESSION"
echo "  Мониторинг:    tmux select-window -t $TMUX_SESSION:monitor"
echo "  Логи:          ls $LOG_DIR/"
echo "═══════════════════════════════════════════════════════════"
