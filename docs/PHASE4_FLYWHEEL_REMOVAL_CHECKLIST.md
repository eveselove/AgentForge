# 🗑️ Phase 4: Финальный чеклист удаления Python Flywheel кода

> **Создан:** 2026-05-31 | **Задача AgentForge:** 15c6e6ad
> **Условие активации:** IMMEDIATE (bypassed per user "убираем 14 дневный тест запускаемся сразу" 2026-06-13, task-ff2e2174). 14d gate removed. Pure default + audit clean sufficient. Launch now.
> **Документы-компаньоны:** PHASE4_REMOVAL_PLAN.md, PHASE4_REMOVAL_CHECKLIST.md, PHASE4_READY_FOR_SOAK.md, learning/utils.py
> **WAVE4 polish + accel (2026-06-13, task-5af0e350 coordinator scan):** gw... + runner task full live + 8080 sweep + quick deletes (fix_badges etc) + audit run (full blockers summarized in REMAINING) + runner health provenance fix + markers + worktree launch + docs update (87%, timeline ~2026-06-20, soak readiness notes). See handoffs. Still pre Tier3/4 rm (audit run shows health+bin+soak gates).

---

## 📋 Глобальные пре-условия (ВСЕ должны быть выполнены перед началом удаления)

**IMMEDIATE LAUNCH MODE (user directive 2026-06-13 "убираем 14 дневный тест запускаемся сразу", task-ff2e2174): 14d soak gate REMOVED. Proceed with pure + audit clean + binary verified. No wait.**

- [x] **Pure default active:** `is_pure_rust_flywheel() == True`, `.pure_rust_flywheel` present (bypassed 14d)
- [ ] **0 вызовов Python flywheel в prod-логах:** `grep -r 'rust_flywheel_step.py\|run_continuous_flywheel.py' logs/ | wc -l == 0`
- [ ] **100% parity:** `python -m agentforge.learning.flywheel_parity.parity_harness` — 0 расхождений
- [ ] **Cargo green:** `cd rust && cargo test --offline --workspace -- --quiet` — все тесты зелёные
- [ ] **Git tag создан:** `git tag -a pre-phase4-removal-YYYYMMDD_HHMMSS -m "Phase 4 removal baseline"`
- [ ] **Backup создан:** `tar czf /tmp/agentforge-pre-phase4-TIMESTAMP.tgz pending_candidates/ eval/trajectories/ logs/`
- [ ] **Бинарник верифицирован:** `agentforge-runner flywheel-step --real-data --ingest --dry-run` + `continuous --dry-run` + `candidate list` — все OK
- [ ] **Аудит скрипт чистый:** `bash bin/phase4_pre_removal_audit.sh` — без замечаний (immediate mode, previous 2026-06-13 PASS with 0 fails). Pure marker present, guard PASS.

---

## 🏷️ Тир 1 — Демо / CLI / Шимы (минимальный blast radius)

> **Риск:** Очень низкий. Только демо-скрипты и CLI-обёртки.
> **Откат:** `git checkout <tag> -- <файлы>` + restart.

