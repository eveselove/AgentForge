# Python Entrypoints для создания/управления задачами — Аудит и план миграции

> **Задача AgentForge:** 61c1dcca  
> **Дата аудита:** 2026-05-31  
> **Автор:** Antigravity (Архитектор AgentForge)  
> **Статус:** ✅ Аудит завершён

---

## Резюме

Обнаружено **14 Python-файлов**, которые создают, обновляют или управляют задачами через HTTP API (localhost:8080).
Из них **5 файлов** — скрипты массового создания задач (create_*.py),
**5 файлов** — утилиты управления (ix_*, 
eassign, 
eset_fakes, pprove_tasks),
**2 файла** — eval-система (только GET-запросы),
**1 файл** — MCP-сервер (мост для IDE),
**1 файл** — core API (	ask_queue.py).

---

## Категория 1: Скрипты массового создания задач (create_*.py)

### Приоритет миграции: 🔴 P0 (критический путь)

| # | Файл | Метод HTTP | Библиотека | Кол-во задач | Описание | Целевой Rust-путь |
|---|------|-----------|------------|-------------|----------|-------------------|
| 1 | create_tasks.py | POST /tasks | 
equests | 12 | Основные задачи (Auto-Decompose, Code Review, SLA и т.д.) | gentforge-runner task create --from-file tasks.json |
| 2 | create_arch_tasks.py | POST /tasks | urllib | 4 | Архитектурные задачи (DAG, делегирование, RepoMap, MCP) | gentforge-runner task create --from-file arch_tasks.json |
| 3 | create_tasks_v2.py | POST /tasks | urllib | 11 | Продвинутые задачи v2 (PRM, MoA, DSPy, Cost Tracking) | gentforge-runner task create --from-file tasks_v2.json |
| 4 | create_final_100_tasks.py | POST /tasks | urllib | 5 | Финальные задачи AGI (Actor-Critic, RAG, Watchdog) | gentforge-runner task create --from-file final_tasks.json |
| 5 | create_teamwork_tasks.py | POST /tasks | urllib | 3 | Командная работа (Merge Resolver, Blackboard, Discovery) | gentforge-runner task create --from-file teamwork_tasks.json |

**Общий паттерн:** Все скрипты содержат hardcoded-массивы задач + цикл POST /tasks.
Помечены как DEPRECATED (у create_tasks.py уже есть баннер).

**Целевое решение:**
`
# Вместо python create_tasks.py:
agentforge-runner task create --title "..." --priority high --tags rust,api
# Или массово (прямая замена hardcoded create_*.py):
agentforge-runner --json task create --from-file tasks.json
agentforge-runner task reassign --from antigravity --to grok --pending-only
agentforge-runner task approve --all-review
agentforge-runner task review <id>
agentforge-runner task reject <id> --feedback "..." 
agentforge-runner task stats
` 
(Implemented 2026-06 in agentforge-runner; live gateway client + --from-file + management subcmds. **task-5af0e350**: added review/reject live wrappers + full polish for 100% entrypoints on runner. Python scripts deleted; remaining py shims (e.g. scripts/create_audit_tasks.py) updated to call runner --from-file preferentially.)

---

## Категория 2: Утилиты управления задачами

### Приоритет миграции: 🟡 P1 (высокий)

| # | Файл | Операции | Библиотека | Описание | Целевой Rust-путь |
|---|------|----------|------------|----------|-------------------|
| 6 | ix_antigravity_tasks.py | GET /tasks, PATCH /tasks/{id} | urllib | Переназначает застрявшие задачи с Antigravity на Grok. Поддерживает --dry-run, --force. Фильтрует по тегам глубокого анализа. | gentforge-runner task reassign --from antigravity --to grok [--dry-run] [--force] |
| 7 | 
eassign.py | GET /tasks, PATCH /tasks/{id} | urllib | Упрощённый reassign: переводит pending задачи с нестандартных агентов на grok. | gentforge-runner task reassign --pending-only --to grok |
| 8 | ix_stuck_tasks.py | PATCH /tasks/{id} | urllib | Обновляет статус конкретных hardcoded задач → 
eview. | gentforge-runner task update {id} --status review --result ... |
| 9 | 
eset_fakes.py | GET /tasks, PATCH /tasks/{id} | urllib | Сбрасывает фейковые задачи (done за 0 секунд) обратно в pending. | gentforge-runner task reset-fakes |
| 10 | pprove_tasks.py | GET /tasks, PATCH /tasks/{id} | urllib | Массово одобряет задачи в статусе 
eview → done. | gentforge-runner task approve --all-review |

