# 🔍 FLYWHEEL_PYTHON_AUDIT.md
# Аудит Python-кода, который пишет flywheel manifests / health JSON
# Задача: [Rust-Flywheel-100] a509e1aa
# Дата: 2026-05-31

> **Цель:** Найти ВСЕ оставшиеся Python/shell файлы, которые создают или обновляют
> manifests, flywheel_health.json и связанные JSON-артефакты.
> Требуемое изменение: переход на canonical `rust-agentforge-runner`.

---

## 📊 Сводная таблица

### 1. Файлы, которые ПИШУТ flywheel_health.json

| Файл | Что пишет | Текущая provenance | Требуемое изменение |
|------|-----------|-------------------|---------------------|
| `learning/trajectory_dataset.py:1278` | `FLYWHEEL_HEALTH_FILE.write_text(...)` via `update_rich_export_health()` | Python `trajectory_dataset` (safeguards monitor) | Заменить на вызов `agentforge-runner health update` или удалить, если Rust runner пишет health сам |
| `bin/run_continuous_flywheel.py:495` | `HEALTH_FILE.write_text(json.dumps(health,...))` continuous health snapshot | Python `run_continuous_flywheel` | Удалить: Rust `agentforge-runner continuous` уже пишет health JSON нативно |
| `watchdog.py:356` | `watchdog_flywheel_status.json` watchdog enriched status | Python `watchdog._flywheel_health_report()` | Оставить как READ-ONLY мост (watchdog читает Rust health и дополняет status); либо мигрировать watchdog полностью |

### 2. Файлы, которые ПИШУТ manifest.json / flywheel_manifest.json

| Файл | Что пишет | Текущая provenance | Требуемое изменение |
|------|-----------|-------------------|---------------------|
| `learning/trajectory_dataset.py:826-827` | `(out_dir / "manifest.json").write_text(...)` dataset manifest (DatasetVersion) | Python `TrajectoryDataset.save()` | Заменить: Rust runner должен генерировать dataset manifest при `flywheel-step --ingest` |
| `learning/trainer_interface.py:174` | `(out_dir / "manifest.json").write_text(...)` DPO trainer manifest | Python `DPOTrainer.prepare_data()` | Заменить: Rust runner или `agentforge-runner train prepare` |
| `learning/pending_candidates.py:226-227` | `(dest / "manifest.json").write_text({"legacy": True, ...})` legacy `drop_candidate()` shim | Python legacy `drop_candidate` | Удалить: использовать `ingest_flywheel_artifacts()` + Rust canonical path |
| `learning/pending_candidates.py:127,184` | `flywheel_manifest.json` copy + `candidate_meta.json` write в `ingest_flywheel_artifacts()` | Python `ingest_flywheel_artifacts` (копирует Rust артефакт) | Оставить пока: это мост, копирующий Rust-артефакты. При полной миграции `agentforge-runner candidate ingest` напрямую |
| `phase2_3_integration.py:581` | `(out_dir / "proposal.json").write_text(...)` proposal от `run_rust_flywheel_step()` | Python `run_rust_flywheel_step` | Удалить: proposal уже генерируется Rust runner в `--output-dir` |
| `phase2_3_integration.py:593` | `candidate_path.write_text(yaml.safe_dump(candidate,...))` candidate_skill.yaml | Python `run_rust_flywheel_step` | Удалить: Rust runner генерирует candidate YAML нативно |

### 3. Файлы, которые ПИШУТ shadow fidelity JSON

| Файл | Что пишет | Текущая provenance | Требуемое изменение |
|------|-----------|-------------------|---------------------|
| `phase2_3_integration.py:751-752` | `shadow_fidelity_phase23_*.json` + `shadow_fidelity_latest.json` | Python `_continuous_dual_shadow()` | Оставить на Phase 3 (parity verification). Удалить при Phase 4 removal |
| `learning/flywheel_parity/parity_harness.py:1198` | `shadow_fidelity_latest.json` | Python `FlywheelParityHarness` | Оставить: тестовый harness для проверки parity Rust<>Python |
| `learning/flywheel_parity/parity_harness.py:1281-1285` | Fidelity JSON файлы | Python parity harness | Оставить: тестовая инфраструктура |
| `learning/flywheel_parity/parity_harness.py:1325` | `fixture_meta.json` | Python parity harness (golden fixtures) | Оставить: тестовая инфраструктура |
| `learning/flywheel_parity/parity_harness.py:1419` | Text fidelity report | Python parity harness | Оставить: тестовая инфраструктура |
| `learning/flywheel_parity/parity_harness.py:1721` | `shadow_fidelity_aggregate.json` | Python parity harness | Оставить: тестовая инфраструктура |

### 4. Файлы, которые ПИШУТ candidate/proposal артефакты

