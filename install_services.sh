#!/bin/bash
# !!! AGGRESSIVE FINAL DEPRECATION SWEEP (RUST_FULL_MIGRATION_PLAN.md + PHASE4_REMOVAL_PLAN.md) !!!
# install_services.sh : installs flywheel-related services (agentforge-flywheel.service .timer, watchdog, workers).
# Services now point to / prefer agentforge-runner for flywheel orchestration (pure default).
# Python orchestration (flywheel timer bits, watchdog.py flywheel sections) deprecated Phase 4 Tier 4.
# See PHASE4_REMOVAL_PLAN.md + make_pure/disable scripts (they patch these units).
# ============================================
# Установка systemd сервисов AgentForge
# Делает систему полностью автономной от ноутбука
# Запуск: bash ~/agentforge/install_services.sh
# ============================================

set -e

AGENTFORGE_DIR="/home/eveselove/agentforge"

echo "🔧 Установка systemd сервисов AgentForge..."

# Останавливаем старые процессы
pkill -f grok_worker.sh 2>/dev/null || true
pkill -f "uvicorn task_queue" 2>/dev/null || true
pkill -f "agentforge-gateway" 2>/dev/null || true
sleep 2

# Копируем юниты (Phase 4: gateway primary)
sudo cp "$AGENTFORGE_DIR/agentforge-gateway.service" /etc/systemd/system/ || true
sudo cp "$AGENTFORGE_DIR/agentforge-worker.service" /etc/systemd/system/
# legacy api (rollback only)
sudo cp "$AGENTFORGE_DIR/agentforge-api.service" /etc/systemd/system/ 2>/dev/null || true

# Перезагружаем systemd
sudo systemctl daemon-reload

# Активируем автозапуск (gateway primary)
sudo systemctl enable agentforge-gateway || true
sudo systemctl enable agentforge-worker
sudo systemctl enable agentforge-api 2>/dev/null || true

# Запускаем
sudo systemctl start agentforge-api
sleep 3
sudo systemctl start agentforge-worker

# Проверяем статус
echo ""
echo "📊 Статус сервисов:"
sudo systemctl status agentforge-api --no-pager -l | head -10
echo "---"
sudo systemctl status agentforge-worker --no-pager -l | head -10

# Убираем дубликаты из crontab (они теперь в systemd)
echo ""
echo "🧹 Чистка crontab от дублей..."
crontab -l 2>/dev/null | grep -v '@reboot.*grok_worker' | grep -v '@reboot.*start.sh' | crontab -

# === Интеграция оптимизации Cargo config (подзадача 4dc58362: jobs=12 + облегчённые debug-символы) ===
# Обеспечиваем оптимальный ~/.cargo/config.toml при каждой переустановке сервисов.
# Критично для быстрых Rust-сборок в задачах AgentForge (grok_runner, rust-fix и др.).
echo ""
echo "🦀 Подготовка Cargo config (jobs=12, line-tables-only debug)..."
if [[ -x "$AGENTFORGE_DIR/scripts/ensure_cargo_optimization.sh" ]]; then
    bash "$AGENTFORGE_DIR/scripts/ensure_cargo_optimization.sh" || echo "⚠️  ensure_cargo_optimization.sh завершился с предупреждением (не критично)"
else
    echo "⚠️  Скрипт ensure_cargo_optimization.sh не найден — пропускаем (установите вручную позже)."
fi

# === Интеграция Rust DevTools (подзадача 4dc58362: cargo-binstall + cargo-machete) ===
# Обеспечиваем наличие современных Rust-инструментов при каждой переустановке сервисов.
# cargo-binstall ускоряет установку утилит, cargo-machete — анализ зависимостей.
echo ""
echo "🦀 Подготовка Rust DevTools (cargo-binstall, cargo-machete)..."
if [[ -x "$AGENTFORGE_DIR/scripts/ensure_rust_devtools.sh" ]]; then
    bash "$AGENTFORGE_DIR/scripts/ensure_rust_devtools.sh" || echo "⚠️  ensure_rust_devtools.sh завершился с предупреждением (не критично)"
else
    echo "⚠️  Скрипт ensure_rust_devtools.sh не найден — пропускаем (установите вручную позже)."
fi

