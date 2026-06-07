# Rust Flywheel — 100% Completion Sprint (2026-06)

**Фокус:** Довести Pure Rust Flywheel оркестрацию до 100%, отдельно от более широкой миграции (Task System и т.д.).

**Последнее обновление:** 2026-05-31 13:54 MSK (автоматический аудит AgentForge)

---

## Текущий статус (объективные факты)

| Компонент | Статус | Детали |
|-----------|--------|--------|
| **Бинарник** | ✅ Готов | gentforge-runner release 1.41 MB, собран 2026-05-31 10:21 |
| **Debug-бинарник** | ✅ Готов | 9.9 MB, собран 2026-05-31 10:26 |
| **Rust workspace** | ✅ 9 crates | core, safety, planning, observability, learning, runner, long-horizon, flywheel, candidates |
| **Systemd-сервисы** | ✅ 6 active | api, grok, jules, watchdog, worker, flywheel.timer |
| **Pure Rust маркер** | ✅ Активен | .pure_rust_flywheel создан 2026-05-31 10:52 |
| **Cutover скрипт** | ✅ Выполнен | in/make_pure_rust_flywheel_default.sh |
| **Rollback** | ✅ Готов | in/disable_pure_rust_flywheel.sh |
| **Кандидаты** | ✅ 257 шт | в pending_candidates/ |
| **Phase 4 аудит** | ✅ Готов | in/phase4_pre_removal_audit.sh (read-only, safe) |
| **14d Soak** | ⏳ 0/14 дней | Маркер создан только сегодня! |
| **Fidelity gate** | ❌ FAIL | avg_composite=0.3588, pass_rate=0%, 2 samples |
| **Health JSON** | ⚠️ dry_run=true | phase=2-prep, shadow mode, НЕ full autonomy |
| **Provenance** | ⚠️ Частично | Новые flywheel_manifest.json имеют engine=rust, старые manifest.json — нет |
| **Rich export** | ⚠️ 75% ошибок | error_rate=0.75, 8 attempts, 2 success |
| **Python fallbacks** | ⚠️ Остаются | bin/rust_flywheel_after_task.sh содержит python -m вызовы |
| **Cargo в PATH** | ❌ Нет | cargo недоступен через SSH (нужно source ~/.cargo/env) |
| **flywheel_health.json** | ⚠️ Только в /tmp | /tmp/agentforge_rust_flywheel/flywheel_health.json, не в корне проекта |

---

## Definition of Done (Rust Flywheel 100%)

- [ ] **14d zero-regression soak** — зелёный результат, ноль Python flywheel fallbacks, консистентная rust-provenance. **СТАТУС: 0/14 дней, только начался**
- [ ] **Fidelity gate** пройден (или задокументировано исключение с планом). **СТАТУС: FAIL, avg=0.36, 0% pass rate**
- [ ] **100% артефактов** (манифесты, health JSON, promotions) содержат engine:  rust-agentforge-runner. **СТАТУС: новые — да, старые — нет**
- [ ] **Phase 4 removal checklist** для Python flywheel кода выполнен. **СТАТУС: аудит готов, execution gated on soak**
- [ ] **Мониторинг** ([SOAK-MONITOR], fidelity, provenance checks) автоматизирован и надёжен. **СТАТУС: watchdog работает, но rich_export 75% ошибок**
- [ ] **Continuous** может работать в real mode безопасно. **СТАТУС: dry_run=true, shadow only**
- [ ] **Финальная документация** что Rust Flywheel 100% завершён. **СТАТУС: не готово**

---

## Оставшиеся пробелы (GAPS)

### 🔴 Критические (блокируют 100%)

1. **Soak 0/14 дней** — маркер .pure_rust_flywheel создан только сегодня (10:52). Нужно 14 дней безрегрессионной работы.
2. **Fidelity FAIL** — composite score 0.3588, pass_rate 0%. Только 2 sample. Нужно:
   - Понять почему composite так низкий (ожидается >0.9)
   - Набрать больше samples (минимум 10-20)
   - Либо задокументировать исключение с планом исправления
3. **Continuous в dry_run** — health.json показывает dry_run: true, phase: 2-prep. Для полной миграции нужен real mode.

### 🟡 Важные (влияют на качество)

4. **Rich export error rate 75%** — watchdog показывает 6 из 8 попыток неудачны. Нужно разобраться в причинах.
5. **Python fallbacks в shell-скриптах** — in/rust_flywheel_after_task.sh всё ещё вызывает python -m agentforge.rust_flywheel_step и python -m agentforge.learning.flywheel_parity.parity_harness. Нужно:
   - Либо удалить (Phase 4)
   - Либо убедиться что guard is_pure_rust_flywheel() блокирует выполнение
