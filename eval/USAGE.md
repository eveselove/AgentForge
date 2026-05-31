# Руководство по использованию Evaluation Framework

**AgentForge Evaluation Framework** — это ваша система измерения качества агентов. Без неё вы не понимаете, улучшаете ли вы систему или только добавляете новые баги.

> «You cannot improve what you cannot measure.»

Это не просто «запустить пару тестов». Это полноценный фреймворк с историей, детекцией регрессий, автоматическими инсайтами и рекомендациями — именно то, чем пользуются топ-команды (Anthropic, Cognition, OpenAI).

---

## Быстрый старт

```bash
# Посмотреть, какие бенчмарки доступны
python -m agentforge.eval list

# Запустить один бенчмарк в быстрой симуляции (без реального запуска агента)
python -m agentforge.eval run lancedb_parser_bottleneck

# Запустить реальную задачу и дождаться результата + автоматически сгенерировать отчёт
python -m agentforge.eval run crawler_core_extraction --real --wait --report

# Запустить ВСЕ бенчмарки параллельно (3 одновременно) и дождаться отчёта
python -m agentforge.eval run-all --real --wait --concurrency 3
```

После первых реальных прогонов сразу используйте:

```bash
python -m agentforge.eval dashboard
python -m agentforge.eval suggest
python -m agentforge.eval report
python -m agentforge.eval prm f12a11c0   # or full path / task prefix
python -m agentforge.eval view f12a11c0 --prm --html  # interactive replay with PRM scores + heatmap
```

### Где хранятся артефакты

Фреймворк автоматически создаёт и использует следующие директории (относительно `agentforge/eval/`):

- `results/` — сырые `EvaluationResult` (по одному JSON на запуск)
- `history/` — продольная история (`.jsonl` файл на каждый бенчмарк, append-only)
- `trajectories/` — structured JSONL-логи поведения агентов (из `log_trajectory.sh`)
- `mappings/` — связь бенчмарков с реальными `task_id` AgentForge
- `reports/` — сгенерированные Markdown-отчёты

Эти директории можно переопределять через переменные окружения (см. раздел «Продвинутые возможности»).

---

## Основные команды

| Команда              | Назначение                                      | Полезные флаги                          |
|----------------------|-------------------------------------------------|-----------------------------------------|
| `list`               | Список всех доступных бенчмарков                | —                                       |
| `run <name>`         | Запуск одного бенчмарка                         | `--real`, `--wait`, `--report`, `--agent` |
| `run-all`            | Запуск нескольких (или всех)                    | `--real --wait --concurrency N`         |
| `status`             | Статус реальных запущенных задач                | —                                       |
| `history [name]`     | История и тренды по бенчмарку (или всем)        | `--window 8`                            |
| `dashboard`          | Быстрый обзор здоровья системы                  | —                                       |
| `insights`           | Действенные инсайты из данных                   | `--json`                                |
| `suggest`            | Приоритизированные рекомендации «что делать»    | `--json`                                |
| `report`             | Генерация красивого Markdown-отчёта             | `--output путь`                         |
| `analyze`            | Анализ траекторий (structured logs)             | `--agent grok --json`                   |
| `prm <traj>`         | Score trajectory with Process Reward Model (step quality) | `--json`                             |
| `view <id>`          | Replay trajectory + PRM heatmap/timeline (text or HTML) | `--prm --html`                       |

**PRM (Process Reward Model) — Phase 1 killer feature**:
- Scores *every step* (llm_call, tool_call, reasoning...) on 0-1 quality scale using heuristics (fast) + future fine-tuned model.
- `overall_prm_score`, high/low quality step counts surfaced in reports, history, dashboard, insights, suggest.
- Use for: finding "success but brittle process", training better agents (export --with-prm), identifying weak reasoning patterns.
- Always available after real runs that log trajectories.

### Phase 1: `view` + `prm` + `--with-prm` (trajectory replay & learning data)

