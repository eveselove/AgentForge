# 🔍 Аудит Jules Worker и Runner

> **Дата:** 2026-05-31
> **Автор:** Antigravity (AgentForge Architect)
> **Задачи:** 146d0292 (multi-repo readiness), a19bb072 (Rust flywheel integration)
> **Файлы:** `jules_worker.sh`, `agents/jules_runner.sh`

---

## 📋 Общее описание

Оба файла реализуют конвейер обработки задач Jules:
- **jules_worker.sh** — поллер: забирает pending-задачи из API (`localhost:8080`), фильтрует по `preferred_agent=jules`, вызывает runner.
- **jules_runner.sh** — исполнитель: создаёт git worktree для изоляции, запускает `jules new` (облако Google), обновляет статус задачи.

**Текущий статус:** TEMPORARILY DISABLED (большой бэклог + проблемы с Jules cloud).

---

## Часть 1: Multi-Repo Readiness (задача 146d0292)

### ✅ Что уже работает

1. **Динамический repo из task data** — Worker извлекает `target_repo` или `repo` из JSON задачи:
   ```python
   repo = t.get("target_repo") or t.get("repo") or "eveselove/planlytasksko"
   ```
2. **Передача repo в runner** — 3-й аргумент `$RUNNER`:
   ```bash
   bash "$RUNNER" "$TASK_ID" "$TITLE. $DESC" "$REPO" "$PRIORITY"
   ```
3. **Runner принимает repo** — `REPO="${3:-eveselove/planlytasksko}"` и передаёт в `jules new --repo "$REPO"`.

### ⚠️ Проблемы и рекомендации

| # | Проблема | Серьёзность | Рекомендация |
|---|----------|-------------|--------------|
| 1 | **Hardcoded fallback repo** в 3 местах: worker (Python), worker (bash), runner. Дублирование дефолта `eveselove/planlytasksko` | Средняя | Вынести дефолтный repo в `config.json` или env-переменную `AGENTFORGE_DEFAULT_REPO`. Использовать одну точку правды |
| 2 | **Git worktree всегда создаётся от `/home/agx/planlytasksko`** — не учитывает dynamic repo | Высокая | Для multi-repo нужно: (а) клонировать целевой repo если он не `planlytasksko`, или (б) маппинг repo→local_path в конфиге |
| 3 | **Нет валидации формата repo** — если task data содержит невалидный repo (не `owner/name`), `jules new` упадёт без внятной ошибки | Средняя | Добавить regex-валидацию формата `^[a-zA-Z0-9_-]+/[a-zA-Z0-9_.-]+$` перед запуском |
| 4 | **Нет кеширования клонов** — при повторных задачах к одному repo каждый раз будет создаваться worktree | Низкая | Создать пул клонов в `/home/agx/agentforge/repos/` с lazy-клонированием |
| 5 | **Fallback repo в Python inline-скрипте** — сложно редактировать, нет тестов | Средняя | Вынести фильтрацию задач в отдельный Python-модуль `agentforge.workers.task_filter` |
| 6 | **Нет поддержки branch/ref из task data** — задача может указать конкретную ветку для PR | Низкая | Добавить поле `target_branch` в task schema и передавать `--branch` в `jules new` |

### 🏗️ Предлагаемая архитектура multi-repo

```json
// config.json (новое)
{
  "default_repo": "eveselove/planlytasksko",
  "repo_cache_dir": "/home/agx/agentforge/repos",
  "repo_map": {
    "eveselove/planlytasksko": "/home/agx/planlytasksko",
    "eveselove/other-project": null
  }
}
```

```bash
# В runner: resolve_repo_path()
resolve_repo_path() {
    local repo="$1"
    local config="/home/agx/agentforge/config.json"
    local local_path
    local_path=$(python3 -c "
import json
with open('$config') as f:
    cfg = json.load(f)
print(cfg.get('repo_map',{}).get('$repo',''))
" 2>/dev/null)
    if [ -n "$local_path" ] && [ -d "$local_path" ]; then
        echo "$local_path"
    else
        local cache_dir="/home/agx/agentforge/repos/$repo"
        if [ ! -d "$cache_dir" ]; then
            git clone "https://github.com/$repo.git" "$cache_dir"
        fi
        echo "$cache_dir"
    fi
}
```