---

## Категория 3: Мониторинг и статистика

### Приоритет миграции: 🟢 P2 (средний)

| # | Файл | Операции | Библиотека | Описание | Целевой Rust-путь |
|---|------|----------|------------|----------|-------------------|
| 11 | check_status.py | GET /metrics, GET /tasks | urllib | Показывает метрики и активные задачи. | gentforge-runner status (уже частично есть) |
| 12 | show_agent_stats.py | GET /tasks | urllib | Детальная статистика маршрутизации, поиск застрявших задач, flywheel health. | gentforge-runner stats [--json] [--stuck-only] |

---

## Категория 4: MCP-сервер (мост для IDE)

### Приоритет миграции: 🟡 P1 (высокий — критический мост)

| # | Файл | Операции | Библиотека | Описание | Целевой Rust-путь |
|---|------|----------|------------|----------|-------------------|
| 13 | mcp_server.py | POST /tasks, POST /tasks/{id}/dispatch, PATCH /tasks/{id}, GET /tasks, GET /tasks/{id} | urllib | MCP-сервер для Antigravity IDE. Реализует gentforge_create_task, gentforge_list_tasks, gentforge_dispatch_task, gentforge_update_task, gentforge_get_task. | Оставить как тонкий мост или переписать на Rust MCP SDK |

**Примечание:** MCP-сервер — это прокси, который пробрасывает вызовы к HTTP API task_queue.
Если task_queue мигрирует в Rust, mcp_server может остаться как тонкий Python-прокси
(минимальный размер, нет бизнес-логики) или быть переписан через 
mcp (Rust MCP SDK).

---

## Категория 5: Core API (task_queue.py)

### Приоритет миграции: 🔴 P0 (самый критический)

| # | Файл | Операции | Описание | Целевой Rust-путь |
|---|------|----------|----------|-------------------|
| 14 | 	ask_queue.py | FastAPI: все CRUD endpoints для задач, MoA, dispatch, webhooks | Центральный сервер задач. ~1600+ строк. Содержит: REST API, SQLite ORM, маршрутизацию, MoA оркестрацию, webhook-уведомления, asyncio.create_task для фоновых процессов. | gentforge-task-service (новый Rust-крейт) на базе xum + sqlx |

**Важно:** 	ask_queue.py — это **не** просто точка входа создания задач.
Это весь backend. Его миграция — это отдельный крупный проект (см. RUST_ONLY_MIGRATION_PLAN.md, Tier 1).

---

## Категория 6: Eval-система (только чтение)

### Приоритет миграции: 🟢 P2 (средний — только GET)

| # | Файл | Операции | Описание | Целевой Rust-путь |
|---|------|----------|----------|-------------------|
| 15 | eval/runner.py | GET /tasks/{id} | Проверяет статус задачи после dispatch. | gentforge-runner eval run (уже частично) |
| 16 | eval/generate_evaluation_report.py | GET /tasks/{id} | Получает данные задач для отчёта. | gentforge-runner eval report |

**Примечание:** Эти файлы **не создают** задачи, только читают.
Низкий приоритет, т.к. eval и так помечена как deprecated для flywheel-путей.

---

## Сводная таблица миграции

