#!/bin/bash
# ============================================
# Multi-Key Cloud Worker Launcher
# Позволяет запускать облачных агентов на разных xAI ключах
#
# Примеры использования:
#   ./bin/launch_cloud_workers.sh mb2 3     # 3 агента на втором ключе (MB2)
#   ./bin/launch_cloud_workers.sh mb3 2     # 2 агента на новом ключе (MB3)
#   ./bin/launch_cloud_workers.sh both 3    # по 3 агента на каждом ключе
# ============================================

set -e

# Derive paths from script location (portability; eliminates hardcoded /home/eveselove)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_DIR="$ENV_DIR/logs"

KEY_ALIAS="${1:-}"
COUNT="${2:-2}"

# Validate COUNT early (prevents logical error: seq fails or zero/negative spawns)
if ! [[ "$COUNT" =~ ^[1-9][0-9]*$ ]]; then
    echo "❌ COUNT must be positive integer (got: '$COUNT')"
    exit 1
fi

mkdir -p "$LOG_DIR"

# Reset PID list for this launch session (enables precise per-invocation stop; avoids stale pids)
: > "$LOG_DIR/.last_launch_pids"

# Early validation of worker script (logical error prevention: would fail later inside loop with confusing "launched" + silent)
WORKER_SCRIPT="$ENV_DIR/grok_xai_worker.sh"
if [ ! -f "$WORKER_SCRIPT" ]; then
    echo "❌ Worker script не найден: $WORKER_SCRIPT"
    exit 1
fi

# Serialize concurrent runs of launcher (fixes data race / duplicate workers / thundering herd from parallel script invocations)
LOCK_FILE="$LOG_DIR/.launch_cloud_workers.lock"
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    echo "❌ Другой экземпляр launch_cloud_workers.sh уже работает (lock: $LOCK_FILE)."
    echo "   Дождитесь или убейте предыдущий процесс."
    exit 1
fi
# (flock auto-releases on exit; no reentrancy issue since top-level once per script)

# Stagger delays made explicit (was narrow bottleneck comment; now tunable + self-documenting for swarm scaling)
LAUNCH_STAGGER=0.2
HEALTH_CHECK_DELAY=0.1

launch_workers() {
    local env_file="$1"
    local count="$2"
    local label="$3"

    if [ ! -f "$env_file" ]; then
        echo "❌ Файл $env_file не найден!"
        return 1
    fi

    echo "🚀 Запускаю $count облачных агентов на ключе $label ($env_file)..."

    for ((i=1; i<=count; i++)); do
        (
            # SAFE .env load via source (shell parser respects "quotes" and spaces in vals).
            # Original export $(grep|xargs) is fragile: strips quotes (xargs), splits on spaces in values,
            # mishandles leading-space comments and inline #. This was root of potential silent bad-env launches.
            # FIX: sed trim leading ws so "   VAR=1" or "  export FOO=.." lines (common .env formatting) don't break source.
            set -a
            # shellcheck disable=SC1090
            source <(grep -Ev '^[[:space:]]*(#|$)' "$env_file" | sed 's/^[[:space:]]*//' | tr -d "\r")
            nohup bash "$ENV_DIR/grok_xai_worker.sh" > "$LOG_DIR/grok_xai_worker_${label}_${i}.log" 2>&1 &
            pid=$!
            echo "   + Cloud worker #$i на $label запущен (PID $pid)"
            echo "$pid" >> "$LOG_DIR/.last_launch_pids"
            # Immediate health check (addresses logical gap: workers could die silently on bad key/parse,
            # launch would claim "запущен" with no user-visible error; output was /dev/null'ed).
            # Now: per-worker unique log (prevents cross-worker log write races + gives actionable inspect path).
            sleep "$HEALTH_CHECK_DELAY"
            if ! kill -0 "$pid" 2>/dev/null; then
                echo "   ⚠️  Cloud worker #$i на $label (PID $pid) exited immediately — inspect $LOG_DIR/grok_xai_worker_${label}_${i}.log + .env"
            fi
        ) || true  # prevent set -e from aborting remaining workers in COUNT or 'both' on transient subshell error
        sleep "$LAUNCH_STAGGER"  # throttle: mitigates narrow bottleneck (thundering herd on gateway WS / xAI API when launching batches)
    done
}

case "$KEY_ALIAS" in
    mb2)
        launch_workers "$ENV_DIR/.env.xai.mb2" "$COUNT" "MB2"
        ;;
    mb3)
        launch_workers "$ENV_DIR/.env.xai" "$COUNT" "MB3"
        ;;
    both)
        echo "=== Запуск на обоих ключах ==="
        launch_workers "$ENV_DIR/.env.xai.mb2" "$COUNT" "MB2"
        launch_workers "$ENV_DIR/.env.xai" "$COUNT" "MB3"
        ;;
    *)
        echo "Использование:"
        echo "  $0 mb2 <кол-во>     # запустить на MB2 (старый ключ)"
        echo "  $0 mb3 <кол-во>     # запустить на MB3 (новый ключ)"
        echo "  $0 both <кол-во>    # запустить по <кол-во> на каждом ключе"
        echo ""
        echo "Пример: $0 both 3     # итого 6 облачных агентов"
        echo "COUNT must be positive int (validated; default 2)"
        exit 1
        ;;
esac

echo ""
echo "Готово. Проверить:"
echo "  ps aux | grep grok_xai_worker | grep -v grep"
echo "  (PIDs printed above; each worker has independent XAI key + process)"
echo ""
if [ -s "$LOG_DIR/.last_launch_pids" ]; then
    pids=$(tr '\n' ' ' < "$LOG_DIR/.last_launch_pids")
    echo "Точные PID'ы этого запуска (для precise stop): $pids"
    echo "Остановить только их: kill $pids"
    echo ""
    echo "Остановить все облачные (fallback):"
    echo "  pkill -f grok_xai_worker.sh"
    echo "  # (note: affects all; kill \$pids above is safe+precise)"
else
    echo "Остановить все облачные:"
    echo "  pkill -f grok_xai_worker.sh"
    echo "  # (note: affects all; for precision use pkill -P <launcher-pid> or kill specific PIDs from launch output)"
fi
