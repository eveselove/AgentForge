#!/bin/bash
# ============================================
# AgentForge Zombie Reaper — страховочный скрипт
# Обнаруживает и логирует зомби-процессы, отправляет SIGCHLD родителям.
# Устанавливается в cron каждые 5 минут.
# ============================================

LOG_FILE="${HOME}/agentforge/logs/zombie_reaper.log"
mkdir -p "$(dirname "$LOG_FILE")"

# Считаем зомби
ZOMBIE_LIST=$(ps -eo stat,pid,ppid,user,comm 2>/dev/null | grep '^Z')
ZOMBIE_COUNT=$(echo "$ZOMBIE_LIST" | grep -c '^Z' 2>/dev/null || echo 0)

if [ "$ZOMBIE_COUNT" -gt 0 ] 2>/dev/null; then
    TS=$(date '+%Y-%m-%d %H:%M:%S')
    echo "[$TS] ⚠️ Обнаружено $ZOMBIE_COUNT зомби-процесс(ов):" >> "$LOG_FILE"
    echo "$ZOMBIE_LIST" >> "$LOG_FILE"

    # Отправляем SIGCHLD каждому уникальному родителю — напоминаем wait()
    echo "$ZOMBIE_LIST" | awk '{print $3}' | sort -u | while read -r ppid; do
        if [ -n "$ppid" ] && [ "$ppid" != "1" ]; then
            kill -SIGCHLD "$ppid" 2>/dev/null && \
                echo "  → SIGCHLD отправлен родителю PID=$ppid" >> "$LOG_FILE" || true
        fi
    done

    echo "" >> "$LOG_FILE"
fi

# Ротация лога (макс 1MB)
if [ -f "$LOG_FILE" ]; then
    LOG_SIZE=$(stat -c%s "$LOG_FILE" 2>/dev/null || echo 0)
    if [ "$LOG_SIZE" -gt 1048576 ] 2>/dev/null; then
        tail -c 524288 "$LOG_FILE" > "${LOG_FILE}.tmp" && mv "${LOG_FILE}.tmp" "$LOG_FILE"
    fi
fi
