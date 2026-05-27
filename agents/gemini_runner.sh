#!/bin/bash
# Запуск Gemini Agent для задачи AgentForge
export HTTPS_PROXY=socks5://127.0.0.1:12335
# Gemini 2.5 Pro через REST API (бесплатный тир)
export PATH=/home/agx/bin:/home/agx/.cargo/bin:/home/agx/.grok/bin:/home/agx/bin:$PATH

TASK_ID="$1"
TASK_DESC="$2"
LOG_DIR="/home/agx/agentforge/logs"

echo "[AgentForge] Запуск Gemini Agent для задачи $TASK_ID" | tee -a $LOG_DIR/gemini_$TASK_ID.log

# Запуск gemini-agent (бесплатный Gemini 2.5 Pro/Flash)
gemini-agent "$TASK_DESC" 2>&1 | tee -a $LOG_DIR/gemini_$TASK_ID.log

# Обновляем статус задачи
curl -s -X PATCH http://localhost:8080/tasks/$TASK_ID \
  -H 'Content-Type: application/json' \
  -d '{"status": "review", "assigned_agent": "gemini"}'

echo "[AgentForge] Gemini завершил задачу $TASK_ID"