# === Интеграция mold (подзадача 4dc58362: копирование mold в ~/.cargo/bin + права) ===
# Обеспечиваем быстрый линкер при каждой переустановке сервисов.
# mold ускоряет линковку Rust-крейтов в 2-5x (критично для planly_gateway и тяжёлых зависимостей).
echo ""
echo "🔗 Подготовка mold (быстрый линкер для cargo)..."
if [[ -x "$AGENTFORGE_DIR/scripts/ensure_mold.sh" ]]; then
    bash "$AGENTFORGE_DIR/scripts/ensure_mold.sh" || echo "⚠️  ensure_mold.sh завершился с предупреждением (сборки будут работать, но линковка медленнее)"
else
    echo "⚠️  Скрипт ensure_mold.sh не найден — пропускаем (установите вручную позже)."
fi

echo ""
echo "✅ Готово! AgentForge теперь полностью автономен:"
echo "   • API запускается при загрузке Erbox"
echo "   • Grok Worker запускается после API (основной исполнитель)"
echo "   • При падении — автоматический перезапуск"
echo "   • Watchdog каждые 5 минут эскалирует зависшие задачи"
echo "   • Ноутбук можно закрывать — Erbox работает 24/7"
echo ""
echo "Команды управления:"
echo "   sudo systemctl status agentforge-api"
echo "   sudo systemctl status agentforge-worker"
echo "   sudo systemctl restart agentforge-worker"
echo "   journalctl -u agentforge-worker -f   # live логи"
echo ""
echo "После рефакторинга routing (2026-06):"
echo "   • Большинство задач теперь идёт на Grok автоматически"
echo "   • Antigravity получает только явно предназначенные задачи"
echo "   • Используй: agentforge-runner task reassign --from antigravity --to grok --dry-run  (or equivalent; old py deleted in Jules wave 2026-06-13 task f29c675b)"

# ============================================
# AUTONOMY TIMER PRODUCTION ROLLOUT (2026-05-31)
# Installs agentforge-flywheel.timer + .service for 24/7 continuous flywheel.
# Non-breaking: reuses ENABLE_RUST_FLYWHEEL + all existing rust_flywheel.env / enable patterns exactly.
# Units get header comments for traceability. Timer: 20min OnCalendar + Persistent + RandomizedDelaySec=90.
# For user-mode setups (no sudo): prefer bin/enable_continuous_flywheel.sh --user instead.
# This ensures *new workers* (re-run install) get the timer automatically.
# ============================================
echo ""
echo "🌀 Установка Continuous Flywheel Timer (Autonomy 24/7)..."
FLYWHEEL_SRC="$AGENTFORGE_DIR/agentforge-flywheel.service"
FLYWHEEL_TIMER_SRC="$AGENTFORGE_DIR/agentforge-flywheel.timer"
if [ -f "$FLYWHEEL_SRC" ] && [ -f "$FLYWHEEL_TIMER_SRC" ]; then
    # System install (matches other units in this script)
    sudo cp "$FLYWHEEL_SRC" /etc/systemd/system/
    sudo cp "$FLYWHEEL_TIMER_SRC" /etc/systemd/system/

    # Inject production rollout header comments (traceable, non-destructive)
    for UNIT in /etc/systemd/system/agentforge-flywheel.service /etc/systemd/system/agentforge-flywheel.timer; do
        if [ -f "$UNIT" ]; then
            sudo sh -c "cat > /tmp/flywheel_unit_header.tmp << 'HDR'
# ============================================================
# Installed by install_services.sh (Autonomy Timer Production Rolled Out 2026-05-31)
# Master: $AGENTFORGE_DIR/$(basename $UNIT)
# Purpose: 24/7 continuous flywheel closer (prioritize + promote-and-ab + winner detect)
# Full reuse: ENABLE_RUST_FLYWHEEL marker + bin/run_continuous_flywheel.{sh,py} + env guards.
# Timer cadence: 20min (Persistent=true, RandomizedDelaySec=90, OnBootSec=3min)
# Safe: service defaults to dry-run. See bin/enable_continuous_flywheel.sh and CONTINUOUS_FLYWHEEL.md
# Rollback: sudo systemctl disable --now agentforge-flywheel.timer ; sudo rm $UNIT
# ============================================================
HDR
cat /tmp/flywheel_unit_header.tmp $UNIT | sudo tee $UNIT >/dev/null
rm -f /tmp/flywheel_unit_header.tmp
"
        fi
    done

    sudo systemctl daemon-reload
    sudo systemctl enable --now agentforge-flywheel.timer 2>/dev/null || echo "  (timer enable non-fatal; may already be in user mode)"

    echo "  ✅ Flywheel timer units copied + enabled (system)"
    echo "     (For mixed user setups run also: bash $AGENTFORGE_DIR/bin/enable_continuous_flywheel.sh --user )"