```bash
# Instant text replay + PRM scores on any real trajectory (by task prefix or path)
python -m agentforge.eval view f12a11c0 --prm

# Beautiful self-contained offline HTML with interactive timeline, PRM heatmap, live filters
python -m agentforge.eval view f12a11c0 --prm --html --output /tmp/traj_f12.html
# open /tmp/traj_f12.html  (works completely offline, JS filters by score/type/text)

# Direct PRM scoring (JSON for scripts)
python -m agentforge.eval prm f12a11c0 --json

# Export for training with full PRM step scores attached (perfect for PRM fine-tuning / critic)
python -m agentforge.eval export --with-prm --include-trajectories --only-real --output learning_datasets/my_prm_dataset.jsonl

# Preference pairs + PRM (DPO-ready)
python -m agentforge.eval export --generate-pairs --with-prm
```

The canonical loader powering everything:
```python
from agentforge.eval.trajectory import load_trajectory
traj = load_trajectory("f12a11c0", include_prm=True)   # or full path
print(traj["prm_result"]["overall_prm_score"])        # 0.71
print(len(traj["events"]))                            # normalized events
```

---



## Запуск бенчмарков: симуляция vs реальность

### 1. Симуляция (по умолчанию)

```bash
python -m agentforge.eval run lancedb_parser_bottleneck
```

- Быстро (1–2 секунды).
- **Не создаёт** реальную задачу в AgentForge.
- Полезна для проверки, что JSON валиден, и для отладки самого фреймворка.
- **Не даёт** настоящих метрик качества агента.

Используйте для smoke-тестов и разработки новых бенчмарков.

### 2. Реальные запуски (`--real`)

```bash
python -m agentforge.eval run lancedb_parser_bottleneck --real
```

- Создаёт задачу в AgentForge через API (`[EVAL] ...`).
- Задача получает теги `evaluation, benchmark, <category>`.
- Сохраняется **mapping** (связь бенчмарк ↔ реальный `task_id`).
- Траектория автоматически логируется (через `log_trajectory.sh` в раннерах).

### 3. Ожидание завершения (`--wait`) — самый важный флаг

```bash
python -m agentforge.eval run lancedb_parser_bottleneck --real --wait
```

Что происходит:
1. Задача диспетчится в AgentForge.
2. CLI переходит в режим поллинга (опрос API каждые 20–45 сек с backoff).
3. При завершении задачи (`done` / `review` / `failed`) — статус обновляется.
4. Запускается `verification_command` из описания бенчмарка (если есть).
5. Результат сохраняется, история обновляется.

**Без `--wait`** вы получите только `dispatched`. Полезно, когда вы хотите запустить много задач и уйти.

**С `--wait`** — вы получаете полный цикл: запуск → ожидание → верификация → запись в историю.

### 4. Параллельный запуск (`run-all --concurrency`)

```bash
python -m agentforge.eval run-all --real --wait --concurrency 4
```

- По умолчанию `concurrency=1` (последовательно).
- При `>1` использует `ThreadPoolExecutor`.
- Каждый бенчмарк выполняется независимо.
- **Рекомендация**: 2–4 на обычной машине. Больше — только если у вас мощный сервер и вы уверены, что агенты не будут конфликтовать за ресурсы (cargo, сеть и т.д.).

После завершения всех запусков автоматически генерируется общий отчёт (если `--report` или `--real --wait`).

---

## Мониторинг и история

### `status` — что сейчас выполняется

```bash
python -m agentforge.eval status
```

Показывает:
- Все бенчмарки, для которых создавались реальные задачи.
- `real_task_id`, агент, текущий статус, время диспетча и последнего обновления.
- Путь к файлу результата (если уже посчитан).

Отлично использовать, когда вы запустили большую партию без `--wait`.

### `history` — продольная память системы

```bash
# По одному бенчмарку
python -m agentforge.eval history lancedb_parser_bottleneck --window 10

# По всем (топ-15)
python -m agentforge.eval history
```

Выводит:
- Количество запусков
- Success rate
- Среднее время
- **Trend**: `improving` / `declining` / `stable` (простой, но эффективный алгоритм сравнения последних 3 прогонов с предыдущими)
- Последний исход

**Это фундамент для всего остального** (регрессии, insights, suggest, отчёты).

### `dashboard` — одна команда, чтобы понять общее состояние

```bash
python -m agentforge.eval dashboard
```

Быстрый дашборд:
- Статистика simulated vs real
- Количество отслеживаемых реальных задач
- 2–3 самых важных инсайта
- Призыв запустить `suggest`

Идеально для ежедневного утреннего ритуала.

---

## Insights и рекомендации

