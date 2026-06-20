#!/bin/bash
# Установка systemd сервисов для Grok XAI Cloud Workers
#
# Аудит 2026-06-13 (SWARM): fixes for portability (no hardcoded paths),
# data races (flock serialize), logical errors (missing checks, no verify,
# weak set -e), silent fails on .env/units, missing logs prep, no backup.
# Matches robustness of bin/launch_cloud_workers.sh + install-pre-commit.
# Strict: only this file edited. Lightning changes for swarm scale.
#
# Usage:
#   ./bin/install_grok_xai_workers.sh          # install units only
#   ./bin/install_grok_xai_workers.sh 3        # install + enable 3 instances @1..3
#   ./bin/install_grok_xai_workers.sh --help

set -euo pipefail

# === PORTABILITY: derive from script location (fixes all /home/eveselove hardcodes;
# supports worktrees /tmp/agentforge/* , other users, Jetson/GMK etc per AGENTS.md)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENTFORGE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_XAI="$AGENTFORGE_DIR/.env.xai"
ENV_EXAMPLE="$AGENTFORGE_DIR/.env.xai.example"
UNIT_DIR="$AGENTFORGE_DIR/systemd"
LOG_DIR="$AGENTFORGE_DIR/logs"
LOCK_FILE="$LOG_DIR/.install_grok_xai_workers.lock"

echo "=== Установка Grok XAI Workers (AGENTFORGE_DIR=$AGENTFORGE_DIR) ==="

# === DATA RACE PROTECTION: serialize concurrent installs (cp + daemon-reload race
# can leave inconsistent units or missed reloads when swarm of agents run this in parallel).
mkdir -p "$LOG_DIR" 2>/dev/null || true
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    echo "❌ Другой экземпляр install_grok_xai_workers.sh уже работает (lock: $LOCK_FILE)."
    echo "   Дождитесь или убейте предыдущий процесс."
    exit 1
fi
# flock releases on exit (no reentrancy since top-level)

# === .env handling (logical error: cp could fail if example missing; no key validation)
if [ ! -f "$ENV_XAI" ]; then
    if [ ! -f "$ENV_EXAMPLE" ]; then
        echo "❌ $ENV_EXAMPLE не найден — не могу создать $ENV_XAI"
        exit 1
    fi
    echo "Создаю .env.xai из примера..."
    cp "$ENV_EXAMPLE" "$ENV_XAI"
    echo "!!! Отредактируй $ENV_XAI и вставь туда свой XAI_API_KEY !!!"
    exit 1
fi

# Validate key looks present (prevents later silent XAI failures in workers)
if ! grep -q '^XAI_API_KEY=' "$ENV_XAI" 2>/dev/null || \
   grep -Eq '^XAI_API_KEY=[[:space:]]*$' "$ENV_XAI" || \
   grep -qi 'ВСТАВЬ' "$ENV_XAI"; then
    echo "❌ XAI_API_KEY не найден/пуст/плейсхолдер в $ENV_XAI"
    echo "   Отредактируй и перезапусти скрипт."
    exit 1
fi

echo "Копирую unit-файлы (с бэкапами если нужно)..."

# Pre-check sources (logical error: previous cp would fail late/ugly if units missing after partial clone)
for unit in grok-xai-worker.service grok-xai-worker@.service; do
    src="$UNIT_DIR/$unit"
    if [ ! -f "$src" ]; then
        echo "❌ Source unit не найден: $src"
        exit 1
    fi
done

# Backup + copy (idempotent-safe; matches install-pre-commit pattern)
for unit in grok-xai-worker.service grok-xai-worker@.service; do
    src="$UNIT_DIR/$unit"
    dst="/etc/systemd/system/$unit"
    if [ -f "$dst" ]; then
        BACKUP="${dst}.bak.$(date +%Y%m%d_%H%M%S)"
        sudo cp "$dst" "$BACKUP" || true
        echo "📦 Backed up existing $unit → $BACKUP"
    fi
    sudo cp "$src" "$dst"
done

# Prep logs dir (prevents potential start race/failure for append: logs in units;
# worker mkdirs too but install-time is better for systemd)
sudo mkdir -p "$LOG_DIR"
if id agx >/dev/null 2>&1; then
    sudo chown -R agx:agx "$LOG_DIR" 2>/dev/null || true
else
    echo "⚠️  Пользователь 'agx' не найден (User=agx в units). Сервисы могут не запуститься."
    echo "   Для user-mode: используй systemctl --user + strip User= (см. enable_continuous_flywheel.sh)"
fi

echo "Перезагружаю systemd..."
if ! sudo systemctl daemon-reload; then
    echo "❌ daemon-reload failed"
    exit 1
fi

# Post-install verification (catches logical misconfig early)
echo "Верификация units..."
if ! systemctl list-unit-files --no-legend | grep -q 'grok-xai-worker'; then
    echo "⚠️  Units не появились в list-unit-files (возможно нужно перелогиниться или проверить sudo)"
fi
sudo systemctl cat grok-xai-worker@.service > /dev/null 2>&1 || echo "⚠️  systemctl cat для template не сработал (non-fatal)"

echo ""
echo "✅ Готово!"

# Optional auto-enable for swarm (lightning fast setup of N parallel @instances)
COUNT="${1:-0}"
if [[ "$COUNT" =~ ^[1-9][0-9]*$ ]]; then
    echo "🚀 Авто-активация $COUNT инстансов grok-xai-worker@{1..$COUNT} ..."
    for i in $(seq 1 "$COUNT"); do
        sudo systemctl enable --now "grok-xai-worker@$i" || echo "   (warn: enable $i failed, non-fatal)"
    done
    echo ""
    echo "Статус:"
    # shellcheck disable=SC2086
    sudo systemctl --no-pager status "grok-xai-worker@1-$COUNT" 2>/dev/null | head -20 || \
        sudo systemctl list-units --no-legend 'grok-xai-worker@*' | cat
else
    echo ""
    echo "Примеры команд:"
    echo "  sudo systemctl enable --now grok-xai-worker          # один инстанс"
    echo "  sudo systemctl enable --now grok-xai-worker@1        # инстанс 1"
    echo "  sudo systemctl enable --now grok-xai-worker@2        # инстанс 2"
    echo "  sudo systemctl status grok-xai-worker@1"
    echo "  journalctl -u grok-xai-worker@1 -f"
    echo ""
    echo "Чтобы запустить 3 параллельных облачных агента:"
    echo "  sudo systemctl enable --now grok-xai-worker@{1..3}"
    echo ""
    echo "Или одной командой после установки: $0 3"
fi

echo ""
echo "Для multi-key (разные .env): см. docs/XAI_MULTI_KEY_GUIDE.md (overrides в .service.d/)"
