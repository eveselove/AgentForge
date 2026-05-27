#!/bin/bash
# Запуск Grok Build для задачи AgentForge
# Поддерживает --check (самопроверка) и --best-of-n (параллельный запуск)
export PATH=/home/agx/.cargo/bin:/home/agx/.grok/bin:/home/agx/bin:$PATH
export NVM_DIR=/home/agx/.nvm
[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"

TASK_ID="$1"
TASK_DESC="$2"
PROJECT_DIR="${3:-/home/agx/planlytasksko}"
PRIORITY="${4:-medium}"
LOG_DIR="/home/agx/agentforge/logs"

echo "[AgentForge] Запуск Grok для задачи $TASK_ID" | tee -a $LOG_DIR/grok_$TASK_ID.log
cd "$PROJECT_DIR"

# Создаём ветку для задачи
git checkout -b agentforge/$TASK_ID 2>/dev/null || git checkout agentforge/$TASK_ID

# Определяем флаги в зависимости от приоритета
GROK_FLAGS="--always-approve --print"

# Для critical/high приоритета — включаем самопроверку
if [ "$PRIORITY" = "critical" ] || [ "$PRIORITY" = "high" ]; then
    GROK_FLAGS="$GROK_FLAGS --check"
    echo "[AgentForge] Включена самопроверка (--check)" | tee -a $LOG_DIR/grok_$TASK_ID.log
fi

# Для critical приоритета — best-of-n (параллельный запуск)
if [ "$PRIORITY" = "critical" ]; then
    GROK_FLAGS="$GROK_FLAGS --best-of-n 3"
    echo "[AgentForge] Best-of-3 для critical задачи" | tee -a $LOG_DIR/grok_$TASK_ID.log
fi

# Проверяем, есть ли фидбек от пользователя (HITL) в результате предыдущих попыток
FEEDBACK=$(python3 -c "
import urllib.request, json
try:
    with urllib.request.urlopen('http://localhost:8080/tasks/$TASK_ID') as resp:
        task = json.loads(resp.read().decode())
        result = task.get('result', '')
        if result and '[HITL Отклонено]:' in result:
            print(result)
except Exception as e:
    pass
")

if [ -n "$FEEDBACK" ]; then
    echo "[AgentForge] Найдено замечание пользователя (HITL фидбек):" | tee -a $LOG_DIR/grok_$TASK_ID.log
    echo "$FEEDBACK" | tee -a $LOG_DIR/grok_$TASK_ID.log
    # Добавляем фидбек к промпту задачи
    CLEAN_FEEDBACK=$(echo "$FEEDBACK" | sed 's/.*\[HITL Отклонено\]: //')
    FULL_PROMPT="$TASK_DESC. ВНИМАНИЕ: предыдущая попытка была отклонена пользователем с замечанием: $CLEAN_FEEDBACK. Пожалуйста, исправь это!"
else
    FULL_PROMPT="$TASK_DESC"
fi

# Выполняем поиск по векторной базе LanceDB для поиска релевантного опыта
CONTEXT=$(python3 /home/agx/agentforge/memory_helper.py search "$TASK_DESC" 2>/dev/null)
if [ -n "$CONTEXT" ]; then
    echo "[AgentForge RAG] Найдена релевантная информация в векторной памяти." | tee -a $LOG_DIR/grok_$TASK_ID.log
    FULL_PROMPT="$FULL_PROMPT $CONTEXT"
fi

# Запуск Grok
START_TIME=$(date +%s)
grok $GROK_FLAGS -p "$FULL_PROMPT" 2>&1 | tee -a $LOG_DIR/grok_$TASK_ID.log
END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))

echo "[AgentForge] Grok завершил задачу $TASK_ID за ${DURATION}с" | tee -a $LOG_DIR/grok_$TASK_ID.log

# === CI/CD: автоматическая проверка после завершения ===
echo "[AgentForge CI/CD] Запуск проверок..." | tee -a $LOG_DIR/grok_$TASK_ID.log

CI_RESULT="pass"

# Проверка Rust проектов
if [ -f "Cargo.toml" ]; then
    echo "[CI] cargo clippy..." | tee -a $LOG_DIR/grok_$TASK_ID.log
    cargo clippy --all-targets 2>&1 | tee -a $LOG_DIR/grok_$TASK_ID.log
    if [ $? -ne 0 ]; then CI_RESULT="clippy_fail"; fi
    
    echo "[CI] cargo test..." | tee -a $LOG_DIR/grok_$TASK_ID.log
    cargo test 2>&1 | tee -a $LOG_DIR/grok_$TASK_ID.log
    if [ $? -ne 0 ]; then CI_RESULT="test_fail"; fi
    
    echo "[CI] cargo build --release..." | tee -a $LOG_DIR/grok_$TASK_ID.log
    cargo build --release 2>&1 | tee -a $LOG_DIR/grok_$TASK_ID.log
    if [ $? -ne 0 ]; then CI_RESULT="build_fail"; fi
fi

# Проверка Python проектов
if [ -f "requirements.txt" ] || [ -f "pyproject.toml" ]; then
    echo "[CI] python tests..." | tee -a $LOG_DIR/grok_$TASK_ID.log
    python3 -m pytest 2>&1 | tee -a $LOG_DIR/grok_$TASK_ID.log
    if [ $? -ne 0 ]; then CI_RESULT="pytest_fail"; fi
fi

# Формируем результат
if [ "$CI_RESULT" = "pass" ]; then
    FINAL_STATUS="review"
    RESULT_MSG="Completed in ${DURATION}s. CI: all checks passed ✅"
else
    FINAL_STATUS="failed"
    RESULT_MSG="Completed in ${DURATION}s. CI failed: ${CI_RESULT} ❌"
fi

echo "[AgentForge CI/CD] Результат: $CI_RESULT" | tee -a $LOG_DIR/grok_$TASK_ID.log

# Обновляем статус задачи с метриками
curl -s -X PATCH http://localhost:8080/tasks/$TASK_ID \
  -H 'Content-Type: application/json' \
  -d "{\"status\": \"$FINAL_STATUS\", \"assigned_agent\": \"grok\", \"result\": \"$RESULT_MSG\"}"

# Если задача завершена успешно, сохраняем её в векторную память LanceDB
if [ "$FINAL_STATUS" = "review" ]; then
    echo "[AgentForge Memory] Сохраняем задачу в векторную память..." | tee -a $LOG_DIR/grok_$TASK_ID.log
    python3 /home/agx/agentforge/memory_helper.py save "$TASK_ID" >> $LOG_DIR/grok_$TASK_ID.log 2>&1
fi
