#!/bin/bash
# Запуск Jules для задачи AgentForge
# Jules работает в облаке Google — поддерживает --parallel N
export PATH=/home/agx/.cargo/bin:/home/agx/bin:$PATH
export NVM_DIR=/home/agx/.nvm
[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"

TASK_ID="$1"
TASK_DESC="$2"
REPO="${3:-eveselove/planlytasksko}"
PRIORITY="${4:-medium}"
LOG_DIR="/home/agx/agentforge/logs"

echo "[AgentForge] Запуск Jules для задачи $TASK_ID" | tee -a $LOG_DIR/jules_$TASK_ID.log

# Параллельные сессии для critical задач
JULES_FLAGS=""
if [ "$PRIORITY" = "critical" ]; then
    JULES_FLAGS="--parallel 3"
elif [ "$PRIORITY" = "high" ]; then
    JULES_FLAGS="--parallel 2"
fi

START_TIME=$(date +%s)

# Запуск Jules — создаёт PR в GitHub (облако Google)
jules new $JULES_FLAGS --repo "$REPO" "$TASK_DESC" 2>&1 | tee -a $LOG_DIR/jules_$TASK_ID.log

END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))

# Обновляем статус
curl -s -X PATCH http://localhost:8080/tasks/$TASK_ID \
  -H 'Content-Type: application/json' \
  -d "{\"status\": \"review\", \"assigned_agent\": \"jules\", \"result\": \"Jules: ${DURATION}s, PR created ✅\", \"duration_seconds\": $DURATION}"

echo "[AgentForge] Jules отправил PR для задачи $TASK_ID (${DURATION}s)"