else
    echo "  ⚠️  Flywheel units not found in $AGENTFORGE_DIR — skipped (run enable_continuous script manually)"
fi

# ============================================
# 2026-06: RUST FLYWHEEL NOW DEFAULT FOR ANTIGRAVITY — ROLLOUT NOTES
# ============================================
echo ""
echo "🦀 Rust Flywheel Default Rollout (Antigravity + Farm) — 2026-06"
echo "   The production self-improving Rust flywheel is ON BY DEFAULT."
echo "   • No ENABLE_RUST_FLYWHEEL marker or extra env required for normal operation."
echo "   • Antigravity (agy) dispatches + all post_process paths now feed rich Rust trajectories automatically."
echo "   • Only disable: export DISABLE_RUST_FLYWHEEL=1 (strong global kill-switch, honored everywhere)."
echo ""
echo "   Recommended systemd Environment for fresh installs (prefers fast release binary):"
echo "     Environment=AGENTFORGE_RUST_FLYWHEEL=1"
echo "     Environment=AGENTFORGE_USE_RUST=1"
echo "     Environment=AGENTFORGE_RUST_RUNNER=/home/eveselove/agentforge/rust/target/release/agentforge-runner"
echo "     # To opt out entirely for this unit: Environment=DISABLE_RUST_FLYWHEEL=1"
echo ""
echo "   Full story + disable instructions + 'What this means for Antigravity tasks' blurb:"
echo "     cat $AGENTFORGE_DIR/ANTIGRAVITY_DEFAULT.md"
echo "   Ops commands: cat $AGENTFORGE_DIR/ENABLE_RUST_FLYWHEEL.md"
echo "   New symmetric disable helper: bash $AGENTFORGE_DIR/bin/disable_rust_flywheel.sh"
echo ""
echo "   This install already wires the continuous timer that drives the meta autonomy loop."
echo "   Watch live candidates: agentforge-runner candidate list --top 5 --sort value --json  (old py deleted in Jules wave 2026-06-13 task f29c675b)"
echo "================================================"

# === PURE RUST FLYWHEEL DEFAULT (injected by make_pure_rust_flywheel_default.sh @ 2026-05-31T10:42:02+03:00) ===
# Pure Rust cutover (production excellence): when .pure_rust_flywheel or AGENTFORGE_PURE_RUST_FLYWHEEL=1 or FLYWHEEL_ENGINE=rust,
# force sole use of agentforge-runner binary for ALL flywheel/candidate/continuous orchestration.
# Complements env snippet + unit patches. Idempotent + guarded. Ultimate killswitch: DISABLE_RUST_FLYWHEEL=1.
PURE_MARKER="/home/eveselove/agentforge/.pure_rust_flywheel"
if [[ -f "$PURE_MARKER" ]] || [[ "${AGENTFORGE_PURE_RUST_FLYWHEEL:-0}" = "1" ]] || [[ "${AGENTFORGE_FLYWHEEL_ENGINE:-}" = "rust" ]]; then
    export AGENTFORGE_PURE_RUST_FLYWHEEL=1
    export AGENTFORGE_FLYWHEEL_ENGINE=rust
    if [ -x "/home/eveselove/agentforge/rust/target/release/agentforge-runner" ]; then
        export AGENTFORGE_RUST_RUNNER="/home/eveselove/agentforge/rust/target/release/agentforge-runner"
    fi
    export AGENTFORGE_FLYWHEEL_PROVENANCE="rust-agentforge-runner"
    # shellcheck disable=SC1091
    [ -f "/home/eveselove/agentforge/bin/rust_flywheel.env" ] && source "/home/eveselove/agentforge/bin/rust_flywheel.env" 2>/dev/null || true
fi
# End pure section — DISABLE_RUST_FLYWHEEL remains ultimate global off-switch everywhere.