---

## Часть 2: Rust Flywheel Integration (задача a19bb072)

### ✅ Что уже работает

1. **Многоуровневая инициализация Rust flywheel**:
   - Source `rust_flywheel.env` (канонический сниппет с env-переменными)
   - Source `enable_rust_flywheel.sh` (расширенная настройка)
   - Выбор release/debug бинарника `agentforge-runner`
   - Export `AGENTFORGE_RUST_FLYWHEEL=1`, `AGENTFORGE_USE_RUST=1`, `AGENTFORGE_RUST_RUNNER`

2. **Post-task flywheel hook** (worker):
   ```bash
   bash /home/agx/agentforge/bin/rust_flywheel_after_task.sh "$TASK_ID"
   ```
   Запускается асинхронно (`&`) после завершения задачи — не блокирует worker.

3. **Python post-process hook** (runner):
   ```bash
   python3 -m agentforge.bin.rust_post_process_hook "$TASK_ID"
   ```
   Также асинхронно. Проверяет `is_pure_rust_flywheel()` для deprecation warnings.

4. **Pure Rust cutover** — оба файла имеют блок Pure Rust Flywheel Default (маркер `.pure_rust_flywheel`).

5. **Kill switches** работают корректно:
   - `DISABLE_RUST_FLYWHEEL=1` (env)
   - `/home/agx/agentforge/.disable_rust_flywheel` (файл)

### ⚠️ Проблемы и рекомендации

| # | Проблема | Серьёзность | Рекомендация |
|---|----------|-------------|--------------|
| 1 | **Массивное дублирование кода инициализации** — Rust flywheel setup повторяется 3 раза в worker и 2 раза в runner (env snippet + enable script + manual export + pure section) | 🔴 Критическая | Консолидировать в единый `source /home/agx/agentforge/bin/init_rust_flywheel.sh` который вызывается один раз |
| 2 | **Двойной выбор release/debug бинарника** — в worker бинарник определяется дважды (строки ~30 и ~50), причём логика идентична | Средняя | Убрать дублирование — определять один раз после source сниппета |
| 3 | **Pure Rust блок после `while true` — недостижимый код** — В worker блок Pure Rust Flywheel Default стоит ПОСЛЕ бесконечного цикла, т.е. никогда не выполнится | 🔴 Критическая | Перенести блок Pure Rust ПЕРЕД основным циклом (после init секции) |
| 4 | **Pure Rust блок после `exit`/`cleanup` в runner — мёртвый код** — Аналогично: блок после `cleanup_worktree` и `echo` в конце, после trap EXIT | 🔴 Критическая | Перенести блок Pure Rust в начало runner (после source секции) |
| 5 | **Конфликт между двумя post-task hooks** — worker вызывает `rust_flywheel_after_task.sh`, runner вызывает `python3 -m agentforge.bin.rust_post_process_hook`. Оба async, оба могут сработать одновременно | Высокая | Определиться: или Rust hook (worker), или Python hook (runner). При `is_pure_rust_flywheel()=1` — только Rust. Убрать дублирование |
| 6 | **Rate-limit в env (`AGENTFORGE_RUST_FLYWHEEL_EVERY_N=5`) не проверяется в worker** — worker вызывает hook безусловно после каждой задачи | Средняя | Добавить счётчик в worker или делегировать rate-limit на `rust_flywheel_after_task.sh` (у него свой lock) |
| 7 | **Trajectory logging в runner вызывается ДО присвоения `TASK_ID`** — строки `export TASK_ID="$TASK_ID"` и `log_task_start` идут до `TASK_ID="$1"` | Высокая | Переместить trajectory init ПОСЛЕ парсинга аргументов ($1, $2, $3, $4) |
| 8 | **Нет проверки существования `agentforge-runner` бинарника** — если бинарник не собран, переменная указывает на несуществующий файл | Средняя | Добавить `if [ ! -x "$AGENTFORGE_RUST_RUNNER" ]; then log "WARN: Rust runner not found"; fi` |

### 🏗️ Предлагаемый рефакторинг init блока