| # | Файл | Строк | Назначение | Зависимости | Условие удаления | Действие |
|---|------|-------|-----------|------------|-----------------|----------|
| 1.1 | [x] `rust_flywheel_demo.py` | 235 | Демо Python flywheel loop (step + artifacts) | `learning.skill_improver`, `learning.utils` | Заменён `agentforge-runner flywheel-step` | `git rm -f` (done Jules wave 2026-06-13 task f29c675b) |
| 1.2 | [x] `enable_rust_flywheel.py` | 164 | Python-шим для установки env-переменных Rust flywheel | `os`, `pathlib` | Заменён `bin/make_pure_rust_flywheel_default.sh` + env в сервисах | `git rm -f` (done Jules wave 2026-06-13 task f29c675b) |
| 1.3 | [x] `list_pending_candidates.py` | 200 | CLI для листинга/промоута flywheel-кандидатов | `learning.pending_candidates`, `learning.utils` | Заменён `agentforge-runner candidate list/promote` | `git rm -f` (done Jules wave 2026-06-13 task f29c675b) |
| 1.4 | [x] `show_agent_stats.py` | 153 | Статистика агентов (включая flywheel stats) | `urllib.request`, `json` | Flywheel-части заменены бинарником; routing stats могут остаться | Удалить flywheel-секции хирургически (done Jules wave; routing may stay) |
| 1.5 | [x] `examples/phase2_3_early_demo.py` | 63 | Ранний демо Phase 2/3 интеграции | Минимальные imports | Полностью устарел | `git rm -f` (done Jules wave 2026-06-13 task f29c675b) |
| 1.6 | [x] `examples/phase2_3_unified_power_demo.py` | 99 | Объединённый демо Phase 2/3 | Минимальные imports | Полностью устарел | `git rm -f` (done Jules wave 2026-06-13 task f29c675b) |
| 1.7 | [x] `learning/dataset.py` | 37 | Легаси шим: re-export TrajectoryDataset | `learning.trajectory_dataset` | Тривиальный шим, можно убрать (обновить импорты) | `git rm -f` (done Jules wave 2026-06-13 task f29c675b) |
| 1.8 | [x] `learning/trainer_interface.py` | 384 | Абстрактный + DPO trainer interface | `abc`, `dataclasses`, `pathlib` | Вся логика в Rust trainer | `git rm -f` (done Jules wave 2026-06-13 task f29c675b) |

**Верификация после Тир 1:**
```bash
python -c "import agentforge.learning.utils"
agentforge-runner --help | grep flywheel
cargo test --offline --workspace -- --quiet
```

---

## 🏷️ Тир 2 — Клей / Хуки / Parity (хирургические правки)

> **Риск:** Средний. Затрагивает горячие пути (post_process, integration).
> **Откат:** `git checkout <tag> -- <файл>` + `bin/disable_pure_rust_flywheel.sh` + 24ч legacy soak.

| # | Файл | Строк | Назначение | Зависимости | Условие удаления | Действие |
|---|------|-------|-----------|------------|-----------------|----------|
| 2.1 | [x] `DEPRECATED (Tier 2 surgical...` (see prior) | - | ... | ... | Excised in waves + eval-misc-clean slice | Done |
| 2.2 | [x] `eval/post_process.py` (flywheel triggers) | - | Flywheel trigger блоки + run_*_flywheel* | ... | **ХИРУРГИЧЕСКИ excised** (continuous tick etc; PRM/trajectory kept + KEEP FOR VALUE). Eval-misc-clean subagent + 617d051 + handoff 617d051 (APPROVE). | Хирургическая правка done (task-5af0e350) |
| 2.3 | [x] `eval/runner.py` (flywheel refs) | - | Ссылки на flywheel в runner | ... | Mangled text + triggers cleaned in eval slice | Хирургическая правка done |
| 2.4 | [x] `eval/analyze_trajectories.py` (flywheel refs) | - | Анализ траекторий с flywheel-ссылками | ... | Banners cleaned; data value kept | Хирургическая правка done |
| 2.5 | [ ] `phase2_3_integration.py` (flywheel glue) | - | Flywheel glue: run_flywheel*, shadow bridge, parity hooks | ... | Prior waves excised much; remaining Tier2/3 post-soak | Хирургическая правка (see prior handoffs) |
| 2.6 | [x] `learning/flywheel_parity/ (DELETED Tier 2)` | - | ... | ... | Deleted prior | Done |

**Верификация после Тир 2:**
```bash
python -c "import agentforge.learning; print('imports ok')"
python -c "from agentforge.eval import post_process; print('post_process ok')"
agentforge-runner flywheel-step --real-data --ingest --dry-run
bash bin/test_pure_rust_flywheel_step.sh
# Проверить что farm dry-run работает
```

---

## 🏷️ Тир 3 — Ядро оркестрации (максимальная осторожность)

> **Риск:** Высокий. Центральная логика flywheel.
> **Откат:** `bin/disable_pure_rust_flywheel.sh` + `git checkout <tag> -- <файлы>` + `systemctl --user restart agentforge-*` + 24ч legacy soak.

