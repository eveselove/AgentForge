# Гайд: Создание задач через AgentForge

> Последнее обновление: 2026-05-31 17:59 MSK
> Версия: agentforge-runner v0.1.0 (1.41 MB)
> Задача AgentForge: #06c5b97b

---

## Быстрый старт

AgentForge поддерживает 4 способа создания и управления задачами.
Текущий основной способ — **curl к Python API** (http://localhost:8080).

---

## 1. Через curl (основной способ)

### Создание задачи

    curl -X POST http://localhost:8080/tasks \
      -H "Content-Type: application/json" \
      -d '{
        "title": "Рефакторинг модуля обучения",
        "description": "Переписать trainer.py на Rust с сохранением API",
        "priority": "high",
        "tags": ["rust", "refactor", "learning"],
        "preferred_agent": "grok",
        "complexity": "complex",
        "context": "Модуль используется в flywheel pipeline"
      }'

### Поля задачи

| Поле | Тип | Обяз. | Описание |
|------|-----|:---:|----------|
| `title` | string | ✅ | Краткое название задачи |
| `description` | string | ✅ | Подробное описание |
| `priority` | string | ❌ | `critical` / `high` / `medium` / `low` (по умолчанию: `medium`) |
| `tags` | string[] | ❌ | Метки: `rust`, `fix`, `test`, `docs`, `frontend`, `architecture` |
| `preferred_agent` | string | ❌ | `grok` / `jules` / `antigravity` / `auto` |
| `complexity` | string | ❌ | `simple` / `medium` / `complex` |
| `context` | string | ❌ | Дополнительный контекст для агента |
| `dependencies` | string[] | ❌ | ID задач-зависимостей |

### Управление задачами

    # Список всех задач
    curl -s http://localhost:8080/tasks | python3 -m json.tool

    # Получить задачу по ID
    curl -s http://localhost:8080/tasks/<TASK_ID>

    # Обновить статус
    curl -X PATCH http://localhost:8080/tasks/<TASK_ID> \
      -H "Content-Type: application/json" \
      -d '{"status": "done", "result": "Задача выполнена успешно"}'

    # Диспатчить задачу агенту
    curl -X POST http://localhost:8080/tasks/<TASK_ID>/dispatch

    # Удалить задачу
    curl -X DELETE http://localhost:8080/tasks/<TASK_ID>

### Статусы задач

    pending → in_progress → done
                          → failed
                          → cancelled

---

## 2. Через MCP (Antigravity IDE)

Если в IDE доступны MCP-инструменты AgentForge:

| Инструмент | Описание |
|-----------|----------|
| `agentforge_create_task` | Создание задачи |
| `agentforge_list_tasks` | Список задач |
| `agentforge_get_task` | Получение по ID |
| `agentforge_update_task` | Обновление (статус, результат) |
| `agentforge_dispatch_task` | Диспатч агенту |
| `agentforge_metrics` | Метрики системы |

Пример использования в Antigravity:

> "Создай задачу: исправить парсер URL, приоритет high, тег fix, агент grok"

Antigravity автоматически вызовет `agentforge_create_task` с нужными параметрами.

---

## 3. Через Python (скрипты и автоматизация)

    import urllib.request, json

    # Создание задачи
    data = json.dumps({
        "title": "Моя задача",
        "description": "Описание задачи",
        "priority": "high",
        "tags": ["rust", "fix"],
        "preferred_agent": "grok"
    }).encode()

    req = urllib.request.Request(
        "http://localhost:8080/tasks",
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"}
    )
    resp = urllib.request.urlopen(req)
    task = json.loads(resp.read())
    print(f"Создана задача: {task['id']}")

### Батч-создание (через create_tasks.py)

На сервере есть готовые скрипты для массового создания задач:

    # Создание задач текущего спринта
    ssh eveselove@146.120.89.199 "cd ~/agentforge && python3 create_tasks.py"

    # Создание задач на архитектуру
    ssh eveselove@146.120.89.199 "cd ~/agentforge && python3 create_arch_tasks.py"

---

## 4. Целевое состояние: agentforge-runner task CLI (IMPLEMENTED + polished for 100%)

> ✅ Полная поддержка live (reqwest к gw 9090) в agentforge-runner task * : create (incl --from-file), list, get, update, dispatch, claim, reassign, approve, review, reject, reset-fakes, stats. 
> Нет необходимости в Python для управления задачами. (Accelerated in task-5af0e350)
> Текущий бинарник (v0.1.0, 1.41 MB) поддерживает flywheel, candidates и обучение.

### Планируемые команды

    # Создание задачи через CLI (будущее)
    agentforge-runner task create \
      --title "Исправить парсер" \
      --description "Описание" \
      --priority high \
      --tags rust,fix \
      --agent grok

    # Список задач
    agentforge-runner task list
    agentforge-runner task list --status pending --sort priority

    # Обновление статуса
    agentforge-runner task update <ID> --status done --result "Готово"

    # Claim задачи воркером
    agentforge-runner task claim <ID> --agent grok-worker-1

    # Диспатч
    agentforge-runner task dispatch <ID>