```bash
#!/bin/bash
# /home/agx/agentforge/bin/init_rust_flywheel.sh
# Единый инициализатор Rust flywheel — вызывать один раз в начале каждого worker/runner

AGENTFORGE_DIR="/home/agx/agentforge"

# 1. Source env snippet
[ -f "$AGENTFORGE_DIR/bin/rust_flywheel.env" ] && \
    source "$AGENTFORGE_DIR/bin/rust_flywheel.env" 2>/dev/null || true

# 2. Проверяем kill switches
if [[ "${DISABLE_RUST_FLYWHEEL:-0}" = "1" ]] || \
   [[ -f "$AGENTFORGE_DIR/.disable_rust_flywheel" ]]; then
    export AGENTFORGE_RUST_FLYWHEEL=0
    export AGENTFORGE_USE_RUST=0
    export AGENTFORGE_PURE_RUST_FLYWHEEL=0
    return 0 2>/dev/null || exit 0
fi

# 3. Включаем flywheel
export AGENTFORGE_RUST_FLYWHEEL=1
export AGENTFORGE_USE_RUST=1

# 4. Выбираем бинарник (release > debug)
if [ -x "$AGENTFORGE_DIR/rust/target/release/agentforge-runner" ]; then
    _RUNNER="$AGENTFORGE_DIR/rust/target/release/agentforge-runner"
elif [ -x "$AGENTFORGE_DIR/rust/target/debug/agentforge-runner" ]; then
    _RUNNER="$AGENTFORGE_DIR/rust/target/debug/agentforge-runner"
else
    echo "[WARN] agentforge-runner бинарник не найден" >&2
    _RUNNER=""
fi
export AGENTFORGE_RUST_RUNNER="${AGENTFORGE_RUST_RUNNER:-$_RUNNER}"

# 5. Pure Rust mode
PURE_MARKER="$AGENTFORGE_DIR/.pure_rust_flywheel"
if [[ -f "$PURE_MARKER" ]] || \
   [[ "${AGENTFORGE_PURE_RUST_FLYWHEEL:-0}" = "1" ]] || \
   [[ "${AGENTFORGE_FLYWHEEL_ENGINE:-}" = "rust" ]]; then
    export AGENTFORGE_PURE_RUST_FLYWHEEL=1
    export AGENTFORGE_FLYWHEEL_ENGINE=rust
    export AGENTFORGE_FLYWHEEL_PROVENANCE="rust-agentforge-runner"
fi

# 6. Enable script (если есть дополнительная инициализация)
[ -x "$AGENTFORGE_DIR/bin/enable_rust_flywheel.sh" ] && \
    source "$AGENTFORGE_DIR/bin/enable_rust_flywheel.sh" 2>/dev/null || true
```

---

## 📊 Сводка критических находок

| ID | Категория | Серьёзность | Описание |
|----|-----------|-------------|----------|
| C1 | Мёртвый код | 🔴 Критическая | Pure Rust блоки после `while true` (worker) и после exit (runner) — никогда не выполняются |
| C2 | Дублирование | 🔴 Критическая | Rust flywheel init повторяется 5+ раз между двумя файлами |
| C3 | Порядок init | 🟠 Высокая | Trajectory logging вызывается до присвоения `TASK_ID` в runner |
| C4 | Двойной hook | 🟠 Высокая | worker и runner оба вызывают post-task flywheel hook (Rust и Python соответственно) — race condition |
| C5 | Multi-repo | 🟠 Высокая | Worktree создаётся от захардкоженного пути — не работает с dynamic repos |

---

## 🎯 План действий (приоритет)

### Немедленно (перед включением Jules обратно)
1. Перенести Pure Rust блоки в начало файлов (до основного цикла/логики)
2. Исправить порядок trajectory init в runner
3. Определиться с одним post-task hook (Rust или Python)

### Краткосрочно (1-2 дня)
4. Создать `init_rust_flywheel.sh` — единый init для всех workers/runners
5. Вынести `DEFAULT_REPO` в конфиг
6. Добавить валидацию repo формата

### Среднесрочно (следующий спринт)
7. Реализовать repo cache pool для multi-repo
8. Добавить `target_branch` поддержку в task schema
9. Вынести inline Python (фильтрация задач) в модуль

---

> **Статус:** Аудит завершён. Рекомендуется не включать Jules Worker до исправления критических находок C1-C4.