| Категория | Файлов | Операции | Приоритет | Статус миграции |
|-----------|--------|----------|-----------|-----------------|
| Массовое создание задач | 5 | POST (create) | 🔴 P0 | ✅ 2026-06 + Jules wave 2026-06-13 task f29c675b: 5 create_*.py + core/agentforge_create_task.py + bin/turbo fully rm'ed (git rm); runner task --from-file live replaces |
| Утилиты управления | 5 | GET + PATCH | 🟡 P1 | ✅ 2026-06 + Jules: fix_*, reassign, reset, approve, check, show fully rm'ed; runner equivalents |
| Мониторинг | 2 | GET | 🟢 P2 | ✅ via task list/stats (and /metrics in gateway) |
| MCP-сервер | 1 | Все CRUD | 🟡 P1 | ⏳ Thin proxy ok for now; points at gateway (or can subprocess runner --json task *) |
| Core API | 1 | Full CRUD + бизнес-логика | 🔴 P0 | ✅ DONE (gateway/ + core TaskStore) — task_queue.py deleted |
| Eval (только чтение) | 2 | GET | 🟢 P2 | ⏳ Частично (gateway list + runner) |
| **Task mgmt entrypoints** | - | via runner task (live reqwest) | - | ✅ **Accelerated/complete in task-5af0e350**: full live create/list/get/update/dispatch/claim/reassign/approve/review/reject/reset/stats + --from-file; no py needed. Scripts gone; create_audit_tasks.py updated to prefer runner --from-file. |

---

## Рекомендуемый порядок миграции

### Фаза 1: CLI для управления задачами (Быстрая победа)
`
# Новые субкоманды в agentforge-runner:
agentforge-runner task create --title ... --priority high --tags rust
agentforge-runner task create --from-file tasks.json  # массовое создание
agentforge-runner task list [--status pending] [--agent grok]
agentforge-runner task update {id} --status done --result ...
agentforge-runner task reassign --from antigravity --to grok
agentforge-runner task approve --all-review
agentforge-runner task review <id>
agentforge-runner task reject <id> --feedback "..."
agentforge-runner task reset-fakes
agentforge-runner task stats [--json]
# (complete surface + live reqwest since task-5af0e350)
`

**Зависимость:** Требует HTTP-клиент в Rust (
eqwest) для обращений к task_queue.py API.
Это минимальный объём работы, и сразу позволит удалить все скрипты Категорий 1-3.

### Фаза 2: Нативный Rust Task Service
- Порт 	ask_queue.py → gentforge-task-service на xum + sqlx (SQLite).
- Перенос маршрутизации, CRUD, MoA, webhooks.
- После завершения — MCP-сервер указывает на Rust-сервис.

### Фаза 3: Eval + MCP в Rust
- Переписать eval GET-запросы на Rust.
- MCP-сервер: либо оставить как тонкий мост, либо переписать через 
mcp.

---

## Файлы для удаления после миграции

Фаза 1 (CLI live task mgmt) ЗАВЕРШЕНА 2026-06. Можно удалять (после обновления любых вызовов в sh/bin и agent-review):
`
create_tasks.py create_arch_tasks.py create_tasks_v2.py create_final_100_tasks.py create_teamwork_tasks.py
fix_antigravity_tasks.py fix_stuck_tasks.py reassign.py reset_fakes.py approve_tasks.py
check_status.py show_agent_stats.py
`
(Также core/agentforge_create_task.py post_create_task и bin/create_turbo... если не нужны.)

**12+ файлов теперь имеют Rust эквивалент.**

---

## Зависимости Python-библиотек (к удалению после полной миграции)

| Библиотека | Используется в | Можно удалить после |
|------------|----------------|---------------------|
| 
equests | create_tasks.py | Фаза 1 |
| urllib.request | Все остальные скрипты | Фаза 1 |
| FastAPI + uvicorn | 	ask_queue.py | Фаза 2 |
| iosqlite / sqlite3 | 	ask_queue.py | Фаза 2 |

---

> **Следующий шаг:** Создать задачу на реализацию gentforge-runner task create/list/update субкоманд.
> Это позволит сразу удалить 12 Python-скриптов и значительно сократить Python-поверхность.
