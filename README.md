# 🔨 AgentForge

**Autonomous Agent Orchestration Platform** — система оркестрации автономных агентов с crash recovery, иерархической декомпозицией задач и shared memory.

## Архитектура

```
agentforge/
├── core/                        # Ядро платформы
│   ├── task_checkpoints.py      # Checkpoint-система + RAG/FTS5 + Shared Memory + Blackboard
│   ├── task_queue.py            # Оркестрация команд, иерархическая декомпозиция, DAG
│   ├── grok_worker.py           # Автономный worker с Git Auto-Rollback
│   ├── agentforge_watchdog.py   # Мониторинг агентов, обнаружение циклов
│   └── agentforge_create_task.py # CLI для создания задач агентами
├── scripts/                     # Shell-скрипты для интеграции
│   ├── grok_worker.sh           # Bash worker (CI guard + auto-rollback)
│   ├── github_watcher.sh        # Мониторинг GitHub событий
│   ├── guardian.sh              # Guardian daemon
│   └── healthcheck.sh           # Health checks
├── services/                    # Systemd unit-файлы
├── config/                      # Центральная конфигурация
│   └── settings.py              # Все пути и параметры
├── data/                        # SQLite БД (не коммитится)
│   ├── task_checkpoints.db      # Чекпоинты + FTS5
│   └── tasks.db                 # Shared Memory / Knowledge
├── monitoring/                  # Grafana/Loki/Promtail конфиги
├── logs/                        # Логи (не коммитится)
└── docs/                        # Документация
```

## Ключевые возможности

- **Crash Recovery** — checkpoint после каждого шага пайплайна, автоматическое восстановление
- **Git Auto-Rollback** — при CI failure автоматический `git revert` для защиты main
- **Иерархическая декомпозиция** — Manager-агент рекурсивно разбивает задачи на подзадачи
- **Shared Memory** — FTS5-powered база знаний агентов с RAG-контекстом
- **Live Blackboard** — оперативная доска для координации активных агентов в реальном времени
- **DAG Dependencies** — задачи могут зависеть друг от друга, автоматический промоушн при готовности

## Быстрый старт

```bash
# Self-test чекпоинтов
python3 core/task_checkpoints.py

# Self-test оркестрации
python3 core/task_queue.py

# Self-test grok worker
DRY_RUN=1 bash scripts/grok_worker.sh self-test

# Создать задачу через CLI
python3 core/agentforge_create_task.py --title "Test task" --dry-run
```

## Пайплайн задачи

```
dispatch → git_clone → grok_start → grok_done → ci_start → ci_done → review → done
                                                     ↓ (failure)
                                                 ci_failed → rollback → failed
```