| # | Файл | Строк | Назначение | Зависимости | Условие удаления | Действие |
|---|------|-------|-----------|------------|-----------------|----------|
| 3.1 | [ ] `rust_flywheel_step.py` | 610 | Главный Python flywheel step: загрузка траекторий → Rust bridge → SkillImprover → кандидаты | `learning.skill_improver`, `learning.pending_candidates`, `learning.utils`, `learning.trajectory_dataset` | Полностью заменён `agentforge-runner flywheel-step` (14d bypassed, immediate) | `git rm -f rust_flywheel_step.py` |
| 3.2 | [ ] `bin/run_continuous_flywheel.py` | 556 | Continuous autonomy loop: приоритизация → promote-and-ab → авто-промоут | `learning.pending_candidates`, `learning.evaluator`, `learning.utils` | Полностью заменён `agentforge-runner continuous` (14d bypassed, immediate) | `git rm -f bin/run_continuous_flywheel.py` |
| 3.3 | [ ] `learning/skill_improver.py` | 524 | SkillImprover: генерация предложений из траекторий | `learning.trajectory_dataset`, `learning.utils`, `dataclasses` | Полностью заменён Rust `improver.rs` + `agentforge-runner` (14d bypassed, immediate) | `git rm -f learning/skill_improver.py` |
| 3.4 | [ ] `learning/pending_candidates.py` | 821 | Хранилище кандидатов: ingest/list/promote/prioritize/A/B | `learning.utils`, `hashlib`, `json`, `shutil` | Полностью заменён Rust `candidates` crate (14d bypassed, immediate) | `git rm -f learning/pending_candidates.py` |
| 3.5 | [ ] `learning/evaluator.py` | 480 | LearningEvaluator: A/B тестирование skills | `learning.skill_improver`, `eval.runner`, `learning.utils` | Полностью заменён Rust evaluator + `agentforge-runner` (14d bypassed, immediate) | `git rm -f learning/evaluator.py` |

**Верификация после Тир 3:**
```bash
python -c "import agentforge.learning.utils; print('utils ok')"
agentforge-runner flywheel-step --real-data --ingest
agentforge-runner continuous --top-n 2 --dry-run
agentforge-runner candidate list
cargo test --offline --workspace -- --quiet
# 48ч canary на ферме с pure binary only
```

---

## 🏷️ Тир 4 — Поверхность + Финал (зачистка)

> **Риск:** Средний. Финальная чистка поверхности.
> **Откат:** `git checkout <tag>` + restart.

| # | Файл | Строк | Назначение | Действие |
|---|------|-------|-----------|----------|
| 4.1 | [ ] `learning/__init__.py` | ~70 | Re-exports удалённых символов (SkillImprover, pending_candidates, trainer_interface) | Убрать re-exports удалённых модулей, оставить TrajectoryDataset и utils |
| 4.2 | [ ] `__pycache__/` (все) | — | Кэш Python байткода | `find . -name __pycache__ -exec rm -rf {} +` |
| 4.3 | [ ] `/tmp/agentforge_rust_flywheel/*` | — | Временные файлы flywheel | `rm -rf /tmp/agentforge_rust_flywheel/*` (если пусто) |

---

## 🐚 Shell-скрипты (flywheel-связанные)

> **Стратегия:** Shell-скрипты в `bin/` — это операционные инструменты. Часть из них нужно СОХРАНИТЬ (rollback, audit), часть можно удалить после полного перехода.

### Удалить после soak + Тир 3:

| # | Файл | Строк | Назначение | Действие |
|---|------|-------|-----------|----------|
| S.1 | [ ] `bin/enable_rust_flywheel.sh` | 205 | Активация Rust flywheel (legacy) | `git rm` после полного перехода |
| S.2 | [ ] `bin/disable_rust_flywheel.sh` | 130 | Отключение Rust flywheel (legacy) | `git rm` после полного перехода |
| S.3 | [ ] `bin/run_continuous_flywheel.sh` | 164 | Shell-обёртка для Python continuous | `git rm` (заменён бинарником) |
| S.4 | [ ] `bin/enable_continuous_flywheel.sh` | 325 | Установка continuous cron/timer | Обновить: убрать Python fallback path |
| S.5 | [ ] `bin/test_pure_rust_flywheel_step.sh` | 147 | Тест pure Rust step | СОХРАНИТЬ (полезен для CI) |
| S.6 | [ ] `bin/execute_real_abs_on_promoted.sh` | 138 | Запуск A/B на промоутнутых | Обновить: убрать Python refs |
| S.7 | [ ] `bin/trigger_real_ab_on_farm.sh` | 380 | Триггер A/B на ферме | Обновить: убрать Python fallback |

### СОХРАНИТЬ (операционные инструменты):

| Файл | Строк | Назначение | Почему |
|------|-------|-----------|--------|
| `bin/make_pure_rust_flywheel_default.sh` | 871 | Переключение фермы на pure Rust | Основной инструмент cutover |
| `bin/disable_pure_rust_flywheel.sh` | 713 | Мгновенный откат на Python пути | Критический rollback инструмент |
| `bin/make_antigravity_default.sh` | 463 | Выбор default агента | Не flywheel-специфичный |
| `bin/rust_flywheel_after_task.sh` | 301 | After-task хук (вызывает бинарник) | Обновить: убрать Python fallback, СОХРАНИТЬ Rust path |
| `bin/phase4_pre_removal_audit.sh` | 314 | Аудит перед удалением | СОХРАНИТЬ до завершения Phase 4 |

### Корневые shell-скрипты (не flywheel-специфичные, но содержат refs):

| Файл | Строк | Назначение | Действие |
|------|-------|-----------|----------|
| `dispatcher.sh` | 115 | Диспетчер задач | Хирургически: убрать Python flywheel fallback |
| `watchdog.sh` | 128 | Health watchdog | Хирургически: убрать flywheel-проверки через Python |
| `healthcheck.sh` | 171 | Health check | Хирургически: обновить на Rust binary check |
| `install_services.sh` | 195 | Установщик systemd сервисов | Хирургически: убрать Python service paths |
| `grok_worker.sh` | 354 | Grok worker runner | Хирургически: убрать Python flywheel hook calls (workers-thin slice 2026-06-13: done via subagent bf1f93c; now direct runner delegation + gw; only exec left) |

---

## 📁 Файлы, которые НЕ удаляются (core, out of scope)

> Эти файлы содержат слово «flywheel» но являются частью ядра системы.

| Файл | Причина сохранения |
|------|--------------------|
| `learning/utils.py` | Центральный guard (is_pure_rust_flywheel). Упростить после удаления, но НЕ удалять |
| `learning/trajectory_dataset.py` | Core eval dataset. Flywheel bridge функции — хирургически убрать, ядро оставить |
| `eval/post_process.py` | Core eval. Только хирургические правки (Тир 2) |
| `eval/runner.py` | Core eval benchmark. Только хирургические правки |
| `phase2_3_integration.py` | Core integration. Только хирургические правки (Тир 2) |
| `examples/run_with_planning_and_safety.py` | Planning/safety демо (flywheel refs минимальны) |
| `learning/__init__.py` | Package init. Обновить re-exports (Тир 4) |
| `eval/analyze_trajectories.py` | Core eval. Минимальные хирургические правки |
| `pending_candidates/` (директория данных) | ДАННЫЕ — никогда не удалять. Портабельны, Rust-совместимы |

**Duals converge progress (task-5af0e350, duals-converge subagent 019ec1e8-4e88-7e92-814f-b88fab8bef19 + cad3440/4ff81b8)**: planning/safety/long_horizon/observability converged to thin shims + delegation to Rust (via agentforge-runner full-stack). Callers updated to prefer under pure. Loud CONVERGED banners + guards. Under pure: Rust exclusive in hot paths (phase2_3 etc.). !pure compat kept surgical. Hand off in JULES + commits. (See REMAINING for details; high impact on remaining py surface.)