6. **Provenance в старых manifest.json** — директории формата 20260531_054548/manifest.json (без _general-refactor_ суффикса) не имеют engine поля. Нужно backfill или задокументировать.
7. **Cargo не в PATH через SSH** — невозможно запустить cargo test / cargo clippy удалённо без source ~/.cargo/env. Нужно добавить в .bashrc.

### 🟢 Минорные (документация/cleanup)

8. **Jules сервис активен**, хотя Jules отключён — gentforge-jules.service loaded+active, при этом Jules офлайн.
9. **Health JSON только в /tmp** — рискует потеряться при перезагрузке. Нужна копия или симлинк в проекте.
10. **Два дублирующих worker-сервиса** — gentforge-grok.service и gentforge-worker.service оба описаны как Grok Worker.

---

## Параллельные треки

1. **Provenance & Monitoring Hardening** (grok-heavy) — ⚠️ rich export 75% ошибок
2. **14d Soak & Fidelity Execution** (grok + субагенты) — ⏳ День 0 из 14
3. **Phase 4 Prep for Flywheel Python** (аудит готов) — ⏳ Gated on soak
4. **Continuous & Ops Polish** (grok) — ⚠️ dry_run mode

---

## Следующие действия (Next Actions)

### Немедленные (сегодня)

1. **[P0] Исправить fidelity scoring** — разобраться почему composite=0.36 при ожидаемом >0.9. Проверить shadow_fidelity_latest.json на предмет ошибок в метриках.
2. **[P0] Переключить continuous в real mode** — выключить dry_run, перевести из phase: 2-prep в production. Без этого soak бессмыслен.
3. **[P1] Исправить rich export errors** — 75% error rate убивает надёжность. Проверить логи watchdog.
4. **[P1] Добавить cargo в PATH** — echo 'source C:\Users\Evese/.cargo/env' >> ~/.bashrc для удалённого CI.

### На этой неделе

5. **[P1] Настроить автоматический soak мониторинг** — cron-job который каждые 4 часа проверяет:
   - Новые манифесты имеют engine=rust
   - Нет Python fallback в логах
   - Fidelity trend растёт
   - Health JSON обновляется
6. **[P2] Backfill provenance** в старых manifest.json или задокументировать что они pre-cutover.
7. **[P2] Остановить jules service** — systemctl --user stop agentforge-jules.service && systemctl --user disable agentforge-jules.service

### После soak (14 дней)

8. **[P1] Phase 4 removal execution** — запустить in/phase4_pre_removal_audit.sh --emit-commands, ревью, выполнить tier-by-tier.
9. **[P0] Финальная документация** — обновить все docs, написать victory announcement.
10. **[P0] Cargo test + clippy green** — финальная проверка перед объявлением 100%.

---

## Хронология

| Дата | Событие |
|------|---------|
| 2026-05-31 10:21 | Release бинарник собран (1.41 MB) |
| 2026-05-31 10:42 | Cutover выполнен (make_pure_rust_flywheel_default.sh) |
| 2026-05-31 10:52 | Soak маркер .pure_rust_flywheel создан |
| 2026-05-31 13:54 | Первый объективный аудит статуса (этот документ) |
| ~2026-06-14 | Целевая дата окончания 14d soak |
| ~2026-06-15 | Phase 4 removal (если soak зелёный) |
| ~2026-06-16 | 100% Announcement |

---

## Ключевые файлы

- **Бинарник**: /home/eveselove/agentforge/rust/target/release/agentforge-runner
- **Health**: /tmp/agentforge_rust_flywheel/flywheel_health.json
- **Fidelity**: /tmp/agentforge_rust_flywheel/shadow_fidelity_aggregate.json
- **Watchdog**: /tmp/agentforge_rust_flywheel/watchdog_flywheel_status.json
- **Soak маркер**: /home/eveselove/agentforge/.pure_rust_flywheel
- **Cutover**: in/make_pure_rust_flywheel_default.sh
- **Rollback**: in/disable_pure_rust_flywheel.sh
- **Phase 4 аудит**: in/phase4_pre_removal_audit.sh
- **Readiness checklist**: 100_PERCENT_READINESS_CHECKLIST.md
- **Phase 4 plan**: PHASE4_REMOVAL_PLAN.md

---

**Важное замечание**: Jules полностью отключён. Весь sprint работает через Grok + Antigravity субагенты.

**Общий прогресс: ~75%** (инфраструктура готова, но soak/fidelity/continuous — ключевые блокеры).
