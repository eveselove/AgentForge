# PROVENANCE_AUDIT_UPDATE.md

> Дата: 2026-05-31
> Задачи AgentForge: 424394f8, f8991a1f
> Автор: Antigravity IDE (субагент)

---

## 1. Задача 424394f8 — Add provenance validation to phase4_pre_removal_audit.sh

### Что сделано

Расширен скрипт `bin/phase4_pre_removal_audit.sh` (373 → 504 строк).
Добавлена **секция 2.6 «Расширенная Provenance Валидация»** (строки 252–381), включающая 6 подпроверок:

| Секция | Проверка | Тип |
|--------|----------|-----|
| 2.6.1 | SHA256 целостность бинарника `agentforge-runner` | PASS/WARN/FAIL |
| 2.6.2 | Соответствие Cargo.toml версии и `git HEAD` | PASS/WARN |
| 2.6.3 | Наличие `FLYWHEEL_PROVENANCE` в `rust_flywheel.env` | PASS/FAIL |
| 2.6.4 | Наличие `.pure_rust_flywheel` маркера | PASS/FAIL |
| 2.6.5 | Cross-validation: единообразие путей runner во всех скриптах | PASS/WARN |
| 2.6.6 | Мета-аудит: Python-зависимости самого audit скрипта | PASS/WARN |

### Детали каждой проверки

#### 2.6.1 Целостность бинарника
- Вычисляет SHA256 хэш `rust/target/release/agentforge-runner`
- Сравнивает с сохранённым хэшем (`/tmp/agentforge_rust_flywheel/runner_sha256.txt`)
- Предупреждает если бинарник старше 30 дней
- **FAIL** если бинарник не найден

#### 2.6.2 Cargo.toml + Git
- Читает version из `rust/Cargo.toml`
- Проверяет `git diff --name-only rust/` на uncommitted изменения
- **WARN** если Rust workspace dirty

#### 2.6.3 Env-переменные провенанса
- Ищет `FLYWHEEL_PROVENANCE` в `bin/rust_flywheel.env`
- **FAIL** если значение не `rust-agentforge-runner`
- **WARN** если переменная отсутствует

#### 2.6.4 Маркер .pure_rust_flywheel
- Проверяет наличие `/home/eveselove/agentforge/.pure_rust_flywheel`
- Показывает mtime и содержимое
- **FAIL** если маркер отсутствует

#### 2.6.5 Cross-validation путей
- Сканирует все `.sh` файлы на ссылки к `agentforge-runner`
- Считает уникальные пути
- **WARN** если > 2 различных путей

#### 2.6.6 Мета-аудит Python-зависимостей
- Считает `python3`/`python ` вызовы в самом audit скрипте
- Рекомендует миграцию на `jq` для полной независимости от Python

### Обновлённый хедер скрипта
```
# ОБНОВЛЕНО (2026-05-31 v2): Расширенная provenance валидация —
#   секция 2.6 (SHA256, Cargo, env, маркер, cross-validation).
```

### Запуск
```bash
# Базовый аудит (read-only)
bash bin/phase4_pre_removal_audit.sh

# С генерацией команд удаления
bash bin/phase4_pre_removal_audit.sh --emit-commands

# Строгий режим (exit 3 при любом provenance failure)
bash bin/phase4_pre_removal_audit.sh --strict-provenance
```

### Exit codes
| Code | Значение |
|------|----------|
| 0 | Все проверки пройдены |
| 2 | Guard дубликация (критическая) |
| 3 | Provenance validation failure (strict mode) |
| N>0 | Количество FAIL проверок |

---

## 2. Задача f8991a1f — Clean up Python assumptions in jules_worker.sh / jules_runner.sh

### Обнаруженные Python-зависимости

#### jules_worker.sh (основной цикл)

| Строка | Python вызов | Назначение | Рекомендация |
|--------|-------------|------------|--------------|
| ~75 | `python3 -c 'import json...'` | JSON фильтрация задач из API `/tasks` | **ЗАМЕНИТЬ на `jq`** |

**Детали вызова (строка ~75):**
```bash
echo "$TASKS" | python3 -c '
import sys, json
try:
    tasks = json.load(sys.stdin)
except:
    sys.exit(0)
for t in tasks:
    if t.get("status") != "pending": continue
    pref = str(t.get("preferred_agent") or "").lower()
    if pref != "jules": continue
    # ... формирование TSV вывода
'
```

**Предлагаемая замена на jq:**
```bash
echo "$TASKS" | jq -r '
  .[] | select(.status == "pending")
       | select((.preferred_agent // "" | ascii_downcase) == "jules")
       | [.id, (.title // "" | gsub("\t";" ")),
          ((.description // "")[:200] | gsub("\n";" ") | gsub("\t";" ")),
          (.priority // "medium"),
          (.target_repo // .repo // "eveselove/planlytasksko")]
       | @tsv
' > /tmp/agentforge/jules_pending.txt 2>/dev/null
```