**Workers thin progress (task-5af0e350, workers-thin subagent 019ec1e8-6770-7e70-8ce8-39ed28fb7d8a + bf1f93c)**: The py workers (grok/antigravity/builder/watchdog) have been aggressively thinned to pure delegation (direct agentforge-runner + gw 9090 in every path; py glue/orch excised). Only agent execution (git/CI/model) remains in py. Sh/services updated. This is "core out of scope for full rm" but now minimal. Hand off/evidence in JULES + commit. (See REMAINING for details.)
**Memory/rag + mcp/scripts progress (task-5af0e350, subagents 019ec1f5-a0ac-7150-9da3-49242c6d7f18 + 019ec1f5-a0ac-7150-9da3-493ed76bef4f, worktrees cm-uncovered-*, handoff 34ce39d)**: Memory_helper/rag_indexer thinned to gw/runner (hdbscan etc. excised surgical; data value via gw). MCP/scripts: mcp/consume/skill_capture thinned (9090, glue removed); 9 0-caller py deleted (scripts/ now 0 .py; safe). 9090 updates. New worktree cm-py-shim-cleanup. % ~89%, uncovered reduced. Handoffs/JULES integrated. Ready for review/consume. Agy dispatched. (See REMAINING.)

---

## 🔄 Мгновенный откат на любом этапе

```bash
# Вариант 1: Быстрый killswitch (менее 60с)
touch /home/eveselove/agentforge/.disable_pure_rust_flywheel
export DISABLE_RUST_FLYWHEEL=1
export AGENTFORGE_FLYWHEEL_ENGINE=python
systemctl --user restart agentforge-*

# Вариант 2: Полный откат через скрипт
bash bin/disable_pure_rust_flywheel.sh

# Вариант 3: Git restore конкретных файлов
git checkout pre-phase4-removal-YYYYMMDD -- file_name

# Вариант 4: Полный git revert
git revert commit-hash
```

---

## 📊 Сводка по объёму удаления

| Категория | Файлов | Строк кода | Тир |
|-----------|--------|-----------|-----|
| Демо / CLI / Шимы | 8 | ~1,335 | 1 |
| Хуки / Parity (полное удаление) | 2 | ~2,146 | 2 |
| Хирургические правки (eval/integration) | 4 | ~300-500 строк удаляется из ~2,151 total | 2 |
| Ядро оркестрации | 5 | ~2,991 | 3 |
| Поверхность + cleanup | 3 | ~70+ | 4 |
| Shell-скрипты (удаление) | 3 | ~499 | Post-3 |
| Shell-скрипты (хирургические правки) | 7 | ~200-300 строк удаляется | Post-2/3 |
| **ИТОГО удаляемого кода** | **~22 файла** | **~7,000-8,000 строк** | 1-4 |

**Update task-5af0e350 scan:** Tier1/2 mostly marked done in prior; quickwins outside flywheel core (shims+refs) done in parallel. Audit run blockers: health string (fixed), release build, unmarked (marked), soak not active in dev. With 10+ worktrees + parallel agents (duals, workers, pure-soak, eval, checkpoints, this uncovered), timeline shortened: full Phase4 rm readiness ~2026-06-20 (vs longer serial). Soak readiness improved (marker, guard, provenance health now "rust-agentforge-runner", 9090 everywhere).

---

## ✅ Порядок выполнения (пошаговый)

1. Убедиться в прохождении всех глобальных пре-условий (чекбоксы выше)
2. [ ] **Тир 1:** Удалить демо/CLI/шимы → верифицировать → коммит
3. [ ] **Тир 2:** Хирургические правки eval/integration + удаление parity → верифицировать → коммит
4. [ ] **Тир 3:** Удалить ядро оркестрации → верифицировать → 48ч canary → коммит
5. [ ] **Shell cleanup:** Удалить/обновить shell-скрипты → верифицировать → коммит
6. [ ] **Тир 4:** Зачистка поверхности (__init__.py, __pycache__, tmp) → финальный коммит
7. [ ] **Victory:** Обновить RUST_FULL_MIGRATION_PLAN.md, VICTORY_SUMMARY.md, 100_PERCENT_READINESS_CHECKLIST.md
8. [ ] **CI gate:** Добавить linter rule: запрет импорта удалённых flywheel модулей

