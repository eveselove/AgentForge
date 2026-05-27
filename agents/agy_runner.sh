#!/bin/bash
# Запуск Antigravity CLI для задачи AgentForge (серверные задачи)
export PATH=/home/agx/.cargo/bin:/home/agx/.grok/bin:/home/agx/bin:$PATH
export NVM_DIR=/home/agx/.nvm
[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"

TASK_ID="$1"
TASK_DESC="$2"
PROJECT_DIR="${3:-/home/agx/planlytasksko}"
LOG_DIR="/home/agx/agentforge/logs"

echo "[AgentForge] Запуск AGY для задачи $TASK_ID" | tee -a $LOG_DIR/agy_$TASK_ID.log
cd "$PROJECT_DIR"

# Создаём ветку для задачи
git checkout -b agentforge/$TASK_ID 2>/dev/null || git checkout agentforge/$TASK_ID

# Запуск agy в headless режиме
agy --prompt "$TASK_DESC" --yes 2>&1 | tee -a $LOG_DIR/agy_$TASK_ID.log

# Обновляем статус
curl -s -X PATCH http://localhost:8080/tasks/$TASK_ID \
  -H 'Content-Type: application/json' \
  -d '{"status": "review", "assigned_agent": "agy"}'

echo "[AgentForge] AGY завершил задачу $TASK_ID"