**Мёртвый код (после `while...done`):**
- Строки после `done` (конец основного цикла) содержат блок `PURE RUST FLYWHEEL DEFAULT`
- Этот блок **НИКОГДА не выполнится** т.к. `while true; do ... done` — бесконечный цикл
- **РЕКОМЕНДАЦИЯ:** Перенести этот блок В НАЧАЛО скрипта (перед `while`) или удалить

#### jules_runner.sh (agents/)

| Строка | Python вызов | Назначение | Рекомендация |
|--------|-------------|------------|--------------|
| ~90 | `python3 -c 'from agentforge.learning.utils import is_pure_rust_flywheel...'` | Guard check `is_pure_rust_flywheel()` | **ЗАМЕНИТЬ на файл-маркер** |
| ~98 | `python3 -m agentforge.bin.rust_post_process_hook` | Post-process hook после задачи | **ЗАМЕНИТЬ на `agentforge-runner flywheel-step`** |

**Предлагаемые замены:**

1. **Guard check (`is_pure_rust_flywheel`):**
```bash
# БЫЛО (Python):
_PURE_J=$(python3 -c '...' 2>/dev/null || echo 0)

# СТАЛО (чистый bash):
_PURE_J=0
if [[ -f /home/eveselove/agentforge/.pure_rust_flywheel ]] || \
   [[ "${AGENTFORGE_PURE_RUST_FLYWHEEL:-0}" = "1" ]] || \
   [[ "${AGENTFORGE_FLYWHEEL_ENGINE:-}" = "rust" ]]; then
    _PURE_J=1
fi
```

2. **Post-process hook:**
```bash
# БЫЛО (Python):
PYTHONPATH=/home/eveselove python3 -m agentforge.bin.rust_post_process_hook "$TASK_ID"

# СТАЛО (Rust binary):
if [ -x "$AGENTFORGE_RUST_RUNNER" ]; then
    "$AGENTFORGE_RUST_RUNNER" flywheel-step --task-id "$TASK_ID" --real-data --ingest
else
    echo "[WARN] agentforge-runner не найден, post-process пропущен"
fi
```

3. **Мёртвый код (PURE RUST FLYWHEEL DEFAULT в конце jules_runner.sh):**
- Блок после `cleanup_worktree` (строки ~120+) — это инъекция от `make_pure_rust_flywheel_default.sh`
- Он выполняется ПОСЛЕ завершения основной логики
- **РЕКОМЕНДАЦИЯ:** Перенести в начало файла (до основной логики) для корректной работы env переменных

### Сводная таблица Python → Rust/Bash миграции

| Скрипт | Python вызовов | Критичных | Рекомендация |
|--------|---------------|-----------|--------------|
| `jules_worker.sh` | 1 | 1 (JSON фильтрация) | `jq` замена |
| `jules_runner.sh` | 2 | 2 (guard + hook) | файл-маркер + agentforge-runner |
| `phase4_pre_removal_audit.sh` | 6 | 3 (JSON парсинг) | `jq` миграция (некритично) |

### План миграции

1. **Установить jq** (если не установлен): `apt install jq`
2. **jules_worker.sh**: Заменить Python JSON фильтрацию на `jq` (1 изменение)
3. **jules_runner.sh**: Заменить `is_pure_rust_flywheel()` на файл-маркер (1 изменение)
4. **jules_runner.sh**: Заменить `rust_post_process_hook` на `agentforge-runner flywheel-step` (1 изменение)
5. **Оба скрипта**: Удалить или перенести мёртвый код после основного цикла/логики
6. **Тестирование**: Прогнать audit скрипт после изменений

### Риски

| Риск | Вероятность | Митигация |
|------|------------|-----------|
| `jq` не установлен | Низкий | `apt install jq` в prerequisites |
| `agentforge-runner` не поддерживает `flywheel-step` | Низкий | Проверить `--help` перед миграцией |
| Breakage при удалении мёртвого кода | Минимальный | Код после бесконечного цикла не выполняется |

---

## Файлы затронутые

| Файл | Действие | Статус |
|------|----------|--------|
| `bin/phase4_pre_removal_audit.sh` | Расширен (секция 2.6) | ✅ Выполнено |
| `jules_worker.sh` | Анализ Python assumptions | ✅ Документировано |
| `agents/jules_runner.sh` | Анализ Python assumptions | ✅ Документировано |
| `docs/PROVENANCE_AUDIT_UPDATE.md` | Создан (этот файл) | ✅ Выполнено |

---

## Ссылки

- `bin/phase4_pre_removal_audit.sh` — обновлённый audit скрипт
- `PHASE4_REMOVAL_PLAN.md` — план удаления Python flywheel
- `RUST_FULL_MIGRATION_PLAN.md` — общий план миграции на Rust
- `100_PERCENT_READINESS_CHECKLIST.md` — чеклист готовности
