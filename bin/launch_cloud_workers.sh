#!/bin/bash
# ============================================
# Multi-Key Cloud Worker Launcher
# Позволяет запускать облачных агентов на разных xAI ключах
#
# Примеры использования:
#   ./bin/launch_cloud_workers.sh mb2 3     # 3 агента на втором ключе (MB2)
#   ./bin/launch_cloud_workers.sh mb3 2     # 2 агента на первом ключе (MB3)
#   ./bin/launch_cloud_workers.sh both 3    # по 3 агента на каждом ключе
# ============================================

set -e

KEY_ALIAS="${1:-}"
COUNT="${2:-2}"

ENV_DIR="/home/agx/agentforge"
LOG_DIR="/home/agx/agentforge/logs"

mkdir -p "$LOG_DIR"

launch_workers() {
    local env_file="$1"
    local count="$2"
    local label="$3"

    if [ ! -f "$env_file" ]; then
        echo "❌ Файл $env_file не найден!"
        return 1
    fi

    echo "🚀 Запускаю $count облачных агентов на ключе $label ($env_file)..."

    for i in $(seq 1 "$count"); do
        (
            export $(grep -v '^#' "$env_file" | xargs)
            nohup bash "$ENV_DIR/grok_xai_worker.sh" > /dev/null 2>&1 &
            echo "   + Cloud worker #$i на $label запущен (PID $!)"
        )
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
        exit 1
        ;;
esac

echo ""
echo "Готово. Проверить:"
echo "  ps aux | grep grok_xai_worker | grep -v grep"
echo ""
echo "Остановить все облачные:"
echo "  pkill -f grok_xai_worker.sh"
