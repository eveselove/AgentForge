# 📘 Jules Multi-Repo Guide — Как таргетировать любой репозиторий

> **Дата создания:** 2026-05-31
> **Автор:** AgentForge / Antigravity IDE

## Обзор

Jules — облачный AI-агент от Google, который создаёт Pull Requests в GitHub-репозиториях.
По умолчанию все задачи AgentForge направляются в `eveselove/planlytasksko`,
но архитектура поддерживает таргетинг **любого GitHub-репозитория** через поле `target_repo`.

---

## 🔧 Архитектура маршрутизации

### Цепочка передачи репозитория:

```
API (POST /tasks) → jules_worker.sh → jules_runner.sh → jules new --repo <REPO>
```

1. **API** принимает задачу с полем `target_repo` (или `repo`)
2. **jules_worker.sh** извлекает репо из JSON-задачи (строка Python-фильтра):
   ```python
   repo = t.get("target_repo") or t.get("repo") or "eveselove/planlytasksko"
   ```
3. **jules_runner.sh** получает репо как 3-й аргумент (`$3`) и запускает:
   ```bash
   jules new $JULES_FLAGS --repo "$REPO" "$TASK_DESC"
   ```

---

## 📋 Как создать задачу для конкретного репозитория

### Способ 1: Через API (curl)

```bash
# Создать задачу для основного репозитория (по умолчанию)
curl -s -X POST http://localhost:8080/tasks \
  -H 'Content-Type: application/json' \
  -d '{
    "title": "Добавить обработку ошибок в парсер",
    "description": "Реализовать try-catch для JSON парсинга",
    "priority": "high",
    "preferred_agent": "jules",
    "tags": ["fix", "rust"]
  }'

# Создать задачу для ДРУГОГО репозитория
curl -s -X POST http://localhost:8080/tasks \
  -H 'Content-Type: application/json' \
  -d '{
    "title": "Обновить README для chromimic",
    "description": "Добавить инструкции по установке",
    "priority": "medium",
    "preferred_agent": "jules",
    "target_repo": "eveselove/chromimic",
    "tags": ["docs"]
  }'
```

### Способ 2: Через MCP (Antigravity IDE)

```
agentforge_create_task:
  title: "Рефакторинг модуля X"
  description: "Вынести утилиты в отдельный файл"
  priority: "medium"
  preferred_agent: "jules"
  target_repo: "eveselove/some-other-repo"
  tags: ["refactor"]
```

### Способ 3: Через Jules CLI напрямую

```bash
# Прямой запуск на конкретном репозитории
jules new --repo eveselove/chromimic "Описание задачи на русском"

# С параллельными сессиями
jules new --parallel 3 --repo eveselove/turboquant-vllm "Задача"

# На приватном репозитории (требуется доступ через GitHub)
jules new --repo eveselove/private-project "Задача"
```

---

## 🏢 Известные репозитории

### Основной (дефолтный)
| Репозиторий | GitHub | Описание |
|-------------|--------|----------|
| `eveselove/planlytasksko` | ✅ Основной | Главный проект, дефолт для всех задач |

### Вторичные (обнаруженные на Erbox)
| Локальный путь | Возможный GitHub-репо | Описание |
|----------------|----------------------|----------|
| `/home/eveselove/planlytasksko/chromimic` | `eveselove/chromimic` | Подпроект chromimic |
| `/home/eveselove/planlytasksko/turboquant-vllm` | `eveselove/turboquant-vllm` | vLLM-форк для квантования |
| `/home/eveselove/planlytasksko/blutter` | `eveselove/blutter` | Flutter RE-инструмент |

> ⚠️ **Важно:** Jules работает с GitHub-репозиториями через облако Google.
> Локальные пути на Erbox не используются напрямую — нужен валидный `owner/repo` на GitHub.
> Убедитесь, что репозиторий существует на GitHub и Jules имеет к нему доступ.

---

## 🔑 Требования для подключения нового репозитория

### 1. Репозиторий должен быть на GitHub
Jules создаёт PR через GitHub API. Репозитории на других платформах (GitLab, Bitbucket) не поддерживаются.

### 2. Jules должен иметь доступ
- Для **публичных** репозиториев — доступ автоматический
- Для **приватных** репозиториев — нужно авторизовать Jules App в настройках GitHub:
  1. Перейти в GitHub → Settings → Applications → Jules
  2. Добавить нужный репозиторий в список разрешённых
  3. Проверить: `jules new --repo owner/repo "test"` — должен создать сессию

