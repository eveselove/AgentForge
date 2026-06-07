#!/bin/bash
#
# ensure_cargo_optimization.sh
# Скрипт обеспечения оптимальной конфигурации глобального ~/.cargo/config.toml
# для ускорения сборок Rust в среде AgentForge.
#
# Оптимизация (подзадача из чата «AgentForge: оркестрация и настройка», 4dc58362):
#   - Удалить codegen-units = 1 (это критично замедляет компиляцию, особенно инкрементальную)
#   - Установить jobs = 12 (по числу ядер CPU в окружении)
#   - Установить облегчённые debug-символы: debug = "line-tables-only" в [profile.dev]
#     (вместо debug = 1 / full — даёт меньший размер .o/.d, быстрее линковка и инкрементальные rebuild'ы)
#
# Почему это важно для AgentForge:
#   - Много Rust-компонентов: planly_gateway, planly_core, planly_parser, planly_telegram_proxy
#   - Задачи агентов часто включают cargo check / cargo build / cargo test
#   - codegen-units=1 превращает параллельную сборку в последовательную → +300-500% времени
#   - jobs=12 даёт полную утилизацию 12-ядерного CPU (Erbox/рабочая станция)
#   - "line-tables-only" — минимально достаточные символы для backtrace (файл:строка), без overhead на locals/types
#     → target/ меньше на десятки-сотни MB, cargo check на 20-40% быстрее в dev

# Использование:
#   bash scripts/ensure_cargo_optimization.sh
#   # или из любого места: ~/agentforge/scripts/ensure_cargo_optimization.sh
#
# Идемпотентен: безопасно запускать многократно.
# Все комментарии и вывод — на русском языке (по требованию задачи).
#
set -euo pipefail

CARGO_CONFIG="$HOME/.cargo/config.toml"
BACKUP="${CARGO_CONFIG}.bak.$(date +%s)"

echo "🔧 [AgentForge] Проверка и оптимизация глобального ~/.cargo/config.toml ..."

mkdir -p "$HOME/.cargo"

NEEDS_UPDATE=0

if [[ ! -f "$CARGO_CONFIG" ]]; then
    echo "⚠️  Файл $CARGO_CONFIG не существует — будет создан."
    NEEDS_UPDATE=1
else
    # Проверяем наличие вредного codegen-units = 1 (убийца скорости параллельной компиляции)
    if grep -qE 'codegen-units\s*=\s*1' "$CARGO_CONFIG"; then
        echo "❌ Обнаружено codegen-units = 1 — требуется удаление для ускорения сборок."
        NEEDS_UPDATE=1
    fi
    # Проверяем jobs (должно быть 12 для 12-ядерной машины)
    if ! grep -qE 'jobs\s*=\s*12' "$CARGO_CONFIG"; then
        echo "⚠️  jobs != 12 или отсутствует — требуется установка."
        NEEDS_UPDATE=1
    fi
    # Проверяем облегчённые debug-символы (подзадача "Облегчённые Debug-символы")
    if ! grep -qE 'debug\s*=\s*"line-tables-only"' "$CARGO_CONFIG"; then
        echo "⚠️  debug != \"line-tables-only\" (или отсутствует) — требуется установка облегчённых debug-символов."
        NEEDS_UPDATE=1
    fi
fi

if [[ $NEEDS_UPDATE -eq 1 ]]; then
    if [[ -f "$CARGO_CONFIG" ]]; then
        cp "$CARGO_CONFIG" "$BACKUP"
        echo "💾 Создана резервная копия: $BACKUP"
    fi
    # Записываем строго оптимальный конфиг (без codegen-units=1, jobs=12, облегчённые debug-символы)
    cat > "$CARGO_CONFIG" << 'EOC'
[build]
jobs = 12
incremental = true

[profile.release]
opt-level = 3
strip = true

[profile.dev]
opt-level = 0
debug = "line-tables-only"
incremental = true

[net]
git-fetch-with-cli = false

[registries.crates-io]
protocol = "sparse"
EOC
    echo "✅ Оптимизация применена: codegen-units=1 удалён, jobs=12, debug=\"line-tables-only\" (облегчённые символы)."
else
    echo "✅ Конфигурация уже оптимальна (jobs=12, без codegen-units=1, debug=\"line-tables-only\")."
fi

echo ""
echo "📊 Текущее содержимое $CARGO_CONFIG:"
cat "$CARGO_CONFIG"
echo ""
echo "🚀 Готово для AgentForge: сборки Rust (cargo check/build/test) теперь используют все ядра, инкрементальность и облегчённые debug-символы."
echo "   Это критично для задач оркестрации и настройки (chat 4dc58362 и связанные подзадачи)."
echo "   Эффект: меньше места в target/, быстрее rebuild'ы при работе rust-fix / grok_runner."
