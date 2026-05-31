# 🔧 Практический гайд: Работа агентов с системой задач AgentForge

> **Версия:** 1.0 (2026-05-31)  
> **Аудитория:** Автономные агенты (Grok, Jules, Antigravity)  
> **Статус:** Переходный период (Python API → Rust CLI)

---

## Оглавление

1. [Текущий workflow (Python API)](#1-текущий-workflow-python-api)
2. [Целевой workflow (agentforge-runner)](#2-целевой-workflow-agentforge-runner)
3. [Статусы задач и переходы](#3-статусы-задач-и-переходы)
4. [Примеры команд для каждого шага](#4-примеры-команд-для-каждого-шага)
5. [Flywheel: самообучающийся цикл](#5-flywheel-самообучающийся-цикл)
6. [Лучшие практики](#6-лучшие-практики)
7. [Текущие ограничения и обходные пути](#7-текущие-ограничения-и-обходные-пути)
8. [Переменные окружения](#8-переменные-окружения)

---

## 1. Текущий workflow (Python API)

Сейчас **управление задачами** полностью реализовано в Python (FastAPI — `task_queue.py`).
**Flywheel (самоулучшение)** мигрирует на Rust (`agentforge-runner`).

### Архитектура

```
+-------------------------------------------------------+
|                   Python API (FastAPI)                  |
|                  http://localhost:8080                   |
|                                                         |
|  POST /tasks          — Создать задачу                  |
|  GET  /tasks          — Список задач (?status=...)      |
|  GET  /tasks/{id}     — Получить задачу                 |
|  PATCH /tasks/{id}    — Обновить (статус, результат)    |
|  POST /tasks/{id}/dispatch — Диспетчеризация            |
|  POST /tasks/pull     — Умный роутер (Work-Stealing)    |
|  POST /tasks/{id}/checkpoint — Сохранить чекпоинт       |
|  POST /tasks/{id}/review     — Guardian ревью           |
|  POST /review/all            — Ревью всех done          |
+-----------------------+-------------------------------  +
                        |
                        v
               +------------------+
               |  dispatcher.sh   |
               |  (bash glue)     |
               +--------+---------+
                        |
           +------------+---------------+
           v            v               v
    grok_runner.sh  jules_runner.sh  gemini_runner.sh
    (Grok Build)    (Jules async)    (Gemini agent)
```

### Жизненный цикл задачи (текущий)

```
1. Создание:     POST /tasks -> статус "pending"
2. Диспетчеризация: POST /tasks/{id}/dispatch
   -> resolve_agent() определяет агента (grok/jules/antigravity)
   -> select_skill() подбирает YAML playbook по тегам
   -> dispatcher.sh запускает соответствующий *_runner.sh
3. Выполнение:   *_runner.sh выполняет задачу
   -> статус "dispatched" -> "in_progress"
4. Завершение:   PATCH /tasks/{id} {status: "done", result: "..."}
5. Ревью:        POST /tasks/{id}/review (Guardian)
```

### Альтернативный путь: Pull-модель (Work-Stealing)

Вместо push-диспатча, `grok_worker.sh` **поллит** API:

```bash
# grok_worker.sh: бесконечный цикл
while true; do
    # Получаем pending задачи
    curl -s http://localhost:8080/tasks > /tmp/pending_tasks.json
    # Фильтруем подходящие
    # Запускаем grok_runner.sh в фоне
    sleep 15
done
```

---

## 2. Целевой workflow (agentforge-runner)

### Что уже мигрировано на Rust

Rust бинарник (`agentforge-runner`) **уже полностью владеет** flywheel-циклом:

| Компонент | Команда Rust | Статус |
|-----------|-------------|--------|
| Flywheel step (после задачи) | `agentforge-runner flywheel-step` | Продакшн |
| Непрерывный цикл | `agentforge-runner continuous` | Продакшн |
| Список кандидатов | `agentforge-runner candidate list` | Продакшн |
| Промоутинг скиллов | `agentforge-runner candidate promote` | Продакшн |
| Экспорт данных | `agentforge-runner flywheel-export` | Продакшн |
| Управление задачами | `agentforge-runner task create/claim/complete` | Ещё нет |

### Что остаётся в Python

| Компонент | Эндпоинт | Замечание |
|-----------|----------|-----------|
| Создание задач | `POST /tasks` | Python API — единственный путь |
| Диспетчеризация | `POST /tasks/{id}/dispatch` | Через Python + dispatcher.sh |
| Обновление статуса | `PATCH /tasks/{id}` | Python API |
| Pull/Work-Stealing | `POST /tasks/pull` | Умный роутер в Python |
| Guardian ревью | `POST /tasks/{id}/review` | Python API |
| Чекпоинты | `POST /tasks/{id}/checkpoint` | Python API |
| Arena/MoA | `/tasks/{id}/arena`, `/tasks/{id}/moa` | Мульти-агентные режимы |

### Целевая архитектура (когда task CLI будет готов)

```
+--------------------------------------------------------+
|              agentforge-runner (Rust CLI)                |
|                                                         |
|  task create --title "..." --tags "fix,rust"            |
|  task list --status pending                             |
|  task claim --agent grok                                |
|  task complete --id XXXX --result "..."                 |
|  flywheel-step --real-data --ingest                     |
|  continuous --top-n 3                                   |
|  candidate list / promote                               |
|                                                         |
|  <-- Один бинарник для ВСЕГО жизненного цикла -->       |
+--------------------------------------------------------+
```

---

## 3. Статусы задач и переходы

### Статусы (TaskStatus enum)

| Статус | Описание | Кто устанавливает |
|--------|----------|-------------------|
| `pending` | Создана, ожидает диспетчеризации | API (автоматически при создании) |
| `dispatched` | Отправлена агенту через dispatcher.sh | `POST /dispatch` |
| `in_progress` | Агент взял в работу | `PATCH` или `POST /tasks/pull` |
| `review` | Выполнена, ожидает ревью Guardian | Агент (PATCH status=review) |
| `done` | Завершена успешно | Агент (PATCH status=done) |
| `failed` | Провалена | Агент (PATCH status=failed) |

### Диаграмма переходов

```
                 +-----------+
                 |  pending  |<-----------------+
                 +-----+-----+                  |
                       |                        |
          POST /dispatch  или  POST /pull       | (re-dispatch
                       |                        |  при failed)
              +--------+--------+               |
              v                 v               |
        +------------+  +--------------+        |
        | dispatched |  | in_progress  |        |
        +------+-----+  +------+------+        |
               |               |                |
               +-------+-------+                |
                       |                        |
              +--------+--------+               |
              v                 v               |
        +-----------+    +-----------+          |
        |  review   |    |  failed   |----------+
        +-----+-----+    +-----------+
              |
              v
        +-----------+
        |   done    |
        +-----------+
```

### Автоматические действия при смене статуса

- `-> in_progress` / `-> dispatched`: автоматически устанавливается `started_at`
- `-> done` / `-> review`: автоматически устанавливается `completed_at`
- `-> done` / `-> failed`: триггерятся webhook-уведомления `task_completed`
- Любая смена статуса: WebSocket уведомление подписчикам

---

## 4. Примеры команд для каждого шага

### 4.1. Создание задачи

```bash
# Через curl (единственный текущий способ)
curl -s -X POST http://localhost:8080/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Исправить баг в парсере цен",
    "description": "Парсер stroylandia не обрабатывает цены с пробелами",
    "priority": "high",
    "tags": ["fix", "rust", "parser"],
    "preferred_agent": "grok"
  }'

# Ответ: {"id": "abc12345", "status": "pending", ...}
```

### 4.2. Просмотр задач

```bash
# Все задачи
curl -s http://localhost:8080/tasks | python3 -m json.tool

# Только pending
curl -s "http://localhost:8080/tasks?status=pending"

# Конкретная задача
curl -s http://localhost:8080/tasks/abc12345
```

### 4.3. Диспетчеризация (push-модель)

```bash
# API выбирает агента автоматически (resolve_agent + select_skill)
curl -s -X POST http://localhost:8080/tasks/abc12345/dispatch

# Ответ: {"task_id": "abc12345", "assigned_agent": "grok", "skill": "parser-fix", ...}
```

### 4.4. Pull-модель (агент сам берёт задачу)

```bash
# Агент запрашивает задачу для себя
curl -s -X POST "http://localhost:8080/tasks/pull?agent=grok"

# Если задача есть — возвращается задача (уже in_progress)
# Если нет — возвращается null
# Поддерживает Work-Stealing: если grok свободен, а jules перегружен,
# grok может "украсть" задачу jules
```

### 4.5. Обновление статуса (в процессе работы)

```bash
# Переход в in_progress (если через dispatch)
curl -s -X PATCH http://localhost:8080/tasks/abc12345 \
  -H "Content-Type: application/json" \
  -d '{"status": "in_progress"}'

# Сохранение чекпоинта (промежуточный прогресс)
curl -s -X POST http://localhost:8080/tasks/abc12345/checkpoint \
  -H "Content-Type: application/json" \
  -d '{
    "step_name": "parsing_fixed",
    "state_data": {"files_changed": ["src/parser.rs"], "tests_passed": 5}
  }'
```

### 4.6. Завершение задачи

```bash
# Успешное завершение
curl -s -X PATCH http://localhost:8080/tasks/abc12345 \
  -H "Content-Type: application/json" \
  -d '{
    "status": "done",
    "result": "Исправлен парсер цен. Добавлена обработка пробелов. 5 тестов пройдено.",
    "duration_seconds": 120,
    "tokens_used": 15000,
    "cost_usd": 0.05
  }'

# Провал
curl -s -X PATCH http://localhost:8080/tasks/abc12345 \
  -H "Content-Type: application/json" \
  -d '{
    "status": "failed",
    "result": "Ошибка компиляции: missing trait bound for PriceParser"
  }'
```

### 4.7. Ревью через Guardian

```bash
# Одна задача
curl -s -X POST http://localhost:8080/tasks/abc12345/review

# Все завершённые задачи
curl -s -X POST http://localhost:8080/review/all
```

---

## 5. Flywheel: самообучающийся цикл

### Что это и зачем

Flywheel — система самоулучшения агентов. После каждой задачи агент анализирует
результат и предлагает улучшения скиллов (YAML playbooks). Это **полностью на Rust**.

### Путь бинарника

```bash
# Продакшн (release, быстрый)
/home/agx/agentforge/rust/target/release/agentforge-runner

# Через переменную окружения (рекомендуется)
$AGENTFORGE_RUST_RUNNER
```

### Flywheel после завершения задачи

```bash
# После завершения задачи — запуск flywheel-step
$AGENTFORGE_RUST_RUNNER flywheel-step \
  --real-data \
  --limit 50 \
  --output-dir /tmp/fw_step \
  --ingest \
  --json

# С shadow-режимом (двойная проверка с Python)
AGENTFORGE_RUST_FLYWHEEL_SHADOW=1 \
$AGENTFORGE_RUST_RUNNER flywheel-step \
  --real-data \
  --limit 20 \
  --output-dir /tmp/shadow_fw \
  --shadow \
  --json
```

### Непрерывный цикл (continuous)

```bash
# Dry-run (безопасный, по умолчанию)
$AGENTFORGE_RUST_RUNNER continuous --top-n 3 --json

# Реальное выполнение
$AGENTFORGE_RUST_RUNNER continuous --top-n 2 --no-dry-run --json

# Health-файл для мониторинга
cat /tmp/agentforge_rust_flywheel/flywheel_health.json
```

### Управление кандидатами

```bash
# Список кандидатов (по learning value)
$AGENTFORGE_RUST_RUNNER candidate list --top 5 --sort value --json

# Список (по свежести)
$AGENTFORGE_RUST_RUNNER candidate list --top 3 --sort recency --json

# Промоутинг (dry-run — предпросмотр)
$AGENTFORGE_RUST_RUNNER candidate promote \
  20260531_055029_general-refactor_81e7d546 \
  --copy-to-skills --dry-run --json

# Реальный промоутинг
$AGENTFORGE_RUST_RUNNER candidate promote \
  20260531_055029_general-refactor_81e7d546 \
  --copy-to-skills
```

---

## 6. Лучшие практики

### Для воркеров (grok_worker.sh и подобных)

1. **Используйте pull-модель** (`POST /tasks/pull?agent=grok`) вместо ручной фильтрации
   pending задач — она поддерживает Work-Stealing и автоматическую маршрутизацию.

2. **Всегда сохраняйте чекпоинты** для задач длиннее 60 секунд — это позволяет
   продолжить при сбое.

3. **Запускайте flywheel после каждой задачи:**
   ```bash
   # В grok_runner.sh после завершения задачи:
   if [ "${AGENTFORGE_RUST_FLYWHEEL:-0}" = "1" ]; then
       $AGENTFORGE_RUST_RUNNER flywheel-step --real-data --ingest --json 2>/dev/null &
   fi
   ```

4. **Используйте `--json` флаг** для машино-читаемого вывода при парсинге результатов.

5. **Обновляйте метрики** при завершении — `tokens_used`, `cost_usd`, `duration_seconds`
   помогают оптимизировать маршрутизацию.

### Для агентов (правила работы с задачами)

1. **Проверяйте статус перед началом работы:**
   ```bash
   STATUS=$(curl -s http://localhost:8080/tasks/$TASK_ID | \
     python3 -c "import sys,json; print(json.load(sys.stdin)['status'])")
   if [ "$STATUS" != "dispatched" ] && [ "$STATUS" != "pending" ]; then
       echo "Задача уже в статусе $STATUS, пропускаю"
       exit 0
   fi
   ```

2. **Используйте git worktree** для изоляции (каждая задача в `/tmp/agentforge/TASK_ID`):
   ```bash
   WORK_DIR="/tmp/agentforge/$TASK_ID"
   git -C /home/agx/planlytasksko worktree add "$WORK_DIR" -b "agentforge/$TASK_ID" 2>/dev/null
   ```

3. **Делайте git commit** перед началом работы для безопасного отката.

4. **Сообщайте результат** — как успех, так и провал. Никогда не оставляйте задачу
   в `in_progress` навсегда.

### Для оркестратора (Antigravity)

1. **Декомпозируйте сложные задачи** на подзадачи с чёткими границами.
2. **Используйте теги** для правильной маршрутизации:
   `rust`, `fix`, `test`, `docs`, `architecture`, `parser`.
3. **Устанавливайте приоритеты** — `critical > high > medium > low`.
4. **Указывайте `preferred_agent`** когда точно знаете кто лучше справится:
   - `grok` — быстрые фиксы, Rust, серверная работа
   - `jules` — асинхронные GitHub PR, фоновые задачи
   - `antigravity` — архитектура, сложный анализ (human-in-the-loop!)

---

## 7. Текущие ограничения и обходные пути

### Ограничение 1: Нет `task` подкоманд в Rust CLI

**Проблема:** `agentforge-runner` ещё не имеет подкоманд `task create/claim/complete`.
Все операции с задачами идут через Python HTTP API.

**Обходной путь:** Используйте curl:
```bash
# Создание
curl -s -X POST http://localhost:8080/tasks -H "Content-Type: application/json" \
  -d '{"title": "...", "description": "...", "tags": ["..."]}'

# Обновление
curl -s -X PATCH http://localhost:8080/tasks/ID -H "Content-Type: application/json" \
  -d '{"status": "done", "result": "..."}'
```

**План:** Добавить в `agentforge-runner` подкоманды:
```bash
agentforge-runner task create --title "..." --tags "fix,rust"
agentforge-runner task claim --agent grok
agentforge-runner task complete --id XXXX --result "..."
agentforge-runner task list --status pending --json
```

### Ограничение 2: Dispatcher запускает bash-скрипты

**Проблема:** `POST /tasks/{id}/dispatch` запускает `dispatcher.sh` -> `*_runner.sh`.
Это bash-цепочка, которая может ломаться.

**Обходной путь:** Мониторьте логи в `/home/agx/agentforge/logs/`.

### Ограничение 3: Python API — единственный источник правды

**Проблема:** SQLite база данных управляется только через Python FastAPI.
Rust runner не имеет прямого доступа к БД задач.

**Обходной путь:** Все task-операции — через HTTP API.
Rust runner взаимодействует только с flywheel-данными на файловой системе.

### Ограничение 4: Rollback

Если Rust flywheel ломает что-то:
```bash
# Мгновенный откат — один из способов:
export DISABLE_RUST_FLYWHEEL=1
# или
touch /home/agx/agentforge/.disable_rust_flywheel
# или
export AGENTFORGE_PURE_RUST_FLYWHEEL=0
```

---

## 8. Переменные окружения

| Переменная | Значение | Описание |
|------------|----------|----------|
| `AGENTFORGE_RUST_RUNNER` | Путь к бинарнику | `/home/agx/agentforge/rust/target/release/agentforge-runner` |
| `AGENTFORGE_RUST_FLYWHEEL` | `1` / `0` | Включить/выключить Rust flywheel (default: 1) |
| `AGENTFORGE_USE_RUST` | `1` / `0` | Общий флаг использования Rust (default: 1) |
| `AGENTFORGE_RUST_FLYWHEEL_SHADOW` | `1` / `0` | Shadow-режим: двойная проверка Rust vs Python |
| `AGENTFORGE_PURE_RUST_FLYWHEEL` | `1` / `0` | Чистый Rust, без Python fallback |
| `AGENTFORGE_FLYWHEEL_ENGINE` | `rust` / `python` | Выбор движка flywheel |
| `DISABLE_RUST_FLYWHEEL` | `1` | Аварийное отключение (+ файл `.disable_rust_flywheel`) |

---

## Краткая шпаргалка

```bash
# === ЗАДАЧИ (Python API) ===
# Создать
curl -sX POST http://localhost:8080/tasks -H "Content-Type: application/json" \
  -d '{"title":"Фикс","description":"...","tags":["fix"],"priority":"high"}'

# Диспатч
curl -sX POST http://localhost:8080/tasks/TASK_ID/dispatch

# Pull (агент берёт сам)
curl -sX POST "http://localhost:8080/tasks/pull?agent=grok"

# Завершить
curl -sX PATCH http://localhost:8080/tasks/TASK_ID \
  -H "Content-Type: application/json" -d '{"status":"done","result":"Готово"}'

# === FLYWHEEL (Rust CLI) ===
R=$AGENTFORGE_RUST_RUNNER

# Шаг после задачи
$R flywheel-step --real-data --ingest --json

# Непрерывный цикл
$R continuous --top-n 3 --json

# Кандидаты
$R candidate list --top 5 --sort value --json
$R candidate promote ID --copy-to-skills

# Health
cat /tmp/agentforge_rust_flywheel/flywheel_health.json
```

---

> **Последнее обновление:** 2026-05-31  
> **Автор:** AgentForge Migration Architect  
> **Связанные документы:**  
> - `RUST_FULL_MIGRATION_PLAN.md` — полный план миграции  
> - `PHASE4_REMOVAL_PLAN.md` — план удаления Python  
> - `CONTINUOUS_FLYWHEEL.md` — непрерывный цикл  
> - `USAGE_RUST_IN_FARM.md` — использование Rust на ферме
