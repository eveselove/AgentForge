# Чеклист миграции Task System на Rust

> Последнее обновление: 2026-05-31 17:59 MSK
> Статус: **В процессе (Phase 1 — Axum HTTP API)**
> Задача AgentForge: #a0a03ba4

---

## Обзор

Миграция Task System из Python (FastAPI + aiosqlite, `task_queue.py`) в чистый Rust.

| Параметр | Текущее (Python) | Целевое (Rust) |
|----------|-----------------|----------------|
| Сервер | FastAPI `task_queue.py` | Axum HTTP в `agentforge-runner` или `agentforge-api` |
| Хранилище | `tasks.db` (SQLite) | `JsonFileTaskStore` → SQLite (`rusqlite`) |
| Биндинг | `0.0.0.0:8080` | `0.0.0.0:8080` (идентично) |
| API | REST JSON | REST JSON (идентичный формат) |
| Воркеры | bash + curl | bash + curl (без изменений) |
| Дашборд | `dashboard.html` | Тот же фронтенд, CORS |

---

## Phase 0: Rust-типы и хранилище — ✅ DONE

- [x] `Task` struct с serde (`agentforge-core/src/task.rs`)
- [x] `TaskStatus` enum: `Pending`, `InProgress`, `Done`, `Failed`, `Cancelled`
- [x] `TaskStore` trait: `create`, `get`, `list_pending`, `list_all`, `update_status`, `update`, `delete`, `count`, `claim`
- [x] `InMemoryTaskStore` — реализация для тестов
- [x] `JsonFileTaskStore` — персистентное хранилище (`.tmp` → `rename`)
- [x] Атомарная запись через rename
- [x] Юнит-тесты зелёные (`cargo test`)
- [x] Builder-паттерн: `Task::new().with_priority().with_preferred_agent().with_tags()`
- [x] Импорт в `agentforge-runner` main.rs

### Известные проблемы Phase 0

| Проблема | Статус | Описание |
|----------|--------|----------|
| `InMemoryTaskStore::claim` вызывает `persist()` | ⚠️ Баг | У InMemory нет persist(), нужно убрать вызов |
| `JsonFileTaskStore::claim` НЕ вызывает `persist()` | ⚠️ Баг | Данные теряются после claim, нужно добавить `self.persist()` |
| Нет `completed_at` в Task struct | ⚠️ Нехватка | Python API отдаёт `completed_at`, в Rust пока нет |
| Нет `duration_seconds` | ⚠️ Нехватка | Python API считает длительность |
| Нет `retry_count`, `tokens_used`, `cost_usd` | ℹ️ Низкий | Метрики из Python, можно добавить позже |

---

## Phase 1: HTTP API (Axum) — 🔄 IN PROGRESS

### Эндпоинты (1:1 с Python)

| Метод | Путь | Python | Rust |
|-------|------|:---:|:---:|
| `POST` | `/tasks` | ✅ | ⬜ |
| `GET` | `/tasks` | ✅ | ⬜ |
| `GET` | `/tasks/{id}` | ✅ | ⬜ |
| `PATCH` | `/tasks/{id}` | ✅ | ⬜ |
| `DELETE` | `/tasks/{id}` | ✅ | ⬜ |
| `POST` | `/tasks/{id}/dispatch` | ✅ | ⬜ |
| `POST` | `/tasks/{id}/claim` | ✅ | ⬜ |
| `POST` | `/review/all` | ✅ Guardian | ⬜ |
| `GET` | `/metrics` | ✅ | ⬜ |
| `GET` | `/health` | ✅ | ⬜ |
| `GET` | `/` | ✅ Dashboard | ⬜ |
| `WS` | `/ws` | ✅ WebSocket | ⬜ |

### Задачи Phase 1

- [ ] Добавить `axum = "0.7"` + `tower-http` (cors) в workspace
- [ ] Создать crate `agentforge-api` или встроить `serve` subcommand в runner
- [ ] Реализовать CRUD эндпоинты
- [ ] JSON-ответы идентичны Python (serde_json, тот же формат)
- [ ] CORS для дашборда
- [ ] Биндинг `0.0.0.0:8080`
- [ ] Валидация входных данных
- [ ] Тесты интеграции (curl-совместимость)

### Критерий перехода Phase 1 → Phase 2

Все curl-команды должны возвращать идентичные JSON-ответы от Python и Rust API.

---

## Phase 2: Интеграция с воркерами — ⏳ TODO