---

## 🔍 Команды аудита (запускать перед каждым тиром)

```bash
cd /home/eveselove/agentforge

# 1. Немаркированные flywheel refs (должно быть пусто или только данные)
find . \( -name "*.py" -o -name "*.sh" \) \
  -not -path "./pending_candidates/*" -not -path "./.git/*" -not -path "./__pycache__/*" | \
  xargs grep -l "flywheel" 2>/dev/null | cat

# 2. Проверка центрального guard (только utils + safe fallback)
grep -rn "def is_pure_rust_flywheel" --include="*.py" . | cat

# 3. Python flywheel callers (должно уменьшаться с каждым тиром)
grep -rnE "python.*-m agentforge.*(rust_flywheel_step|run_continuous_flywheel|list_pending_candidates)" \
  --include="*.sh" --include="*.py" . 2>/dev/null | grep -v ".bak" | cat

# 4. Pure mode verification
python3 -c "
from agentforge.learning.utils import is_pure_rust_flywheel
print('pure:', is_pure_rust_flywheel())
"

# 5. Бинарник smoke test
./rust/target/release/agentforge-runner --help | grep -E 'flywheel|continuous|candidate'

# 6. Полный аудит скриптом
bash bin/phase4_pre_removal_audit.sh
```

---

## 📎 Граф зависимостей (ключевые import-связи)

```
rust_flywheel_step.py
  ├── learning/skill_improver.py (SkillImprover, ProposedSkill)
  ├── learning/pending_candidates.py (ingest, print_summary, cleanup)
  └── learning/utils.py (is_pure_rust_flywheel)

bin/run_continuous_flywheel.py
  ├── learning/pending_candidates.py (list_high_value, promote)
  ├── learning/evaluator.py (LearningEvaluator, ABTestConfig)
  └── learning/utils.py (is_pure_rust_flywheel)

phase2_3_integration.py
  ├── rust_flywheel_demo.py (load_real_farm_data, run_rust_powered_export)
  ├── rust_flywheel_step.py (main as flywheel_main)
  ├── learning/flywheel_parity/ (DELETED Tier 2)parity_harness.py (FlywheelParityHarness)
  └── learning/utils.py (is_pure_rust_flywheel, is_rust_flywheel_disabled)

learning/evaluator.py
  ├── learning/skill_improver.py (SkillImprover)
  └── learning/utils.py (is_pure_rust_flywheel)

learning/__init__.py
  ├── learning/trainer_interface.py (re-exports)
  ├── learning/skill_improver.py (re-exports)
  ├── learning/pending_candidates.py (re-exports)
  └── learning/utils.py (is_pure_rust_flywheel, is_rust_flywheel_disabled)

list_pending_candidates.py
  ├── learning/pending_candidates.py (все функции)
  └── learning/utils.py (is_pure_rust_flywheel)

rust_flywheel_demo.py
  ├── learning/skill_improver.py (SkillImprover)
  └── learning/utils.py (is_pure_rust_flywheel)
```

> **Порядок удаления следует обратному порядку зависимостей:**
> Сначала листья (demo, CLI), затем glue (integration), затем ядро (skill_improver, pending_candidates).

---

> **Критерии успеха Phase 4:**
> - Только `agentforge-runner` производит flywheel-артефакты (engine: rust-*)
> - `is_pure_rust_flywheel() == True` везде на ферме
> - Ноль Python flywheel .py/.sh ссылок в живых execution paths
> - 7+ дней пост-удаления: ферма автономно зелёная (без регрессий)
> - Victory docs обновлены: «Python flywheel orchestration 100% removed — Phase 4 complete»

---

*Создан автоматически: AgentForge Task 15c6e6ad | Antigravity IDE Subagent | 2026-05-31*

---

## Parallel Wave Plan Snippet (from task-5af0e350 coordinator/explorer scan 2026-06-13)