| Файл | Что пишет | Текущая provenance | Требуемое изменение |
|------|-----------|-------------------|---------------------|
| `learning/pending_candidates.py:486` | `ab_config.json` A/B test config | Python `promote_and_ab()` | Мигрировать на `agentforge-runner candidate promote --ab` |
| `learning/pending_candidates.py:685,712` | `candidate_meta.json` updates (merge results) | Python `promote_and_ab()` | Мигрировать на `agentforge-runner candidate promote` |
| `learning/pending_candidates.py:744` | A/B result JSON | Python `promote_and_ab()` | Мигрировать на Rust A/B |
| `learning/pending_candidates.py:765` | `promotions.jsonl` log | Python `promote_winner()` | Мигрировать на `agentforge-runner candidate promote` |
| `learning/pending_candidates.py:791` | `skills_index.json` | Python `promote_winner()` | Мигрировать на `agentforge-runner candidate promote --copy-to-skills` |
| `rust_flywheel_demo.py:127` | `/tmp/rust_flywheel_pairs_*.jsonl` | Python demo script | Оставить: это демо, не продакшн |

### 5. Файлы, которые ЧИТАЮТ (не пишут) -- информация

| Файл | Что читает | Статус |
|------|-----------|--------|
| `show_agent_stats.py:136` | Читает `flywheel_health.json` для отображения | OK -- только чтение |
| `watchdog.py:230` | Читает `flywheel_health.json` | OK -- только чтение |
| `eval/post_process.py:326,372,583` | Читает/ссылается на `flywheel_manifest.json`, `flywheel_health.json` | OK -- только чтение + metadata |
| `bin/run_continuous_flywheel.py:323,339` | Читает `flywheel_health.json` для мержа | Удалить при удалении continuous Python |
| `examples/phase2_3_early_demo.py` | Строка в print (инструкция) | OK -- только комментарий |
| `examples/phase2_3_unified_power_demo.py` | Строка в print (инструкция) | OK -- только комментарий |

### 6. Shell-скрипты

| Файл | Роль | Статус |
|------|------|--------|
| `bin/test_pure_rust_flywheel_step.sh` | Тест -- читает health.json для проверки | OK -- тестовая инфраструктура |
| `bin/run_continuous_flywheel.sh` | Обёртка continuous -- ссылается на health | Удалить при удалении Python continuous |
| `bin/disable_pure_rust_flywheel.sh` | Rollback script -- проверяет health | OK -- ops tool |
| `bin/make_pure_rust_flywheel_default.sh` | Cutover script -- проверяет manifests | OK -- ops tool |
| `bin/make_antigravity_default.sh` | Проверяет health/status JSON | OK -- ops tool |

### 7. planlytasksko/scripts/

| Файл | Что нашлось | Статус |
|------|------------|--------|
| `scripts/optimize_prompts.py:610` | Слово "manifested" в строке -- НЕ flywheel manifest | False positive -- не относится |

---

## 🎯 Приоритеты миграции

### 🔴 CRITICAL -- Удалить/заменить немедленно (пишут то же, что Rust runner)
1. **`bin/run_continuous_flywheel.py`** -- `HEALTH_FILE.write_text(...)` -> Rust `continuous` пишет health
2. **`phase2_3_integration.py`** -- `proposal.json` + `candidate_skill.yaml` -> Rust `flywheel-step` пишет оба
3. **`learning/pending_candidates.py:drop_candidate()`** -- legacy shim, пишет `manifest.json` -> удалить

### 🟡 HIGH -- Мигрировать при Phase 4
4. **`learning/trajectory_dataset.py:update_rich_export_health()`** -- health write -> Rust health subsystem
5. **`learning/trajectory_dataset.py:save()`** -- dataset manifest -> Rust dataset export
6. **`learning/trainer_interface.py`** -- trainer manifest -> Rust trainer
7. **`learning/pending_candidates.py`** -- A/B config, results, promotions -> `agentforge-runner candidate`

### 🟢 LOW -- Оставить (тестовая / ops инфраструктура)
8. **`learning/flywheel_parity/parity_harness.py`** -- fidelity JSON (тестовый harness, нужен для parity)
9. **`watchdog.py`** -- `watchdog_flywheel_status.json` (мост: читает Rust + дополняет)
10. **`show_agent_stats.py`** -- только чтение
11. **Shell ops scripts** -- только чтение/проверка
12. **`rust_flywheel_demo.py`** -- демо, пишет temp JSONL

---

## 📋 Canonical Provenance String

Все артефакты после миграции должны содержать:
```json
{
  "engine": "rust-agentforge-runner",
  "provenance": "agentforge-runner v<VERSION>"
}
```

Текущие Python файлы используют разные строки provenance:
- `"generated_by": "run_rust_flywheel_step"` (phase2_3_integration.py)
- `"legacy": True` (pending_candidates.py drop_candidate)
- `"source_dataset": "..."` (trainer_interface.py)
- Без provenance (trajectory_dataset.py save)
- `"source": "phase2_3_continuous_dual"` (shadow fidelity)

**Все должны быть заменены на canonical `"engine": "rust-agentforge-runner"`.**

---

## Итог

- **Всего Python файлов с записью flywheel артефактов:** 7
- **Из них CRITICAL (дублируют Rust):** 3
- **HIGH (мигрировать при Phase 4):** 4
- **LOW (оставить -- тесты/ops):** 5
- **False positives (planlytasksko):** 1
- **Shell скрипты (только чтение/ops):** 5

Аудит завершён. Следующий шаг: удаление CRITICAL Python writers + добавление `engine` provenance проверки.