### Текущие команды runner-а (v0.1.0)

    agentforge-runner <COMMAND> [OPTIONS]

    Flywheel:
      flywheel-step       — один шаг flywheel (--real-data --ingest)
      continuous          — автономный мета-цикл (--top-n, --dry-run, --shadow)
      flywheel-export     — экспорт обучающих данных

    Candidates:
      candidate list      — список кандидатов (--top N, --sort value/recency)
      candidate promote   — продвижение кандидата (--copy-to-skills)

    Данные:
      export-pairs        — экспорт Rust-пар
      export-prm-steps    — экспорт PRM-шагов
      export-sft          — экспорт SFT-данных
      export-learning     — экспорт обучающих данных
      improve-skill       — улучшение навыка
      stats               — статистика

    Task mgmt (LIVE to 9090 gw, complete surface, replaces all py entrypoints):
      task create --title ".." [--priority high] [--from-file file.json] [--agent grok] ...
      task list [--status pending]
      task get/update/dispatch/claim <id>
      task reassign --from X --to Y [--pending-only] [--dry-run]
      task approve --all-review
      task review <id>
      task reject <id> --feedback "..."
      task reset-fakes | stats
      (default live via reqwest; --local for prototype store; full --json support. task-5af0e350)

    Общие флаги:
      --json              — JSON-вывод
      --trajectories DIR  — путь к траекториям
      --prm-dir DIR       — путь к PRM-данным
      --output FILE       — путь для вывода
      version             — версия бинарника
      help                — справка

---

## 5. Рекомендации по приоритетам задач

| Приоритет | Когда использовать |
|-----------|-------------------|
| `critical` | Продакшн сломан, блокер для команды |
| `high` | Важная фича или баг, нужно сегодня |
| `medium` | Обычная задача, в текущем спринте |
| `low` | Улучшение, рефакторинг, "было бы неплохо" |

---

## 6. Рекомендации по выбору агента

| Задача | Агент | Почему |
|--------|-------|--------|
| Быстрый фикс, Rust-код | `grok` | Быстрый мультиагентный исполнитель |
| Асинхронная задача, GitHub PR | `jules` | Фоновый агент для PRs |
| Архитектура, сложный рефакторинг | `antigravity` | Полный доступ к IDE + субагенты |
| Не уверен | `auto` | Маршрутизатор выберет оптимального |

---

## 7. Примеры типичных задач

### Баг-фикс

    curl -X POST http://localhost:8080/tasks \
      -H "Content-Type: application/json" \
      -d '{"title":"Fix: парсер падает на пустых строках","description":"stack trace: ...","priority":"high","tags":["fix","rust"],"preferred_agent":"grok"}'

### Документация

    curl -X POST http://localhost:8080/tasks \
      -H "Content-Type: application/json" \
      -d '{"title":"Обновить README.md","description":"Добавить секцию про CLI","priority":"low","tags":["docs"],"preferred_agent":"jules"}'

### Архитектурное решение

    curl -X POST http://localhost:8080/tasks \
      -H "Content-Type: application/json" \
      -d '{"title":"Спроектировать Axum API для Task System","description":"Заменить Flask queue_server.py на Rust Axum","priority":"high","tags":["architecture","rust"],"preferred_agent":"antigravity","complexity":"complex"}'

---

## 8. Инфраструктура

| Компонент | Адрес | Описание |
|-----------|-------|----------|
| Task API | `http://146.120.89.199:8080` | Python FastAPI (текущий) |
| Дашборд | `http://localhost:9090/dashboard` | Через SSH-туннель |
| Erbox | `eveselove@146.120.89.199` | Основной сервер |
| MCP-сервер | Через Antigravity IDE | agentforge_* инструменты |

### SSH-туннель для дашборда

    ssh -L 9090:localhost:8080 eveselove@146.120.89.199

Затем откройте http://localhost:9090/ в браузере.

---

## 9. Troubleshooting

| Проблема | Решение |
|----------|---------|
| `Connection refused` на 8080 | Проверить: `ssh agx@... "pgrep -f task_queue"` |
| Задача не диспатчится | Проверить статус: должен быть `pending` |
| Воркер не берёт задачу | Проверить: `ps aux | grep worker` |
| MCP не отвечает | Рестарт IDE, проверить mcp_server.py |

---

> **См. также:**
> - `TASK_MIGRATION_CHECKLIST.md` — чеклист миграции на Rust
> - `JULES_AUTO_FLYWHEEL_AFTER_TASK.md` — автоматический flywheel после задач
> - `HOW_TO_RUN_PURE_RUST_FLYWHEEL_TODAY.md` — запуск Rust flywheel
> - `README.md` — общая документация AgentForge

> Обновлено Antigravity агентом, задача AgentForge #06c5b97b
