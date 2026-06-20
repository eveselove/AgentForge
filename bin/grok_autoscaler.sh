#!/bin/bash
# ============================================
# AgentForge Grok Autoscaler v1.0
# Автоматически масштабирует количество grok_worker инстансов
# под количество pending задач в Gateway.
#
# 11 задач → 11 воркеров, 300 задач → 300 воркеров
# Воркеры запускаются в tmux-сессии "grok-farm"
#
# Запуск: bash ~/agentforge/bin/grok_autoscaler.sh
# Остановка: tmux kill-session -t grok-farm
# ============================================

set -euo pipefail

API_BASE="${AGENTFORGE_API:-http://localhost:9090}"
POLL_INTERVAL=10          # Проверять каждые 10 секунд
MAX_WORKERS=500           # Жёсткий потолок воркеров (поддерживает 300+ параллельных Grok per user request 2026-06-14)
MIN_WORKERS=1             # Минимум всегда держим 1 воркер
WORKERS_PER_TASK=1        # 1 воркер на 1 задачу
SCALE_DOWN_DELAY=120      # Ждать 2 минуты перед scale-down (чтобы не дёргать)
TMUX_SESSION="grok-farm"
WORKER_SCRIPT="$HOME/agentforge/grok_worker.sh"
LOG_FILE="$HOME/agentforge/logs/grok_autoscaler.log"

mkdir -p "$(dirname "$LOG_FILE")"

log() {
    echo "[Autoscaler $(date +%H:%M:%S)] $*" | tee -a "$LOG_FILE"
}

get_pending_count() {
    local count
    count=$(curl -sf "${API_BASE}/api/metrics" 2>/dev/null \
        | jq -r '.by_status.pending // 0' 2>/dev/null) || count=0
    echo "$count"
}

get_inprogress_count() {
    local count
    count=$(curl -sf "${API_BASE}/api/metrics" 2>/dev/null \
        | jq -r '.by_status.inprogress // 0' 2>/dev/null) || count=0
    echo "$count"
}

get_running_workers() {
    # Считаем количество живых окон в tmux-сессии grok-farm
    if tmux has-session -t "$TMUX_SESSION" 2>/dev/null; then
        tmux list-windows -t "$TMUX_SESSION" 2>/dev/null | wc -l
    else
        echo 0
    fi
}

ensure_tmux_session() {
    if ! tmux has-session -t "$TMUX_SESSION" 2>/dev/null; then
        tmux new-session -d -s "$TMUX_SESSION" -n "worker-0" "bash $WORKER_SCRIPT"
        log "🏗️ Создана tmux-сессия '$TMUX_SESSION' с 1 воркером"
    fi
}

scale_up() {
    local target=$1
    local current
    current=$(get_running_workers)
    local to_add=$((target - current))
    
    if [ "$to_add" -le 0 ]; then
        return
    fi
    
    log "⬆️ Scale UP: $current → $target (+$to_add воркеров)"
    
    for i in $(seq 1 "$to_add"); do
        local worker_id=$((current + i))
        tmux new-window -t "$TMUX_SESSION" -n "worker-$worker_id" \
            "MAX_PARALLEL=1 bash $WORKER_SCRIPT" 2>/dev/null || true
    done
    
    log "✅ Запущено $to_add новых воркеров (всего: $target)"
}

scale_down() {
    local target=$1
    local current
    current=$(get_running_workers)
    local to_remove=$((current - target))
    
    if [ "$to_remove" -le 0 ]; then
        return
    fi
    
    log "⬇️ Scale DOWN: $current → $target (-$to_remove воркеров)"
    
    # Убиваем окна с конца (последние добавленные)
    local windows
    windows=$(tmux list-windows -t "$TMUX_SESSION" -F "#{window_index}" 2>/dev/null | sort -rn)
    local removed=0
    for wid in $windows; do
        if [ "$removed" -ge "$to_remove" ]; then
            break
        fi
        # Не убиваем первое окно (worker-0)
        if [ "$wid" -gt 0 ]; then
            tmux kill-window -t "$TMUX_SESSION:$wid" 2>/dev/null || true
            removed=$((removed + 1))
        fi
    done
    
    log "✅ Остановлено $removed воркеров (осталось: $target)"
}

# ============================================
# Главный цикл автоскейлера
# ============================================

log "🚀 AgentForge Grok Autoscaler v1.0 запущен"
log "📊 Конфиг: poll=${POLL_INTERVAL}s, max=$MAX_WORKERS, min=$MIN_WORKERS"
log "🎯 Стратегия: 1 задача = 1 воркер (instant scale)"

ensure_tmux_session

last_scale_down_time=0

while true; do
    pending=$(get_pending_count)
    inprog=$(get_inprogress_count)
    current=$(get_running_workers)
    
    # Нужное количество воркеров = pending + in_progress задачи
    # (in_progress уже обрабатываются, но воркеры могут быть заняты)
    desired=$((pending + inprog))
    
    # Ограничения
    if [ "$desired" -lt "$MIN_WORKERS" ]; then
        desired=$MIN_WORKERS
    fi
    if [ "$desired" -gt "$MAX_WORKERS" ]; then
        desired=$MAX_WORKERS
    fi
    
    if [ "$desired" -gt "$current" ]; then
        # Scale UP — мгновенно!
        scale_up "$desired"
    elif [ "$desired" -lt "$current" ]; then
        # Scale DOWN — с задержкой (чтобы не дёргать при кратковременных паузах)
        now=$(date +%s)
        if [ $((now - last_scale_down_time)) -ge "$SCALE_DOWN_DELAY" ]; then
            scale_down "$desired"
            last_scale_down_time=$now
        fi
    fi
    
    # Логируем статус каждый 6-й цикл (раз в минуту)
    if [ $((SECONDS % 60)) -lt "$POLL_INTERVAL" ]; then
        log "📊 Status: pending=$pending in_progress=$inprog workers=$current desired=$desired"
    fi
    
    sleep "$POLL_INTERVAL"
done
