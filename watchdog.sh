#!/bin/bash
# ============================================
# AgentForge Watchdog — контроль зависших задач + эскалация
# Если агент завис → задача эскалируется к более опытному
# Цепочка: jules → grok → antigravity → failed
# Запуск через cron: */5 * * * * bash ~/agentforge/watchdog.sh
# ============================================

API="http://localhost:8080"
LOG_DIR="/home/agx/agentforge/logs"
TIMEOUT_MINUTES=30  # Таймаут для обычных задач
CRITICAL_TIMEOUT=60 # Таймаут для critical (best-of-n дольше)

echo "[Watchdog] $(date '+%H:%M:%S') Проверка зависших задач..." >> "$LOG_DIR/watchdog.log"

# Получаем задачи в работе и проверяем таймауты
curl -s "$API/tasks" 2>/dev/null | python3 -c "
import sys, json, urllib.request
from datetime import datetime, timezone

API = '$API'
tasks = json.load(sys.stdin)
now = datetime.now(timezone.utc)

# Цепочка эскалации: кто следующий если агент завис
# jules → grok → antigravity → failed (конец цепочки)
ESCALATION = {
    'jules': 'grok',
    'grok': 'antigravity',
    'antigravity': None,  # Некуда эскалировать — failed
    'auto': 'grok',
}

for t in tasks:
    if t['status'] not in ('dispatched', 'in_progress'):
        continue
    
    # Берём время начала
    started = t.get('started_at') or t.get('updated_at') or t.get('created_at')
    if not started:
        continue
    
    try:
        dt = datetime.fromisoformat(started.replace('Z', '+00:00'))
    except:
        continue
    
    timeout = $CRITICAL_TIMEOUT if t.get('priority') == 'critical' else $TIMEOUT_MINUTES
    age_minutes = (now - dt).total_seconds() / 60
    
    if age_minutes <= timeout:
        continue
    
    agent = t.get('assigned_agent', 'auto')
    next_agent = ESCALATION.get(agent)
    task_id = t['id']
    title = t['title']
    age = round(age_minutes)
    
    if next_agent:
        # Эскалация — передаём более опытному агенту
        escalation_note = f'Эскалация: {agent} завис ({age}m), передано → {next_agent}'
        update = {
            'status': 'pending',
            'assigned_agent': None,
            'result': escalation_note,
        }
        # Обновляем preferred_agent для маршрутизации
        data = json.dumps(update).encode()
        req = urllib.request.Request(
            f'{API}/tasks/{task_id}',
            data=data,
            headers={'Content-Type': 'application/json'},
            method='PATCH'
        )
        urllib.request.urlopen(req)
        
        # Принудительно ставим preferred_agent через отдельный PATCH
        force = json.dumps({'preferred_agent': next_agent, 'status': 'pending'}).encode()
        req2 = urllib.request.Request(
            f'{API}/tasks/{task_id}',
            data=force,
            headers={'Content-Type': 'application/json'},
            method='PATCH'
        )
        try:
            urllib.request.urlopen(req2)
        except:
            pass
        
        print(f'ESCALATE|{task_id[:8]}|{title[:40]}|{agent} → {next_agent}|{age}m')
    else:
        # Конец цепочки — некуда эскалировать
        update = {
            'status': 'failed',
            'result': f'Все агенты не справились ({agent} завис {age}m). Требуется ручное вмешательство ⚠️',
        }
        data = json.dumps(update).encode()
        req = urllib.request.Request(
            f'{API}/tasks/{task_id}',
            data=data,
            headers={'Content-Type': 'application/json'},
            method='PATCH'
        )
        urllib.request.urlopen(req)
        print(f'FAILED|{task_id[:8]}|{title[:40]}|{agent} — конец цепочки|{age}m')

print('DONE')
" | while IFS='|' read -r ACTION TASK_ID TITLE DETAIL AGE; do
    case "$ACTION" in
        ESCALATE)
            echo "[Watchdog] 🔄 Эскалация: $TASK_ID — $TITLE ($DETAIL, $AGE)" | tee -a "$LOG_DIR/watchdog.log"
            # Убиваем зависший процесс
            pkill -f "$TASK_ID" 2>/dev/null
            ;;
        FAILED)
            echo "[Watchdog] ❌ Провал: $TASK_ID — $TITLE ($DETAIL, $AGE)" | tee -a "$LOG_DIR/watchdog.log"
            pkill -f "$TASK_ID" 2>/dev/null
            ;;
        DONE)
            echo "[Watchdog] ✅ Проверка завершена" >> "$LOG_DIR/watchdog.log"
            ;;
    esac
done