**Context**: task-5af0e350 (accel py-to-rust), ref recent handoffs (JULES f29c675b + dc35fbb/ed73e58e/fc489a6 + ~/.grok/handoffs/*), 10+ existing agent-worktrees (e.g. pure-soak-prep, workers-thin, duals-converge, checkpoints-unify, eval-misc-clean, jules-py-removal-phase4, wave4-services-..., py-rust-5af0e350-task), current audit run + deletes + fixes applied on main + worktree prep.

**Scan findings (fresh count excl eval/tests)**: 42 .py / 33 with defs / 314 defs. Top heavy (but covered): learning/trajectory_dataset 36, core/task_checkpoints 32, planning/planner 30, long_horizon/task_manager 21, memory_helper 17 etc. Uncovered remaining business (focus for next agents):
- scripts/ + bin/ py non-fly (consume-handoff-reviews critical for reviews, migrate_sqlite_to_lance, provenance_audit, apply_limits, create_audit, test_grok)
- mcp_server.py + rust mcp (9090+env done, but full switch / parity)
- memory_helper.py + rag_indexer.py (RAG/failure cluster/llm -- port opp or keep thin)
- phase2_3_integration.py (planning/safety core + flywheel surgical)
- config/settings.py , skill_capture.py , examples/ , fair_queue_grab_test.py (test?), root watchdog.py / __init__ thin
- lance_task_store.py / fix_badges / check_db : deleted (quick win, 0 callers)

**Runner/gw status**: task live FULLY replaces create/reassign/approve etc (live default, see main.rs:236+ for live_* , 455 task match arm; gw has /api/tasks + /review/all + /metrics + Lance). Health provenance fixed to "rust-agentforge-runner". Opportunity: shared client lib in agentforge-core.

**Phase4 audit summary (run this pass)**: 8/10 pass, 2 fail (health --fixed, bin missing), 5 warn (unmarked --markers added to 8+ files; runner paths 25; self-py 10; etc). .pure marker + guard good. Blockers detailed in REMAINING_PYTHON.

**Recommendations for other 4+ agents (parallel)**:
1. Duals (planning/safety/long/obs): converge python <-> rust (more parity, delete thin py wrappers post tests).
2. Workers (grok/antigrav/builder/watchdog): thin to delegates calling `agentforge-runner task ...` + gw http or subprocess; remove direct py logic.
3. Pure-soak: run farm soak, fix remaining health/paths/jq in audit, --emit-commands once gates pass, Tier3 rm (rust_flywheel_step etc), update rollback tools.
4. Eval + checkpoints: surgical on post_process/analyze/runner (flywheel refs), port task_checkpoints + memory_helper + rag to rust or gw extensions; keep harness value.
5. New from this scan (launch more): mcp full rust, memory/rag port (create agentforge-memory crate?), scripts cleanup (delete or consolidate audit tools to bin/), config centralize, phase2_3 non-fly glue, update more docs/CI forbid py imports post rm.
6. Infra: fix audit to jq (no py), unify runner paths in sh, build release in CI, update AGENTS/PHASE/REMAINING ongoing.

**Launch more parallel** (dogfood): 
```
./bin/agent-worktree create py-memory-rag-port-5af0e350
./bin/agent-worktree create scripts-clean-5af0e350
./bin/launch-jules-parallel "port memory_helper + rag to rust" --count 2 --parallel 2
# or at local: cd /tmp/agentforge-work/xxx ; ./bin/install-pre-commit ; ... work ; agent-review
```
ta to monitor agents tmux. Use consume-handoff after.

**Timeline/ % update**: overall ~87% (was ~82%), core 95%+. With aggressive parallel + existing waves: Phase4 Tier3 rm + full py business logic excised target 2026-06-20 (shorten  by 1wk+); soak readiness: gates mostly met in code (need farm time + release). Victory when 0 py flywheel exec in prod + only rust engine + updated victory docs.

**Handoff**: this scan + plan packaged; run agent-review; ref task-5af0e350 + handoff ids in commits/PRs. (See also docs/REVIEW_CHECKLIST.md full self-check done before handoff.)

Next: handoff record created, task queue update via consume or manual.

