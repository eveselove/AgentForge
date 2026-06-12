#!/bin/bash
# =============================================================================
# Planly Health Check — Быстрая проверка всех сервисов
# Используется Uptime Kuma (Push monitor) и cron-алертами
#
# Использование:
#   ./scripts/healthcheck.sh          # Полный отчёт
#   ./scripts/healthcheck.sh --json   # JSON для мониторинга
#   ./scripts/healthcheck.sh --push   # Отправить в Uptime Kuma push endpoint
# =============================================================================

set -uo pipefail

# === Настройки ===
GATEWAY_URL="${GATEWAY_URL:-http://localhost:3000}"
VLM_URL="${VLM_URL:-http://localhost:8200}"
REDIS_HOST="${REDIS_HOST:-127.0.0.1}"
DISK_WARN_PERCENT=85
RAM_WARN_PERCENT=90
UPTIME_KUMA_PUSH_URL="${UPTIME_KUMA_PUSH_URL:-}"  # Например: http://localhost:3001/api/push/xxxxx

# === Проверки ===
STATUS="ok"
CHECKS=()
FAILED=()

check() {
    local name=$1 result=$2 detail=$3
    if [ "$result" = "ok" ]; then
        CHECKS+=("{\"name\":\"$name\",\"status\":\"ok\",\"detail\":\"$detail\"}")
    else
        CHECKS+=("{\"name\":\"$name\",\"status\":\"fail\",\"detail\":\"$detail\"}")
        FAILED+=("$name: $detail")
        STATUS="fail"
    fi
}

# 1. Gateway API
gw_response=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 5 "${GATEWAY_URL}/api/health" 2>/dev/null || echo "000")
if [ "$gw_response" = "200" ]; then
    gw_uptime=$(curl -s --connect-timeout 5 "${GATEWAY_URL}/api/health" 2>/dev/null | grep -o '"uptime":"[^"]*"' | cut -d'"' -f4)
    check "gateway" "ok" "HTTP 200, uptime: ${gw_uptime:-unknown}"
else
    check "gateway" "fail" "HTTP ${gw_response} (expected 200)"
fi

# 2. VLM Server (Jetson)
vlm_response=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 5 "${VLM_URL}/health" 2>/dev/null || echo "000")
if [ "$vlm_response" = "200" ]; then
    check "vlm" "ok" "HTTP 200"
else
    # VLM может быть на другом сервере — не критично если недоступен с GMKtec
    check "vlm" "fail" "HTTP ${vlm_response} (VLM сервер недоступен)"
fi

# 3. Redis
if command -v redis-cli &>/dev/null; then
    redis_ping=$(redis-cli -h "$REDIS_HOST" ping 2>/dev/null || echo "FAIL")
    if [ "$redis_ping" = "PONG" ]; then
        redis_keys=$(redis-cli -h "$REDIS_HOST" dbsize 2>/dev/null | awk '{print $2}')
        check "redis" "ok" "PONG, keys: ${redis_keys:-unknown}"
    else
        check "redis" "fail" "Нет ответа от Redis"
    fi
else
    check "redis" "fail" "redis-cli не установлен"
fi

# 4. Docker контейнеры
if command -v docker &>/dev/null; then
    running=$(docker ps --format '{{.Names}}' 2>/dev/null | wc -l)
    unhealthy=$(docker ps --filter "health=unhealthy" --format '{{.Names}}' 2>/dev/null)
    if [ -n "$unhealthy" ]; then
        check "docker" "fail" "Unhealthy: ${unhealthy}"
    else
        check "docker" "ok" "${running} контейнеров запущено"
    fi
else
    check "docker" "fail" "Docker не установлен"
fi

# 5. Диск
disk_usage=$(df -h / | awk 'NR==2 {print $5}' | tr -d '%')
disk_avail=$(df -h / | awk 'NR==2 {print $4}')
if [ "$disk_usage" -lt "$DISK_WARN_PERCENT" ]; then
    check "disk" "ok" "${disk_usage}% использовано, ${disk_avail} свободно"
else
    check "disk" "fail" "КРИТИЧНО: ${disk_usage}% использовано, осталось ${disk_avail}"