- [ ] `grok_worker.sh` — проверить совместимость (curl идентичный)
- [ ] `jules_worker.sh` — аналогично
- [ ] `grok_xai_worker.sh` — аналогично
- [ ] `dispatcher.sh` — проверить маршрутизацию
- [ ] Guardian (`/review/all`) — реализовать логику ревью
- [ ] MCP-обёртки (`mcp_server.py`) — перенаправить на Rust API
- [ ] Дашборд (`dashboard.html`) — проверить CORS + формат ответов
- [ ] `healthcheck.sh` — проверить `/health` эндпоинт

---

## Phase 3: Расширенные фичи — ⏳ TODO

- [ ] Фильтрация: `?status=pending&tag=rust&priority=high&agent=grok`
- [ ] Пагинация: `?limit=50&offset=0`
- [ ] Сортировка: `?sort=priority&order=desc`
- [ ] WebSocket для real-time обновлений дашборда
- [ ] Prometheus-метрики (`GET /metrics`)
- [ ] Rate limiting
- [ ] Health check с диагностикой

---

## Phase 4: Удаление Python — ⏳ TODO (после 14-дневного soak)

- [ ] Убить `task_queue.py` (88K строк)
- [ ] Удалить Python-зависимости (FastAPI, aiosqlite, pydantic, uvicorn)
- [ ] Обновить systemd-юниты
- [ ] Обновить MCP-конфигурацию (mcp_server.py → Rust)
- [ ] Обновить всю документацию
- [ ] Финальное E2E тестирование на ферме
- [ ] Удалить `*.py.bak` и legacy-скрипты

---

## Rust Crates — текущая структура

| Crate | Назначение | Статус |
|-------|-----------|--------|
| `agentforge-core` | Task, Agent, Config, Outcome типы | ✅ Стабильный |
| `agentforge-runner` | CLI: flywheel, candidates, обучение | ✅ Продакшн (1.41 MB) |
| `agentforge-learning` | Dataset, Trainer, Improver | ✅ Рабочий |
| `agentforge-candidates` | CandidateStore, Prioritizer, Promote | ✅ Продакшн |
| `agentforge-flywheel` | FlywheelOrchestrator | ✅ Рабочий |
| `agentforge-safety` | PolicyEngine | 🔄 Скелет |
| `agentforge-planning` | Planner | 🔄 Скелет |
| `agentforge-observability` | Трейсинг, метрики | 🔄 Скелет |
| `agentforge-long-horizon` | TaskManager для длинных задач | 🔄 Скелет |

---

## Зависимости

### Текущие (workspace Cargo.toml)

- tokio 1 (full) — асинхронный рантайм
- serde 1.0 + serde_json 1.0 — сериализация
- chrono 0.4 — timestamps
- uuid 1.0 (v4) — генерация ID
- anyhow 1.0 + thiserror 1.0 — ошибки
- tracing 0.1 — логирование

### Нужно добавить для HTTP API

- axum 0.7 — HTTP фреймворк
- tower-http 0.5 (cors, trace) — middleware
- Опционально: rusqlite 0.31 (bundled) — SQLite вместо JSON

---

## Риски и митигация

| Риск | Вероятность | Митигация |
|------|:-----------:|----------|
| Несовместимость JSON-схемы | Средняя | Тесты паритета Python ↔ Rust ответов |
| Потеря данных | Низкая | Миграция: `tasks.db` → `data/tasks.json` |
| Воркеры ломаются | Низкая | API идентичный, curl не меняется |
| Дашборд перестаёт работать | Средняя | CORS + формат ответов |
| Конкурентный доступ | Средняя | `tokio::sync::RwLock` для TaskStore |
| SQLite → JSON регрессия | Средняя | rusqlite как альтернативный backend |

---

## Быстрый старт (текущий workaround)

Пока Rust HTTP API не готов, задачи создаются через Python API:

    # Создание задачи
    curl -X POST http://localhost:8080/tasks \
      -H "Content-Type: application/json" \
      -d '{"title":"Моя задача","description":"Описание","priority":"high","tags":["rust"]}'

    # Обновление статуса
    curl -X PATCH http://localhost:8080/tasks/<ID> \
      -H "Content-Type: application/json" \
      -d '{"status":"done","result":"Готово"}'

---

## Следующие шаги

1. **Исправить баги** в `task.rs` (persist в claim, недостающие поля)
2. **Добавить `axum`** в workspace Cargo.toml
3. **Реализовать HTTP сервер** — subcommand `agentforge-runner serve`
4. **Тесты паритета** — скрипт сравнения Python и Rust ответов
5. **Shadow режим** — запуск Rust API параллельно Python для валидации

---

> Обновлено Antigravity агентом, задача AgentForge #a0a03ba4