### `insights`

```bash
python -m agentforge.eval insights
# или в JSON для скриптов/дашбордов
python -m agentforge.eval insights --json
```

Автоматически находит:
- Declining тренды
- Высокий infrastructure overhead (много `infra_step` в траекториях)
- Низкое использование RAG
- **Обнаруженные регрессии**
- Общие сигналы

### `suggest` — «что мне делать прямо сейчас»

```bash
python -m agentforge.eval suggest
```

Это самый ценный вывод фреймворка.

Генерирует приоритизированный список действий:
- Красные флаги по низкому success rate
- Конкретные бенчмарки, которые нужно перезапустить и отладить
- Рекомендации по оптимизации частых инфраструктурных шагов
- Общие советы, когда данных ещё мало

**Используйте каждый раз перед тем, как садиться за большую задачу.**

---

## Регрессии — что это и почему это важно

**Регрессия** — это ситуация, когда недавняя производительность бенчмарка **значительно хуже**, чем исторический baseline.

Алгоритм (см. `regression.py`):
- Берёт последние N запусков (`window`, обычно 8)
- Берёт предыдущие запуски как baseline (`baseline_window`)
- Если падение success rate ≥ `threshold` (по умолчанию 15%) — флаг.

Регрессии автоматически:
- Показываются в `insights`
- Включаются в `suggest` с высоким приоритетом
- Выводятся красивой таблицей в отчётах
- Учитываются при расчёте Health Score

### Как работать с регрессиями

1. Увидели в `suggest` или `dashboard`.
2. `history <bench>` — подтвердите тренд.
3. Посмотрите, какие изменения вносились в раннер/скилл/промпт примерно в то же время.
4. Перезапустите проблемный бенчмарк несколько раз (`--real --wait`).
5. Если регрессия подтверждается — откатите подозрительное изменение или добавьте targeted отладку.
6. После фикса — несколько успешных прогонов должны перевести тренд в `improving`.

Это один из самых мощных механизмов предотвращения «тихого деградирования» качества агентов.

---

## Генерация отчётов и что в них смотреть

```bash
python -m agentforge.eval report
# или с кастомным именем
python -m agentforge.eval report --output reports/my_eval_2026-05-30.md
```

Отчёт генерируется в `eval/reports/` автоматически при `--report` / `--real --wait`.

### Что обязательно смотреть в отчёте

1. **Executive Summary + Health Score (0–100)**
   - Взвешенная оценка: реальные запуски весят больше всего.
   - Штрафы за регрессии, бонусы за improving-тренды.
   - `Strong` / `Acceptable` / `Needs Attention`.

2. **Simulated vs Real Comparison** (таблица)
   - Большая разница между симуляцией и реальностью — сигнал о distribution shift.

3. **Real Executions Detail**
   - Прямые ссылки на реальные `task_id` + статус + превью результата.

4. **Recent Performance Trends** (с ASCII sparklines)
   - Визуальные тренды по последним 8 запускам.

5. **Top Current Issues & Regressions**
   - Таблица регрессий + приоритизированные suggestions.

6. **Trajectory Insights**
   - Среднее время выполнения
   - Самые частые инфраструктурные шаги (цель для оптимизации)
   - Использование RAG / HITL

Отчёт — это артефакт, который можно сохранить в git, отправить коллегам или прикрепить к PR.

---

## Типичные workflows

### Workflow 1. Быстрая проверка перед большим изменением
```bash
python -m agentforge.eval run crawler_core_extraction --real --wait
python -m agentforge.eval suggest
```

### Workflow 2. Полноценный регрессионный прогон (перед релизом)
```bash
python -m agentforge.eval run-all --real --wait --concurrency 3 --report
# через 30–60 минут
python -m agentforge.eval dashboard
cat eval/reports/evaluation_report_*.md | less
```

### Workflow 3. Ежедневный мониторинг (утренний ритуал)
```bash
python -m agentforge.eval dashboard
python -m agentforge.eval suggest
python -m agentforge.eval history
```

### Workflow 4. Расследование регрессии
```bash
python -m agentforge.eval suggest
python -m agentforge.eval history lancedb_parser_bottleneck --window 12
python -m agentforge.eval insights
# дальше — targeted runs + анализ траекторий
python -m agentforge.eval analyze --agent grok
```

