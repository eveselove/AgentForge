#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# Тест параллельных сессий с ДЕТАЛЬНЫМ ЛОГИРОВАНИЕМ стадий
# Каждая стадия замеряется: старт → инициализация → ответ → итого
#
# Запуск: bash test_multi_agent_timed.sh [grok_count] [agy_count]
# ═══════════════════════════════════════════════════════════════

set -u

GROK_BIN="/home/eveselove/.grok/bin/grok"
AGY_BIN="/home/eveselove/.local/bin/agy"
PROJECT_DIR="/home/eveselove/planlytasksko"
LOG_DIR="/tmp/agentforge_timed_test"
TMUX_SESSION="agent-timed"

GROK_COUNT="${1:-5}"
AGY_COUNT="${2:-3}"
TOTAL=$((GROK_COUNT + AGY_COUNT))

mkdir -p "$LOG_DIR"
rm -f "$LOG_DIR"/*.log "$LOG_DIR"/*.txt "$LOG_DIR"/*.json

echo "╔═════════════════════════════════════════════════════════╗"
echo "║  🧪 Тайминг-тест параллельных агентов                  ║"
echo "║  Grok: $GROK_COUNT  |  AGY: $AGY_COUNT  |  Всего: $TOTAL                         ║"
echo "╚═════════════════════════════════════════════════════════╝"

# Убиваем старую сессию
tmux kill-session -t "$TMUX_SESSION" 2>/dev/null || true
sleep 0.3

tmux new-session -d -s "$TMUX_SESSION" -x 220 -y 50

GLOBAL_START=$(date +%s%3N)  # миллисекунды
echo "$GLOBAL_START" > "$LOG_DIR/global_start.txt"

WINDOW_IDX=0

# Скрипт-обёртка для каждого агента (с замером стадий)
create_agent_script() {
    local AGENT_TYPE="$1"  # grok | agy
    local LABEL="$2"
    local SESSION_LOG="$LOG_DIR/${LABEL}.log"
    local TIMING_FILE="$LOG_DIR/${LABEL}_timing.json"

    cat << 'AGENT_SCRIPT_EOF'
#!/bin/bash
AGENT_TYPE="__AGENT_TYPE__"
LABEL="__LABEL__"
SESSION_LOG="__SESSION_LOG__"
TIMING_FILE="__TIMING_FILE__"
GROK_BIN="__GROK_BIN__"
AGY_BIN="__AGY_BIN__"
PROJECT_DIR="__PROJECT_DIR__"
GLOBAL_START=$(cat "__LOG_DIR__/global_start.txt" 2>/dev/null || echo 0)

ms() { date +%s%3N; }
elapsed() { echo $(( $(ms) - $1 )); }
elapsed_global() { echo $(( $(ms) - GLOBAL_START )); }

T_QUEUE=$(ms)
echo "[$LABEL] ⏱️  QUEUED     +$(elapsed_global)ms (от глобального старта)" | tee "$SESSION_LOG"

# === Стадия 1: Инициализация (worktree, env) ===
T_INIT=$(ms)
echo "[$LABEL] 🔧 INIT_START +$(elapsed_global)ms" | tee -a "$SESSION_LOG"

# Для grok — проверяем worktree
if [ "$AGENT_TYPE" = "grok" ]; then
    WORK_DIR="/tmp/agentforge_test_${LABEL}"
    mkdir -p "$WORK_DIR" 2>/dev/null
fi

T_INIT_DONE=$(ms)
INIT_MS=$(elapsed $T_INIT)
echo "[$LABEL] 🔧 INIT_DONE  +$(elapsed_global)ms (init=${INIT_MS}ms)" | tee -a "$SESSION_LOG"

# === Стадия 2: Запуск CLI агента ===
T_EXEC=$(ms)
echo "[$LABEL] 🚀 EXEC_START +$(elapsed_global)ms" | tee -a "$SESSION_LOG"

PROMPT="Выведи в stdout фразу 'Session $LABEL timing test OK at $(date +%H:%M:%S)' и больше ничего не делай. Не создавай и не редактируй файлы."

if [ "$AGENT_TYPE" = "grok" ]; then
    timeout 120 "$GROK_BIN" --always-approve --cwd "$PROJECT_DIR" -p "$PROMPT" >> "$SESSION_LOG" 2>&1
    EXIT_CODE=$?
elif [ "$AGENT_TYPE" = "agy" ]; then
    timeout 120 "$AGY_BIN" --dangerously-skip-permissions --prompt "$PROMPT" >> "$SESSION_LOG" 2>&1
    EXIT_CODE=$?
fi

T_EXEC_DONE=$(ms)
EXEC_MS=$(elapsed $T_EXEC)
echo "[$LABEL] 🏁 EXEC_DONE  +$(elapsed_global)ms (exec=${EXEC_MS}ms, exit=$EXIT_CODE)" | tee -a "$SESSION_LOG"

# === Стадия 3: Проверка результата ===
T_CHECK=$(ms)
HAS_429=0
if grep -qi '429\|rate.limit\|too many\|resource.exhausted\|quota' "$SESSION_LOG" 2>/dev/null; then
    HAS_429=1
    STATUS="429_RATE_LIMIT"
elif [ "$EXIT_CODE" -eq 0 ]; then
    STATUS="OK"
elif [ "$EXIT_CODE" -eq 124 ]; then
    STATUS="TIMEOUT"
else
    STATUS="ERROR"
fi
T_CHECK_DONE=$(ms)
CHECK_MS=$(elapsed $T_CHECK)

# === Итого ===
TOTAL_MS=$(elapsed $T_QUEUE)
echo "" | tee -a "$SESSION_LOG"
echo "[$LABEL] ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" | tee -a "$SESSION_LOG"
echo "[$LABEL] 📊 ИТОГО:     ${TOTAL_MS}ms ($(( TOTAL_MS / 1000 ))с)" | tee -a "$SESSION_LOG"
echo "[$LABEL]    init:      ${INIT_MS}ms" | tee -a "$SESSION_LOG"
echo "[$LABEL]    exec:      ${EXEC_MS}ms ($(( EXEC_MS / 1000 ))с)" | tee -a "$SESSION_LOG"
echo "[$LABEL]    check:     ${CHECK_MS}ms" | tee -a "$SESSION_LOG"
echo "[$LABEL]    status:    $STATUS (exit=$EXIT_CODE)" | tee -a "$SESSION_LOG"
echo "[$LABEL]    429:       $HAS_429" | tee -a "$SESSION_LOG"
echo "[$LABEL] ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" | tee -a "$SESSION_LOG"

# JSON для агрегации
cat > "$TIMING_FILE" << JSONEOF
{
  "label": "$LABEL",
  "agent": "$AGENT_TYPE",
  "status": "$STATUS",
  "exit_code": $EXIT_CODE,
  "has_429": $HAS_429,
  "total_ms": $TOTAL_MS,
  "init_ms": $INIT_MS,
  "exec_ms": $EXEC_MS,
  "check_ms": $CHECK_MS,
  "global_offset_ms": $(elapsed_global)
}
JSONEOF

echo "--- [$LABEL] Готово ---"
sleep 15
AGENT_SCRIPT_EOF
}

# === Запуск Grok сессий ===
for i in $(seq 1 "$GROK_COUNT"); do
    LABEL="grok-$i"
    SCRIPT_FILE="$LOG_DIR/run_${LABEL}.sh"
    
    create_agent_script "grok" "$LABEL" > "$SCRIPT_FILE"
    
    # Подставляем переменные
    sed -i "s|__AGENT_TYPE__|grok|g" "$SCRIPT_FILE"
    sed -i "s|__LABEL__|$LABEL|g" "$SCRIPT_FILE"
    sed -i "s|__SESSION_LOG__|$LOG_DIR/${LABEL}.log|g" "$SCRIPT_FILE"
    sed -i "s|__TIMING_FILE__|$LOG_DIR/${LABEL}_timing.json|g" "$SCRIPT_FILE"
    sed -i "s|__GROK_BIN__|$GROK_BIN|g" "$SCRIPT_FILE"
    sed -i "s|__AGY_BIN__|$AGY_BIN|g" "$SCRIPT_FILE"
    sed -i "s|__PROJECT_DIR__|$PROJECT_DIR|g" "$SCRIPT_FILE"
    sed -i "s|__LOG_DIR__|$LOG_DIR|g" "$SCRIPT_FILE"
    chmod +x "$SCRIPT_FILE"
    
    if [ "$WINDOW_IDX" -eq 0 ]; then
        tmux rename-window -t "$TMUX_SESSION" "$LABEL"
        tmux send-keys -t "$TMUX_SESSION:$LABEL" "bash $SCRIPT_FILE" Enter
    else
        tmux new-window -t "$TMUX_SESSION" -n "$LABEL" "bash $SCRIPT_FILE"
    fi
    WINDOW_IDX=$((WINDOW_IDX + 1))
    echo "  🟦 $LABEL запущен"
    sleep 0.5
done

# === Запуск AGY сессий ===
for i in $(seq 1 "$AGY_COUNT"); do
    LABEL="agy-$i"
    SCRIPT_FILE="$LOG_DIR/run_${LABEL}.sh"
    
    create_agent_script "agy" "$LABEL" > "$SCRIPT_FILE"
    
    sed -i "s|__AGENT_TYPE__|agy|g" "$SCRIPT_FILE"
    sed -i "s|__LABEL__|$LABEL|g" "$SCRIPT_FILE"
    sed -i "s|__SESSION_LOG__|$LOG_DIR/${LABEL}.log|g" "$SCRIPT_FILE"
    sed -i "s|__TIMING_FILE__|$LOG_DIR/${LABEL}_timing.json|g" "$SCRIPT_FILE"
    sed -i "s|__GROK_BIN__|$GROK_BIN|g" "$SCRIPT_FILE"
    sed -i "s|__AGY_BIN__|$AGY_BIN|g" "$SCRIPT_FILE"
    sed -i "s|__PROJECT_DIR__|$PROJECT_DIR|g" "$SCRIPT_FILE"
    sed -i "s|__LOG_DIR__|$LOG_DIR|g" "$SCRIPT_FILE"
    chmod +x "$SCRIPT_FILE"
    
    tmux new-window -t "$TMUX_SESSION" -n "$LABEL" "bash $SCRIPT_FILE"
    WINDOW_IDX=$((WINDOW_IDX + 1))
    echo "  🟩 $LABEL запущен"
    sleep 0.5
done

# === Окно-агрегатор ===
AGGREGATOR_SCRIPT="$LOG_DIR/aggregator.sh"
cat > "$AGGREGATOR_SCRIPT" << 'AGGEOF'
#!/bin/bash
LOG_DIR="__LOG_DIR__"
TOTAL=__TOTAL__

echo "📊 Агрегатор результатов ($TOTAL агентов)"
echo "Ожидаю завершения..."
echo ""

WAITED=0
while [ $(ls "$LOG_DIR"/*_timing.json 2>/dev/null | wc -l) -lt "$TOTAL" ] && [ "$WAITED" -lt 180 ]; do
    DONE=$(ls "$LOG_DIR"/*_timing.json 2>/dev/null | wc -l)
    # Показываем лайв-статус каждого
    echo -ne "\r⏳ Готово: $DONE / $TOTAL (${WAITED}с)   "
    
    # Лайв-обновление по логам
    if [ $((WAITED % 10)) -eq 0 ] && [ "$WAITED" -gt 0 ]; then
        echo ""
        for f in "$LOG_DIR"/*.log; do
            [ -f "$f" ] || continue
            NAME=$(basename "$f" .log)
            LAST=$(grep -oP '\+\d+ms' "$f" 2>/dev/null | tail -1)
            STAGE=$(grep -oP '(QUEUED|INIT|EXEC|DONE)' "$f" 2>/dev/null | tail -1)
            echo "  ⏱️  $NAME: стадия=$STAGE $LAST"
        done
    fi
    sleep 2
    WAITED=$((WAITED + 2))
done

echo ""
echo ""
echo "╔═════════════════════════════════════════════════════════════════════╗"
echo "║                    📊 РЕЗУЛЬТАТЫ С ТАЙМИНГАМИ                      ║"
echo "╚═════════════════════════════════════════════════════════════════════╝"
echo ""

python3 << 'PYEOF'
import json, os, glob

log_dir = os.environ.get("LOG_DIR", "__LOG_DIR__")
files = sorted(glob.glob(f"{log_dir}/*_timing.json"))

if not files:
    print("❌ Нет результатов")
    exit(1)

results = []
for f in files:
    try:
        with open(f) as fh:
            results.append(json.load(fh))
    except Exception as e:
        print(f"⚠️ Ошибка чтения {f}: {e}")

grok = [r for r in results if r["agent"] == "grok"]
agy = [r for r in results if r["agent"] == "agy"]

print(f"{'Агент':<12} {'Статус':<16} {'Init':>8} {'Exec':>10} {'Total':>10} {'429?':>5}")
print("─" * 65)

for r in results:
    status_icon = "✅" if r["status"] == "OK" else "🚫" if r["status"] == "429_RATE_LIMIT" else "❌"
    init_s = f"{r['init_ms']}ms"
    exec_s = f"{r['exec_ms']/1000:.1f}s" if r["exec_ms"] > 1000 else f"{r['exec_ms']}ms"
    total_s = f"{r['total_ms']/1000:.1f}s" if r["total_ms"] > 1000 else f"{r['total_ms']}ms"
    r429 = "🚫" if r["has_429"] else "—"
    print(f"{r['label']:<12} {status_icon} {r['status']:<13} {init_s:>8} {exec_s:>10} {total_s:>10} {r429:>5}")

print("─" * 65)

ok = sum(1 for r in results if r["status"] == "OK")
rl = sum(1 for r in results if r["has_429"])
avg_exec = sum(r["exec_ms"] for r in results) / len(results) if results else 0
max_exec = max(r["exec_ms"] for r in results) if results else 0
min_exec = min(r["exec_ms"] for r in results) if results else 0

print(f"\n📈 Статистика:")
print(f"  Успешных:          {ok}/{len(results)}")
print(f"  Rate Limited:      {rl}")
print(f"  Среднее exec:      {avg_exec/1000:.1f}s")
print(f"  Мин exec:          {min_exec/1000:.1f}s")
print(f"  Макс exec:         {max_exec/1000:.1f}s")

if grok:
    avg_g = sum(r["exec_ms"] for r in grok) / len(grok)
    print(f"\n  Grok ({len(grok)} сессий):  avg={avg_g/1000:.1f}s")
if agy:
    avg_a = sum(r["exec_ms"] for r in agy) / len(agy)
    print(f"  AGY  ({len(agy)} сессий):  avg={avg_a/1000:.1f}s")

if rl > 0:
    print(f"\n⚡ ВЫВОД: {rl} получили 429 — уменьши параллелизм")
else:
    print(f"\n⚡ ВЫВОД: ВСЕ {len(results)} прошли без 429!")
PYEOF

echo ""
echo "Детальные логи: cat $LOG_DIR/<agent>.log"
AGGEOF

sed -i "s|__LOG_DIR__|$LOG_DIR|g" "$AGGREGATOR_SCRIPT"
sed -i "s|__TOTAL__|$TOTAL|g" "$AGGREGATOR_SCRIPT"
chmod +x "$AGGREGATOR_SCRIPT"

tmux new-window -t "$TMUX_SESSION" -n "📊results" "LOG_DIR=$LOG_DIR bash $AGGREGATOR_SCRIPT"

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  $TOTAL агентов запущены с детальным таймингом"
echo "  tmux attach -t $TMUX_SESSION"
echo "  Результаты: tmux select-window -t $TMUX_SESSION:📊results"
echo "═══════════════════════════════════════════════════════════"
