#!/bin/bash
# ============================================
# AgentForge Zombie Reaper — страховочный скрипт
# Обнаруживает и логирует зомби-процессы, отправляет SIGCHLD родителям.
# Устанавливается в cron каждые 5 минут.
# Защищён от гонок данных (flock), логических ошибок при пустых списках,
# и узких мест (один ps + атомарная запись отчёта + безопасная ротация).
# ============================================

# Защита от unset HOME в cron-окружении
if [ -z "${HOME:-}" ]; then
    HOME=$(getent passwd "$(id -un 2>/dev/null || echo eveselove)" 2>/dev/null | cut -d: -f6 || echo "/home/eveselove")
fi

LOG_FILE="${HOME}/agentforge/logs/zombie_reaper.log"
mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || true

# === Блокировка от параллельных запусков (критично для cron */5: предотвращает
# гонки на >> в лог, TOCTOU size+mv при ротации, и двойной ps) ===
LOCKFILE="/tmp/zombie_reaper.lock"
exec 9>"$LOCKFILE" 2>/dev/null || exit 0
if ! flock -n 9 2>/dev/null; then
    exit 0  # другой экземпляр держит лок — выходим тихо, без шума в cron
fi

# Считаем зомби (один вызов ps — устранено дублирование)
ZOMBIE_LIST=$(ps -eo stat,pid,ppid,user,comm 2>/dev/null | grep '^Z' || true)
ZOMBIE_COUNT=$([ -z "$ZOMBIE_LIST" ] && echo 0 || echo "$ZOMBIE_LIST" | wc -l)

if [ "${ZOMBIE_COUNT:-0}" -gt 0 ]; then
    TS=$(date '+%Y-%m-%d %H:%M:%S')
    # Атомарный блок записи всего отчёта одним >> (меньше interleaving даже без лока)
    {
        echo "[$TS] ⚠️ Обнаружено $ZOMBIE_COUNT зомби-процесс(ов):"
        echo "$ZOMBIE_LIST"

        # Отправляем SIGCHLD каждому уникальному родителю — напоминаем wait()
        echo "$ZOMBIE_LIST" | awk '{print $3}' | sort -u | while read -r ppid; do
            if [ -n "$ppid" ] && [ "$ppid" != "1" ]; then
                kill -SIGCHLD "$ppid" 2>/dev/null && \
                    echo "  → SIGCHLD отправлен родителю PID=$ppid"
            fi
        done

        echo ""
    } >> "$LOG_FILE"
fi

# Ротация лога (макс 1MB) — безопасная (с .new + cleanup, защищена от гонок flock'ом)
if [ -f "$LOG_FILE" ]; then
    LOG_SIZE=$(stat -c%s "$LOG_FILE" 2>/dev/null || echo 0)
    if [ "${LOG_SIZE:-0}" -gt 1048576 ]; then
        tail -c 524288 "$LOG_FILE" > "${LOG_FILE}.new" && \
            mv -f "${LOG_FILE}.new" "$LOG_FILE" || rm -f "${LOG_FILE}.new" 2>/dev/null || true
    fi
fi
