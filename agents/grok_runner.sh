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
SKILL="${5:-}"
LOG_DIR="/home/agx/agentforge/logs"

echo "[AgentForge] Запуск Grok для задачи $TASK_ID" | tee -a $LOG_DIR/grok_$TASK_ID.log
cd "$PROJECT_DIR"

# Создаём ветку для задачи (опционально; grok -w создаст изолированный worktree)
git checkout -b agentforge/$TASK_ID 2>/dev/null || git checkout agentforge/$TASK_ID || true

# Определяем флаги в зависимости от приоритета (совместимо с headless grok CLI)
GROK_FLAGS="--always-approve"

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

# Получаем полные данные задачи (включая result с историей HITL-отказов)
TASK_DATA=$(curl -s "http://localhost:8080/tasks/$TASK_ID" 2>/dev/null | python3 -c '
import sys, json, re
try:
    d = json.load(sys.stdin)
    title = (d.get("title") or "").strip()
    desc = (d.get("description") or "").strip()
    result = (d.get("result") or "").strip()
    print("TITLE=" + title.replace("\n", " "))
    print("DESC=" + desc.replace("\n", " "))
    # Собираем ВСЮ историю фидбеков (поддержка повторных HITL reject)
    feedbacks = []
    for src in [result, desc]:
        if not src: continue
        for m in re.findall(r"\[HITL[^\]]*\][:\s]*(.*?)(?=\[HITL|$)", src, re.IGNORECASE | re.DOTALL):
            c = " ".join(m.strip().split())
            if c: feedbacks.append(c)
    for i, f in enumerate(feedbacks, 1):
        print(f"FEEDBACK_{i}=" + f)
except Exception:
    pass
' 2>/dev/null || echo "")

# Парсим TASK_DATA
TASK_TITLE=""
TASK_DESC_FULL=""
FEEDBACK_LINES=""
while IFS= read -r L; do
    case "$L" in
        TITLE=*) TASK_TITLE="${L#TITLE=}" ;;
        DESC=*) TASK_DESC_FULL="${L#DESC=}" ;;
        FEEDBACK_*) 
            fb="${L#FEEDBACK_?*=}"
            [ -n "$fb" ] && FEEDBACK_LINES="${FEEDBACK_LINES}- ${fb}\n"
            ;;
    esac
done <<EOT
$TASK_DATA
EOT

# Базовый промпт на основе title/desc (как в worker)
if [ -n "$TASK_TITLE" ]; then
    BASE_PROMPT="$TASK_TITLE"
    if [ -n "$TASK_DESC_FULL" ]; then
        BASE_PROMPT="$BASE_PROMPT. Детали: $TASK_DESC_FULL"
    fi
else
    BASE_PROMPT="$TASK_DESC"
fi

# Если есть история фидбеков — добавляем блок для grok (это и есть требуемая поддержка)
if [ -n "$FEEDBACK_LINES" ]; then
    echo "[AgentForge] Найдена история HITL-отказов, передаём фидбек в промпт:" | tee -a $LOG_DIR/grok_$TASK_ID.log
    echo -e "$FEEDBACK_LINES" | tee -a $LOG_DIR/grok_$TASK_ID.log
    FULL_PROMPT="$BASE_PROMPT

=== ВАЖНО: ИСТОРИЯ ОТКАЗОВ ПОЛЬЗОВАТЕЛЯ (HITL REJECT) ===
Эта задача имеет историю отклонений пользователем. Фидбек:
$FEEDBACK_LINES
Обязательно исправь все проблемы из списка выше. Не повторяй прошлые ошибки!
=== КОНЕЦ БЛОКА ФИДБЕКА ==="
else
    FULL_PROMPT="$BASE_PROMPT"
fi

# RAG по заголовку/описанию
RAG_QUERY="$TASK_TITLE"
[ -z "$RAG_QUERY" ] && RAG_QUERY="$TASK_DESC"
CONTEXT=$(python3 /home/agx/agentforge/memory_helper.py search "$RAG_QUERY" 2>/dev/null)
if [ -n "$CONTEXT" ]; then
    echo "[AgentForge RAG] Найдена релевантная информация в векторной памяти." | tee -a $LOG_DIR/grok_$TASK_ID.log
    FULL_PROMPT="$FULL_PROMPT $CONTEXT"
