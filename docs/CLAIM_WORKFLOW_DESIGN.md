# 🔄 Claim Workflow Design — AgentForge

> Дизайн-документ: идеальный claim + work + complete flow с точки зрения автономного агента.
> Задача: dc6e4ab6 | Автор: Antigravity (субагент) | Дата: 2026-05-31

---

## 📋 Содержание

1. [Текущие проблемы](#текущие-проблемы)
2. [Предлагаемый flow](#предлагаемый-flow)
3. [Статусные переходы](#статусные-переходы)
4. [Новые поля в БД](#новые-поля-в-бд)
5. [API эндпоинты](#api-эндпоинты)
6. [CLI эргономика](#cli-эргономика)
7. [Edge cases и отказоустойчивость](#edge-cases)
8. [Миграция с текущего push-flow](#миграция)

---

## 1. Текущие проблемы

### 1.1 Push-модель (dispatch)

Сейчас задачи «проталкиваются» в агенты через `POST /tasks/{id}/dispatch`:

```
Пользователь → POST /tasks → pending → POST /dispatch → dispatched → grok_worker.sh
```

**Проблемы:**

| # | Проблема | Последствия |
|---|----------|-------------|
| 1 | **Нет claim lock** | Два воркера могут получить одну задачу через dispatch → дублирование работы |
| 2 | **Нет heartbeat** | Если агент упал, задача навсегда висит в `dispatched`/`in_progress` |
| 3 | **Нет pull-модели** | Агент не может сам выбрать задачу из очереди по своим возможностям |
| 4 | **Race conditions** | `grok_worker.sh` вызывает dispatch через HTTP, но между GET и POST статус может измениться |
| 5 | **Нет timeout recovery** | Зависшие задачи не возвращаются в пул автоматически |
| 6 | **Нет crash recovery** | При падении агента задача остаётся заблокированной без механизма освобождения |
| 7 | **Статус `dispatched` размыт** | Не ясно — задача уже взята агентом или только отправлена в shell |

### 1.2 Текущий workflow в коде

```
task_queue.py:
  TaskStatus: pending → dispatched → in_progress → review → done/failed

grok_worker.sh (poll loop):
  1. GET /tasks?status=pending → парсинг JSON → список задач
  2. POST /tasks/{id}/dispatch → статус = dispatched, запуск dispatcher.sh
  3. dispatcher.sh → grok_runner.sh → grok CLI → PATCH /tasks/{id} (done/failed)
```

**Нет атомарности**: между шагами 1 и 2 другой воркер может забрать ту же задачу.

---

## 2. Предлагаемый flow

### 2.1 Общая схема: Agent Pull → Claim → Heartbeat → Complete

```
┌──────────────┐     ┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│  Agent idle   │────▶│  PULL task   │────▶│ CLAIM (atom) │────▶│  WORK + HB  │
│  (ожидание)   │     │  (фильтр)   │     │  (lock)      │     │  (heartbeat)│
└──────────────┘     └─────────────┘     └──────────────┘     └──────┬──────┘
                                                                      │
                                                            ┌─────────┴─────────┐
                                                            ▼                   ▼
                                                    ┌──────────────┐   ┌──────────────┐
                                                    │  COMPLETE ✅  │   │   FAIL ❌     │
                                                    │  (результат)  │   │  (откат)     │
                                                    └──────────────┘   └──────────────┘
```

### 2.2 Детальный flow с точки зрения агента

```bash
# 1. PULL — агент запрашивает подходящую задачу
agentforge-runner task pull --agent grok --tags rust,fix --limit 1

# Ответ: список pending задач, подходящих по фильтрам
# { "tasks": [{"id": "abc123", "title": "Fix parser", "priority": "high", ...}] }

# 2. CLAIM — атомарный захват задачи (или 409 Conflict)
agentforge-runner task claim abc123 --agent grok --timeout 600

# Ответ: { "status": "claimed", "claimed_by": "grok-worker-1", "claimed_at": "..." }
# Или: { "error": "already_claimed", "claimed_by": "jules" }

# 3. HEARTBEAT — периодический пинг (каждые 30-60 сек)
agentforge-runner task heartbeat abc123 --progress "Анализ AST завершён, рефактор 40%"

# 4a. COMPLETE — успешное завершение
agentforge-runner task complete abc123 --result "Рефактор парсера: 3 файла, +tests"

# 4b. FAIL — ошибка
agentforge-runner task fail abc123 --reason "Cargo build failed: missing dependency"

# 4c. RELEASE — добровольный отказ от задачи
agentforge-runner task release abc123 --reason "Слишком сложно, нужен claude-opus"
```

### 2.3 Pull + Claim как единая операция

Для упрощения CLI предусмотрена комбинированная команда:

```bash
# Атомарный pull-and-claim: найти + захватить одним запросом
agentforge-runner task pull-claim --agent grok --tags rust --priority high --timeout 600

# Ответ: задача уже в статусе claimed
# { "task": {"id": "abc123", ...}, "claimed_by": "grok-worker-1" }
# Или: { "task": null } — нет подходящих задач
```

Это устраняет race condition между pull и claim.

---

## 3. Статусные переходы

### 3.1 Новая модель состояний

```
                    ┌──────────────┐
                    │   pending    │  ← Создана, ждёт агента
                    └──────┬───────┘
                           │ claim (атомарно)
                    ┌──────▼───────┐
                    │   claimed    │  ← Агент зарезервировал, готовит среду
                    └──────┬───────┘
                           │ start_work
                    ┌──────▼───────┐
               ┌───▶│ in_progress  │  ← Агент активно работает, шлёт heartbeat
               │    └──┬───┬───┬───┘
               │       │   │   │
               │ hb    │   │   │ release / timeout
               └───────┘   │   │
                           │   └──────────────┐
                    ┌──────▼───────┐   ┌──────▼───────┐
                    │    done ✅    │   │   pending    │
                    └──────────────┘   │  (re-queued) │
                    ┌──────────────┐   └──────────────┘
                    │   failed ❌   │
                    └──────────────┘
                    ┌──────────────┐
                    │   review 🔍  │  ← Guardian проверяет
                    └──────────────┘
```

### 3.2 Матрица разрешённых переходов

| Из / В          | pending | claimed | in_progress | done | failed | review |
|-----------------|---------|---------|-------------|------|--------|--------|
| **pending**     | —       | ✅ claim | ❌          | ❌   | ❌     | ❌     |
| **claimed**     | ✅ release/timeout | — | ✅ start | ❌ | ✅ fail | ❌    |
| **in_progress** | ✅ timeout/release | ❌ | — | ✅ complete | ✅ fail | ✅ review |
| **done**        | ✅ reopen | ❌     | ❌          | —    | ❌     | ❌     |
| **failed**      | ✅ retry | ✅ re-claim | ❌      | ❌   | —      | ❌     |
| **review**      | ❌      | ❌      | ❌          | ✅ approve | ✅ reject | — |

### 3.3 Обратная совместимость

- **dispatched** → маппится на **claimed** (deprecated, для grok_worker.sh)
- POST `/tasks/{id}/dispatch` → внутренне делает claim + start_work
- Старый flow продолжает работать без изменений

---

## 4. Новые поля в БД

### 4.1 Расширение таблицы tasks

```sql
ALTER TABLE tasks ADD COLUMN claimed_by TEXT;           -- ID агента (grok-worker-1, jules, antigravity-sub-3)
ALTER TABLE tasks ADD COLUMN claimed_at TEXT;            -- ISO8601 timestamp захвата
ALTER TABLE tasks ADD COLUMN heartbeat_at TEXT;          -- Последний heartbeat
ALTER TABLE tasks ADD COLUMN heartbeat_progress TEXT;    -- Текстовый прогресс (опционально)
ALTER TABLE tasks ADD COLUMN timeout_seconds INTEGER DEFAULT 600;  -- Таймаут (10 мин по умолчанию)
ALTER TABLE tasks ADD COLUMN claim_count INTEGER DEFAULT 0;        -- Сколько раз задача была захвачена (retry tracking)
ALTER TABLE tasks ADD COLUMN worker_id TEXT;             -- Уникальный ID воркер-инстанса (hostname-pid)
```

### 4.2 Таблица claim_history (аудит)

```sql
CREATE TABLE IF NOT EXISTS claim_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    agent TEXT NOT NULL,             -- grok, jules, antigravity
    worker_id TEXT,                  -- grok-worker-1-pid12345
    action TEXT NOT NULL,            -- claim, release, timeout, complete, fail
    reason TEXT,                     -- Причина release/fail
    timestamp TEXT NOT NULL,         -- ISO8601
    duration_seconds INTEGER,       -- Время владения задачей
    FOREIGN KEY (task_id) REFERENCES tasks(id)
);
```

---

## 5. API эндпоинты

### 5.1 Новые эндпоинты

#### GET /tasks/pull — получить подходящие задачи

```python
@app.get("/tasks/pull", tags=["Claim Workflow"])
async def pull_tasks(
    agent: str,                    # grok, jules, antigravity
    tags: Optional[str] = None,    # rust,fix — фильтр по тегам
    priority: Optional[str] = None, # critical, high — минимальный приоритет
    limit: int = 5,                # Макс. количество
    exclude_claimed: bool = True   # Исключить claimed задачи
):
    """
    Pull: агент запрашивает подходящие pending задачи.
    Сортировка: critical, high, medium, low — затем по дате создания.
    НЕ меняет статус — только чтение.
    """
```

#### POST /tasks/{task_id}/claim — атомарный захват

```python
@app.post("/tasks/{task_id}/claim", tags=["Claim Workflow"])
async def claim_task(
    task_id: str,
    agent: str,                    # grok
    worker_id: Optional[str] = None, # grok-worker-1-pid12345
    timeout_seconds: int = 600     # Таймаут в секундах (default 10 мин)
):
    """
    Claim: атомарный захват задачи.
    - Если pending — claimed (успех, 200)
    - Если уже claimed другим — 409 Conflict
    - Если claimed тем же агентом — 200 (идемпотентно)
    - Записывает claimed_by, claimed_at, timeout_seconds
    Реализация: BEGIN EXCLUSIVE + UPDATE ... WHERE status='pending' + COMMIT
    """
```

#### POST /tasks/pull-claim — комбинированный

```python
@app.post("/tasks/pull-claim", tags=["Claim Workflow"])
async def pull_and_claim(
    agent: str,
    worker_id: Optional[str] = None,
    tags: Optional[str] = None,
    priority: Optional[str] = None,
    timeout_seconds: int = 600
):
    """
    Атомарная операция: найти подходящую pending задачу + захватить.
    Одна транзакция, нет race condition.
    Ответ: задача или null (нет подходящих).
    """
```

#### POST /tasks/{task_id}/heartbeat — пинг жизни

```python
@app.post("/tasks/{task_id}/heartbeat", tags=["Claim Workflow"])
async def heartbeat(
    task_id: str,
    progress: Optional[str] = None  # "40% — рефактор AST"
):
    """
    Heartbeat: агент подтверждает что жив и работает.
    Обновляет heartbeat_at + heartbeat_progress.
    Возвращает 200 или 404 (задача не найдена).
    Если задача не in_progress/claimed — 409.
    """
```

#### POST /tasks/{task_id}/release — добровольный отказ

```python
@app.post("/tasks/{task_id}/release", tags=["Claim Workflow"])
async def release_task(
    task_id: str,
    reason: Optional[str] = None  # "Слишком сложно"
):
    """
    Release: агент добровольно отказывается от задачи.
    claimed/in_progress → pending (очищает claimed_by/claimed_at).
    Записывает в claim_history.
    """
```

#### POST /tasks/{task_id}/complete — успешное завершение

```python
@app.post("/tasks/{task_id}/complete", tags=["Claim Workflow"])
async def complete_task(
    task_id: str,
    result: str,                  # "Рефактор: 3 файла, +15 тестов"
    duration_seconds: Optional[int] = None
):
    """
    Complete: in_progress/claimed → done.
    Очищает claim lock, записывает результат.
    Тригерит Guardian auto-review если настроен.
    """
```

#### POST /tasks/{task_id}/fail — ошибка

```python
@app.post("/tasks/{task_id}/fail", tags=["Claim Workflow"])
async def fail_task(
    task_id: str,
    reason: str,                  # "Cargo build failed"
    retry: bool = False           # Автоматически вернуть в pending?
):
    """
    Fail: in_progress/claimed → failed (или pending если retry=true).
    """
```

### 5.2 Внутренняя реализация атомарного claim

```python
async def _atomic_claim(task_id: str, agent: str, worker_id: str, timeout: int) -> dict:
    """
    Атомарный claim через SQLite EXCLUSIVE транзакцию.
    Гарантирует что только один агент может захватить задачу.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        # BEGIN EXCLUSIVE — блокирует всю БД на время транзакции
        await db.execute("BEGIN EXCLUSIVE")
        try:
            cursor = await db.execute(
                "SELECT status, claimed_by FROM tasks WHERE id = ?", (task_id,)
            )
            task = await cursor.fetchone()
            if not task:
                await db.execute("ROLLBACK")
                return {"error": "not_found"}

            status, current_claimer = task

            # Идемпотентность: тот же агент уже захватил
            if status == "claimed" and current_claimer == agent:
                await db.execute("ROLLBACK")
                return {"status": "claimed", "claimed_by": agent, "idempotent": True}

            # Уже занята другим
            if status not in ("pending", "failed"):
                await db.execute("ROLLBACK")
                return {
                    "error": "already_claimed",
                    "claimed_by": current_claimer,
                    "status": status
                }

            now = datetime.utcnow().isoformat()
            await db.execute("""
                UPDATE tasks SET
                    status = 'claimed',
                    claimed_by = ?,
                    worker_id = ?,
                    claimed_at = ?,
                    heartbeat_at = ?,
                    timeout_seconds = ?,
                    claim_count = COALESCE(claim_count, 0) + 1,
                    updated_at = ?
                WHERE id = ?
            """, (agent, worker_id, now, now, timeout, now, task_id))

            # Аудит
            await db.execute("""
                INSERT INTO claim_history (task_id, agent, worker_id, action, timestamp)
                VALUES (?, ?, ?, 'claim', ?)
            """, (task_id, agent, worker_id, now))

            await db.commit()
            return {"status": "claimed", "claimed_by": agent, "claimed_at": now}
        except Exception:
            await db.execute("ROLLBACK")
            raise
```

---

## 6. CLI эргономика

### 6.1 Новые subcommands для agentforge-runner

```
agentforge-runner task <command> [options]

COMMANDS:
    pull              Получить список подходящих pending задач
    claim <id>        Атомарно захватить задачу
    pull-claim        Pull + claim одним запросом (рекомендуется)
    heartbeat <id>    Отправить heartbeat (жив, работаю)
    start <id>        Перевести claimed → in_progress
    complete <id>     Завершить задачу с результатом
    fail <id>         Пометить задачу как failed
    release <id>      Добровольно отказаться от задачи
    status <id>       Показать статус задачи

OPTIONS (общие):
    --agent <name>     Имя агента (grok, jules, antigravity)
    --worker-id <id>   Уникальный ID воркера (default: hostname-pid)
    --json             JSON-вывод (для автоматизации)
    --api <url>        URL API (default: http://localhost:8080)

ПРИМЕРЫ:
    # Простой poll-claim цикл (заменяет grok_worker.sh)
    agentforge-runner task pull-claim --agent grok --tags rust --json

    # Heartbeat в фоне (каждые 30 сек)
    while true; do
        agentforge-runner task heartbeat $TASK_ID --progress "$PROGRESS"
        sleep 30
    done &

    # Завершение
    agentforge-runner task complete $TASK_ID --result "Done: 3 files changed" --json
```

### 6.2 Worker loop (замена grok_worker.sh)

```bash
#!/bin/bash
# grok_worker_v2.sh — pull-based worker с claim и heartbeat
AGENT="grok"
RUNNER="/home/agx/agentforge/rust/target/release/agentforge-runner"
POLL_INTERVAL=15
MAX_PARALLEL=3

while true; do
    # Считаем текущие задачи в работе
    RUNNING=$(pgrep -f "agentforge-$AGENT" | wc -l)
    if [ "$RUNNING" -ge "$MAX_PARALLEL" ]; then
        sleep "$POLL_INTERVAL"
        continue
    fi

    # Атомарный pull-claim
    TASK_JSON=$($RUNNER task pull-claim --agent "$AGENT" --timeout 900 --json 2>/dev/null)
    TASK_ID=$(echo "$TASK_JSON" | jq -r '.task.id // empty')

    if [ -z "$TASK_ID" ]; then
        sleep "$POLL_INTERVAL"
        continue
    fi

    # Запускаем работу в фоне
    (
        # Heartbeat фоновый процесс
        ( while kill -0 $$ 2>/dev/null; do
            $RUNNER task heartbeat "$TASK_ID" --progress "working" --json >/dev/null 2>&1
            sleep 30
        done ) &
        HB_PID=$!

        # Переход в in_progress
        $RUNNER task start "$TASK_ID" --json >/dev/null

        # Выполняем задачу (подставить реальную логику)
        RESULT=$(run_grok_task "$TASK_ID")
        EXIT_CODE=$?

        # Убиваем heartbeat
        kill $HB_PID 2>/dev/null

        # Репортим результат
        if [ $EXIT_CODE -eq 0 ]; then
            $RUNNER task complete "$TASK_ID" --result "$RESULT" --json
        else
            $RUNNER task fail "$TASK_ID" --reason "$RESULT" --json
        fi
    ) &

    sleep 2
done
```

---

## 7. Edge cases и отказоустойчивость

### 7.1 Timeout → Auto-release

```python
# Фоновый watchdog (каждые 60 секунд)
async def claim_watchdog():
    """
    Освобождает задачи, у которых истёк timeout без heartbeat.
    Запускается как background task при старте FastAPI.
    """
    while True:
        await asyncio.sleep(60)
        now = datetime.utcnow()

        async with aiosqlite.connect(DB_PATH) as db:
            # Находим задачи с протухшим heartbeat
            cursor = await db.execute("""
                SELECT id, claimed_by, heartbeat_at, timeout_seconds, claimed_at
                FROM tasks
                WHERE status IN ('claimed', 'in_progress')
                  AND heartbeat_at IS NOT NULL
                  AND timeout_seconds IS NOT NULL
            """)
            for row in await cursor.fetchall():
                task_id, agent, hb_at, timeout, claimed_at = row
                last_hb = datetime.fromisoformat(hb_at)
                if (now - last_hb).total_seconds() > timeout:
                    # Auto-release
                    await db.execute("""
                        UPDATE tasks SET
                            status = 'pending',
                            claimed_by = NULL,
                            claimed_at = NULL,
                            heartbeat_at = NULL,
                            worker_id = NULL,
                            updated_at = ?
                        WHERE id = ?
                    """, (now.isoformat(), task_id))
                    await db.execute("""
                        INSERT INTO claim_history
                        (task_id, agent, action, reason, timestamp)
                        VALUES (?, ?, 'timeout', 'heartbeat expired', ?)
                    """, (task_id, agent, now.isoformat()))
                    log.warning(
                        f"Timeout: задача {task_id} освобождена (агент {agent})"
                    )
            await db.commit()
```

### 7.2 Crash recovery

| Сценарий | Решение |
|----------|---------|
| **Агент упал без heartbeat** | Watchdog обнаруживает timeout → auto-release в pending |
| **Сеть потеряна** | Heartbeat перестаёт приходить → timeout → release |
| **task_queue.py перезапущен** | Watchdog стартует при startup → сканирует и освобождает зависшие |
| **Двойной claim (race)** | SQLite EXCLUSIVE транзакция → только один выиграет, второй получит 409 |
| **Агент завершил, но PATCH не дошёл** | Задача остаётся claimed → timeout → release → повторный claim |

### 7.3 Повторные попытки (retry)

```python
# Конфигурируемые лимиты
MAX_CLAIM_COUNT = 3  # Максимум 3 попытки для одной задачи
RETRY_BACKOFF = [60, 300, 900]  # 1 мин, 5 мин, 15 мин

# При release/timeout:
# if task.claim_count >= MAX_CLAIM_COUNT:
#     Эскалация: переводим в failed с причиной
#     task.status = "failed"
#     task.result = f"Exhausted {MAX_CLAIM_COUNT} claim attempts"
#     Уведомление в webhook
# else:
#     task.status = "pending"
#     Задержка перед повторным claim
#     task.retry_after = now + timedelta(seconds=RETRY_BACKOFF[task.claim_count])
```

### 7.4 Приоритетная очередь при pull

```sql
-- Порядок выдачи задач при pull:
SELECT * FROM tasks
WHERE status = 'pending'
  AND (retry_after IS NULL OR retry_after <= datetime('now'))
  AND (tags IS NULL OR tags LIKE '%' || :tag || '%')
ORDER BY
    CASE priority
        WHEN 'critical' THEN 0
        WHEN 'high' THEN 1
        WHEN 'medium' THEN 2
        WHEN 'low' THEN 3
    END,
    created_at ASC
LIMIT :limit
```

---

## 8. Миграция с текущего push-flow

### 8.1 Фазы миграции

```
Фаза 0 (сейчас):     push-only (dispatch)
Фаза 1 (следующая):  API + watchdog + CLI subcommands (pull, claim, heartbeat)
Фаза 2:              grok_worker_v2.sh (pull-based, параллельно со старым)
Фаза 3:              Все воркеры на pull-claim, dispatch = legacy wrapper
Фаза 4:              Удаление dispatch, полный pull-claim
```

### 8.2 Фаза 1 — минимальный набор изменений

**task_queue.py:**
1. Добавить поля в SQLite (claimed_by, claimed_at, heartbeat_at, timeout_seconds, claim_count)
2. Создать таблицу claim_history
3. Добавить эндпоинты: GET /tasks/pull, POST /tasks/{id}/claim, POST /tasks/{id}/heartbeat, POST /tasks/{id}/release, POST /tasks/{id}/complete
4. Добавить claim_watchdog как background task
5. POST /tasks/{id}/dispatch → внутренне вызывает _atomic_claim (обратная совместимость)

**agentforge-runner (Rust):**
1. Добавить subcommand `task` с подкомандами: pull, claim, pull-claim, heartbeat, start, complete, fail, release, status
2. Общение через HTTP API (не SQLite напрямую)
3. --json вывод для автоматизации

**grok_worker.sh:**
1. Оставить без изменений (фаза 1 = добавление нового, не ломая старого)

### 8.3 Обратная совместимость

```python
# POST /tasks/{id}/dispatch → обёртка над claim
@app.post("/tasks/{task_id}/dispatch", tags=["Диспетчеризация (Legacy)"])
async def dispatch_task(task_id: str):
    """Legacy endpoint — внутренне делает claim + start_work."""
    # 1. Атомарный claim
    result = await _atomic_claim(
        task_id, agent="grok", worker_id="dispatch-legacy", timeout=900
    )
    if result.get("error"):
        raise HTTPException(status_code=409, detail=result["error"])

    # 2. Переход в in_progress (как раньше dispatched)
    await _update_status(task_id, "in_progress")

    # 3. Запуск dispatcher.sh (существующая логика)
    subprocess.Popen([DISPATCHER_PATH, task_id])

    return {"status": "dispatched", "task_id": task_id}
```

---

## 📊 Сводка: до и после

| Аспект | Сейчас (push) | Предлагается (pull-claim) |
|--------|---------------|---------------------------|
| **Инициатор** | Внешний dispatch | Агент сам тянет задачу |
| **Атомарность** | Нет (GET → POST race) | SQLite EXCLUSIVE транзакция |
| **Мониторинг** | Нет | Heartbeat каждые 30 сек |
| **Timeout** | Нет | Watchdog + auto-release |
| **Crash recovery** | Ручной | Автоматический через timeout |
| **Race conditions** | Возможны | Невозможны (atomic claim) |
| **Аудит** | Нет | claim_history таблица |
| **CLI** | curl + jq хаки | agentforge-runner task ... |
| **Retry** | Ручной re-dispatch | Автоматический с backoff |
| **Статусы** | pending→dispatched→... | pending→claimed→in_progress→... |

---

## 🔧 Конфигурация (config.toml)

```toml
[claim]
# Таймаут по умолчанию (секунды) — после этого задача освобождается
default_timeout_seconds = 600

# Интервал heartbeat (рекомендуемый для агентов)
heartbeat_interval_seconds = 30

# Интервал проверки watchdog
watchdog_interval_seconds = 60

# Максимум повторных попыток
max_claim_count = 3

# Задержка перед повторным claim (секунды)
retry_backoff = [60, 300, 900]

[claim.agents]
# Кастомные таймауты по агентам
grok_timeout = 900        # 15 мин (grok быстрый)
jules_timeout = 3600      # 1 час (jules = GitHub PRs)
antigravity_timeout = 1800 # 30 мин
```

---

> **Следующий шаг**: реализация Фазы 1 — добавление pull/claim/heartbeat эндпоинтов в task_queue.py + task subcommand в Rust CLI.