### 3. Формат имени репозитория
Всегда используйте формат `owner/repo`:
- ✅ `eveselove/planlytasksko`
- ✅ `eveselove/chromimic`
- ❌ `planlytasksko` (без owner)
- ❌ `git@github.com:eveselove/planlytasksko.git` (полный URL)
- ❌ `/home/eveselove/planlytasksko` (локальный путь)

---

## 📊 Примеры реальных сценариев

### Сценарий 1: Пакетное создание задач для нескольких репо

```bash
# Скрипт для создания задач в нескольких репозиториях одновременно
REPOS=("eveselove/planlytasksko" "eveselove/chromimic" "eveselove/turboquant-vllm")

for REPO in "${REPOS[@]}"; do
  curl -s -X POST http://localhost:8080/tasks \
    -H 'Content-Type: application/json' \
    -d "{
      \"title\": \"Обновить CI/CD пайплайн\",
      \"description\": \"Добавить cargo clippy и cargo test в GitHub Actions\",
      \"priority\": \"medium\",
      \"preferred_agent\": \"jules\",
      \"target_repo\": \"$REPO\",
      \"tags\": [\"ci\", \"infrastructure\"]
    }"
  echo "✅ Задача создана для $REPO"
done
```

### Сценарий 2: Проверка — какие задачи на каких репо

```bash
# Просмотр распределения задач по репозиториям
curl -s http://localhost:8080/tasks | python3 -c "
import sys, json
from collections import Counter
tasks = json.load(sys.stdin)
repos = Counter()
for t in tasks:
    repo = t.get('target_repo') or t.get('repo') or 'eveselove/planlytasksko (дефолт)'
    repos[repo] += 1
for repo, count in repos.most_common():
    print(f'  {repo}: {count} задач')
"
```

---

## ⚙️ Конфигурация worker для multi-repo

### Текущая конфигурация (`jules_worker.sh`)
Воркер уже поддерживает multi-repo «из коробки» — никаких изменений не требуется.

**Ключевая строка фильтра (Python):**
```python
repo = t.get("target_repo") or t.get("repo") or "eveselove/planlytasksko"
```

### Текущая конфигурация (`jules_runner.sh`)
Раннер принимает `$3` (третий аргумент) как репозиторий:
```bash
REPO="${3:-eveselove/planlytasksko}"
# ...
jules new $JULES_FLAGS --repo "$REPO" "$TASK_DESC"
```

### Git Worktree изоляция
Раннер создаёт worktree для изоляции, но это не критично для Jules,
т.к. Jules работает в облаке и не использует локальные файлы:
```bash
git -C "/home/eveselove/planlytasksko" worktree add "$WORKTREE_DIR" -b "agentforge/$TASK_ID"
```

> **Замечание:** Worktree создаётся только для основного репо.
> Если нужна worktree-изоляция для вторичных репо, необходимо модифицировать
> `jules_runner.sh` для определения корректного локального пути.

---

## 🚨 Troubleshooting

### Jules не может создать сессию для репозитория
```
ERROR: Jules failed to create sessions
```
**Решение:**
1. Проверить, что репо существует: `gh repo view owner/repo`
2. Проверить доступ Jules: GitHub → Settings → Applications → Jules
3. Проверить Jules CLI: `jules --version`
4. Тестовый запуск: `jules new --repo owner/repo "test task"`

### Задача создаётся без target_repo
**Решение:** Убедитесь, что JSON содержит поле `target_repo`:
```bash
curl -s http://localhost:8080/tasks/TASK_ID | python3 -m json.tool | grep repo
```

### Worker игнорирует target_repo
**Решение:** Проверьте что worker запущен из актуальной версии:
```bash
systemctl status agentforge-jules-worker
# Или перезапуск:
sudo systemctl restart agentforge-jules-worker
```

---

## 📌 Резюме

| Что | Как |
|-----|-----|
| Поле в API | `target_repo` (или `repo`) |
| Формат | `owner/repo` (GitHub) |
| Дефолт | `eveselove/planlytasksko` |
| CLI | `jules new --repo owner/repo "задача"` |
| Требования | Репо на GitHub + доступ Jules App |

---

## 📝 Статус вторичных репозиториев

На текущий момент (2026-05-31):
- **Jules Worker** временно отключён (см. комментарий в `jules_worker.sh`)
- Причина: backlog + нестабильность создания сессий в Jules cloud
- **Multi-repo поддержка** полностью реализована в коде worker/runner
- **Для активации:** исправить проблемы с Jules cloud, перезапустить worker