### Workflow 5. Сравнение поведения двух агентов (будущее)
```bash
# Пока агрегировано, но история уже позволяет
python -m agentforge.eval history some_bench --window 20
# В будущем: отдельные сравнения по агентам
```

### Workflow 6. Добавление нового бенчмарка + первая оценка
1. Создаёте `examples/my_new_hard_task.json` (реальная боль из истории).
2. `python -m agentforge.eval list` — проверяете, что появился.
3. `python -m agentforge.eval run my_new_hard_task --real --wait --report`
4. Изучаете отчёт и `suggest`.

### Workflow 7. Подготовка данных для обучения (Phase 1+)
- Все реальные запуски с `--wait` автоматически сохраняют:
  - `EvaluationResult` (с `prm_overall_score` + high/low counts)
  - Траектории (JSONL) — сразу доступны через `load_trajectory`
  - Историю (с PRM полями)
- Исследуйте поведение: `python -m agentforge.eval view <task> --prm --html`
- Экспорт с PRM для обучения:
  ```bash
  python -m agentforge.eval export --with-prm --generate-pairs --only-real
  python -m agentforge.eval export --with-prm --include-trajectories
  ```
- Эти данные идеально подходят для DPO, Process Reward Models, critic fine-tuning и preference tuning.

---

## Как добавлять свои бенчмарки (лучшие практики)

Просто киньте `.json` в `examples/`.

**Обязательные поля:**
- `id`, `title`, `description`
- `difficulty`, `category`, `tags`
- `verification` + `verification_command` (лучше всего) или `"manual_review"`

**Принципы отличного бенчмарка:**
- Взят из **реальной** истории проекта (не синтетика).
- Есть **объективная** верификация (cargo test / cargo check / golden diff > LLM judge).
- Указаны `required_skills` и `estimated_minutes`.
- Описывает настоящую боль (performance, сложный рефакторинг, интеграция).

Примеры высокого качества уже лежат в `examples/`.

---

## Продвинутые возможности

- **Переопределение директорий** (полезно в CI и тестах):
  ```bash
  AGENTFORGE_EVAL_HISTORY_DIR=/tmp/eval-history \
  AGENTFORGE_EVAL_TRAJECTORIES_DIR=/tmp/trajectories \
  python -m agentforge.eval ...
  ```

- **JSON-вывод** для скриптинга и дашбордов:
  `insights --json`, `suggest --json`, `analyze --json`

- **Автоматические отчёты** при `--real --wait` (и в `run-all`).

- Траектории можно анализировать отдельно:
  ```bash
  python -m agentforge.eval analyze --agent grok
  ```

---

## Troubleshooting

**«Нет реальных запусков» / status пустой**
- Вы ещё не запускали с `--real`.
- Или API AgentForge недоступен (`localhost:8080`).

**Верификация всегда падает**
- Проверьте `verification_command` в JSON бенчмарка.
- Убедитесь, что вы находитесь в правильном `repo_path`.

**Concurrency «съедает» всю машину**
- Уменьшайте `--concurrency`. Помните, что каждый агент может запускать cargo, сборки, сетевые запросы.

**История «не помнит» старые запуски**
- История пишется только при использовании Evaluation Framework (через `record_run`).
- Прямые запуски через обычный интерфейс не попадают в eval-историю (это нормально).

---

## Связанные файлы и следующий шаг

- `README.md` — философия и текущий статус.
- `schemas.py` — контракты данных.
- `runner.py` + `cli.py` — сердце выполнения.
- `history.py`, `regression.py`, `insights.py`, `suggest.py` — аналитика.
- `generate_evaluation_report.py` — генератор отчётов.
- `AGENTFORGE_FRONTIER_ROADMAP.md` — куда мы идём дальше (Phase 1: Process Reward Models, полноценный tracing, learning flywheel).

**Следующий уровень зрелости:**
- Интеграция результатов обратно в память (LanceDB).
- Автоматический запуск eval после каждого большого изменения в скиллах.
- Сравнение разных версий промптов/агентов по одним и тем же бенчмаркам.

---

*Создано с любовью к качеству и измеримому прогрессу. Используйте каждый день — и ваша система агентов будет становиться объективно лучше.*

**AgentForge Evaluation Framework — это не инструмент. Это культура.**