fi

# === Skills/Playbooks: инъекция system_prompt из YAML при наличии SKILL ===
SKILL_SYSTEM_PROMPT=""
SKILL_TIMEOUT="900"
SKILL_CI_CHECKS="[]"
SKILL_MODEL="grok"
if [ -n "$SKILL" ]; then
    echo "[AgentForge Skills] Загрузка playbook '$SKILL'..." | tee -a $LOG_DIR/grok_$TASK_ID.log
    SKILL_DATA=$(python3 -c '
import os, sys, yaml, json
skill_arg = sys.argv[1]
candidates = [
    os.path.expanduser(f"~/agentforge/skills/{skill_arg}.yaml"),
    os.path.expanduser(f"~/agentforge/skills/{skill_arg}.yml"),
    os.path.expanduser(f"~/agentforge/skills/{skill_arg}"),
]
path = None
for c in candidates:
    if os.path.exists(c):
        path = c
        break
if not path:
    print("SKILL_ERROR=no_file")
    sys.exit(0)
try:
    with open(path, "r", encoding="utf-8") as f:
        d = yaml.safe_load(f) or {}
    sp = d.get("system_prompt", "")
    print("SKILL_SYSTEM_PROMPT<<YAML_PROMPT_EOF")
    print(sp)
    print("YAML_PROMPT_EOF")
    print("SKILL_TIMEOUT=" + str(d.get("timeout", 900)))
    ci = d.get("ci_checks", [])
    print("SKILL_CI_CHECKS=" + json.dumps(ci, ensure_ascii=False))
    print("SKILL_MODEL=" + str(d.get("preferred_model", "grok")))
except Exception as e:
    print("SKILL_ERROR=" + str(e))
' "$SKILL" 2>/dev/null || echo "SKILL_ERROR=load_failed")

    # Парсим SKILL_DATA (аналогично TASK_DATA)
    while IFS= read -r L; do
        case "$L" in
            SKILL_SYSTEM_PROMPT<<YAML_PROMPT_EOF)
                SKILL_SYSTEM_PROMPT=""
                in_prompt=true
                ;;
            YAML_PROMPT_EOF)
                in_prompt=false
                ;;
            SKILL_TIMEOUT=*) SKILL_TIMEOUT="${L#SKILL_TIMEOUT=}" ;;
            SKILL_CI_CHECKS=*) SKILL_CI_CHECKS="${L#SKILL_CI_CHECKS=}" ;;
            SKILL_MODEL=*) SKILL_MODEL="${L#SKILL_MODEL=}" ;;
            SKILL_ERROR=*) echo "[AgentForge Skills] Ошибка загрузки: ${L#SKILL_ERROR=}" | tee -a $LOG_DIR/grok_$TASK_ID.log ;;
        esac
        if [ "${in_prompt:-false}" = "true" ] && [ "$L" != "SKILL_SYSTEM_PROMPT<<YAML_PROMPT_EOF" ]; then
            SKILL_SYSTEM_PROMPT="${SKILL_SYSTEM_PROMPT}${L}"$'\n'
        fi
    done <<EOT2
$SKILL_DATA
EOT2

    if [ -n "$SKILL_SYSTEM_PROMPT" ]; then
        echo "[AgentForge Skills] Инъекция system_prompt из playbook '$SKILL' (timeout=${SKILL_TIMEOUT}s)" | tee -a $LOG_DIR/grok_$TASK_ID.log
        FULL_PROMPT="=== PLAYBOOK: $SKILL ===
$SKILL_SYSTEM_PROMPT
=== END PLAYBOOK ===

$FULL_PROMPT"
    fi
fi

# Запуск Grok (worktree изоляция + корректные флаги CLI)
START_TIME=$(date +%s)
WORKTREE_NAME="agentforge-$TASK_ID"
echo "[AgentForge] Grok старт (worktree=$WORKTREE_NAME)" | tee -a $LOG_DIR/grok_$TASK_ID.log
grok $GROK_FLAGS -w "$WORKTREE_NAME" -p "$FULL_PROMPT" 2>&1 | tee -a $LOG_DIR/grok_$TASK_ID.log
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