fi

# 6. RAM
ram_percent=$(free | awk '/Mem:/ {printf "%.0f", $3/$2 * 100}')
ram_avail=$(free -h | awk '/Mem:/ {print $7}')
if [ "$ram_percent" -lt "$RAM_WARN_PERCENT" ]; then
    check "ram" "ok" "${ram_percent}% использовано, ${ram_avail} свободно"
else
    check "ram" "fail" "ВЫСОКОЕ: ${ram_percent}% использовано, осталось ${ram_avail}"
fi

# 7. Последний бэкап
BACKUP_DIR="${HOME}/planlytasksko/backups/snapshots"
if [ -d "$BACKUP_DIR" ]; then
    latest_backup=$(ls -t "${BACKUP_DIR}"/snapshot_*.tar.gz 2>/dev/null | head -1)
    if [ -n "$latest_backup" ]; then
        backup_age_hours=$(( ($(date +%s) - $(stat -c %Y "$latest_backup" 2>/dev/null || echo 0)) / 3600 ))
        if [ "$backup_age_hours" -lt 48 ]; then
            check "backup" "ok" "Последний: ${backup_age_hours}ч назад"
        else
            check "backup" "fail" "Устарел: ${backup_age_hours}ч назад (>48ч)"
        fi
    else
        check "backup" "fail" "Снимки не найдены"
    fi
else
    check "backup" "fail" "Директория бэкапов не существует"
fi

# === Формирование отчёта ===
CHECKS_JSON=$(IFS=,; echo "[${CHECKS[*]}]")
REPORT="{\"status\":\"${STATUS}\",\"timestamp\":\"$(date -Iseconds)\",\"hostname\":\"$(hostname)\",\"checks\":${CHECKS_JSON}}"

case "${1:-}" in
    --json)
        echo "$REPORT"
        ;;
    --push)
        if [ -n "$UPTIME_KUMA_PUSH_URL" ]; then
            if [ "$STATUS" = "ok" ]; then
                curl -s "${UPTIME_KUMA_PUSH_URL}?status=up&msg=All%20checks%20passed" >/dev/null 2>&1
            else
                msg=$(printf '%s' "${FAILED[*]}" | head -c 200 | sed 's/ /%20/g')
                curl -s "${UPTIME_KUMA_PUSH_URL}?status=down&msg=${msg}" >/dev/null 2>&1
            fi
            echo "Push sent to Uptime Kuma (status: ${STATUS})"
        else
            echo "UPTIME_KUMA_PUSH_URL не задан"
            exit 1
        fi
        ;;
    *)
        echo "╔══════════════════════════════════════════════════╗"
        echo "║        Planly Infrastructure Health Check        ║"
        echo "╠══════════════════════════════════════════════════╣"
        echo "║  Время: $(date '+%Y-%m-%d %H:%M:%S')                  ║"
        echo "║  Хост:  $(hostname)                                    ║"
        echo "╚══════════════════════════════════════════════════╝"
        echo ""
        
        for check_json in "${CHECKS[@]}"; do
            name=$(echo "$check_json" | grep -o '"name":"[^"]*"' | cut -d'"' -f4)
            status=$(echo "$check_json" | grep -o '"status":"[^"]*"' | cut -d'"' -f4)
            detail=$(echo "$check_json" | grep -o '"detail":"[^"]*"' | cut -d'"' -f4)
            
            if [ "$status" = "ok" ]; then
                printf "  ✅ %-12s %s\n" "$name" "$detail"
            else
                printf "  ❌ %-12s %s\n" "$name" "$detail"
            fi
        done
        
        echo ""
        if [ "$STATUS" = "ok" ]; then
            echo "  ✅ Все проверки пройдены"
        else
            echo "  ⚠️  Обнаружены проблемы: ${#FAILED[@]}"
            for f in "${FAILED[@]}"; do
                echo "     → $f"
            done
        fi
        echo ""
        ;;
esac

# Код возврата: 0 = OK, 1 = проблемы
[ "$STATUS" = "ok" ] && exit 0 || exit 1
