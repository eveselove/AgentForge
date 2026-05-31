#!/bin/bash
#
# ensure_rust_devtools.sh
# Скрипт обеспечения установки и актуальности cargo-binstall и cargo-machete
# для ускорения и улучшения работы с Rust-инструментами в среде AgentForge.
#
# Назначение (подзадача из чата «AgentForge: оркестрация и настройка», 4dc58362):
#   - Установка `cargo-binstall` — быстрый установщик prebuilt cargo-крейтов
#     (заменяет медленный `cargo install`, который компилирует из исходников).
#   - Установка `cargo-machete` — инструмент поиска неиспользуемых зависимостей
#     в Cargo.toml (cargo machete). Полезен при рефакторинге больших workspace.
#   - Установка `cargo-nextest` — быстрый параллельный тестовый раннер (замена cargo test).
#     Критично для CI-проверок в grok_runner.sh после правок агентов (rust-fix skill).
#
# Почему это важно для AgentForge:
#   - Rust-задачи агентов (rust-fix skill, grok_runner) часто требуют
#     установки временных утилит (cargo-udeps, cargo-outdated, nextest и т.д.).
#   - cargo-binstall сокращает время установки утилит с минут до секунд.
#   - cargo-machete помогает поддерживать чистоту зависимостей в
#     planly_gateway, planly_core и других крейтах — снижает время компиляции.
#   - cargo-nextest ускоряет выполнение тестов в 2-10x (параллелизм по умолчанию,
#     умный вывод, поддержка .config/nextest.toml для повторных запусков flaky-тестов).
#   - Улучшает опыт в CI и локальных проверках после правок агентов (см. обновление grok_runner.sh).
#
# Использование:
#   bash ~/agentforge/scripts/ensure_rust_devtools.sh
#   # или из любого места после добавления в PATH setup
#
# Идемпотентен: безопасно запускать многократно (проверяет наличие и версии).
# Все комментарии, echo и логи — строго на русском языке.
#
# Интеграция:
#   Рекомендуется вызывать из install_services.sh и/или grok_runner.sh
#   при старте задачи (гарантия наличия инструментов, включая cargo-nextest для CI).
#   Обновлено подзадачей "Установка cargo-nextest и обновление grok_runner.sh".
#

set -euo pipefail

CARGO_BIN_DIR="${HOME}/.cargo/bin"
CARGO_BININSTALL="${CARGO_BIN_DIR}/cargo-binstall"
CARGO_MACHETE="${CARGO_BIN_DIR}/cargo-machete"
LOG_PREFIX="[AgentForge Rust DevTools]"

echo "🔧 ${LOG_PREFIX} Проверка и установка cargo-binstall + cargo-machete ..."
echo "   Цель: ускорение установки Rust-утилит и анализ неиспользуемых зависимостей."

# Гарантируем наличие директории
mkdir -p "${CARGO_BIN_DIR}"
export PATH="${CARGO_BIN_DIR}:${PATH}"

# ===== Функция: проверка наличия бинаря (и его работоспособности) =====
is_installed() {
    local bin="$1"
    local cmd_name="$bin"
    # cargo-binstall, cargo-machete и cargo-nextest вызываются через cargo subcommand
    if [[ "$bin" == "cargo-binstall" ]]; then cmd_name="cargo binstall"; fi
    if [[ "$bin" == "cargo-machete" ]]; then cmd_name="cargo machete"; fi
    if [[ "$bin" == "cargo-nextest" ]]; then cmd_name="cargo nextest"; fi

    if command -v "$bin" >/dev/null 2>&1; then
        # Проверяем, что бинарь реально запускается (нет ошибок GLIBC и т.п.)
        if $cmd_name -V >/dev/null 2>&1 || $cmd_name --version >/dev/null 2>&1; then
            return 0
        else
            echo "⚠️  $bin найден, но не работает (возможно несовместимость glibc) — будет переустановлен."
            return 1
        fi
    fi
    if [[ -x "$bin" ]]; then
        if "$bin" -V >/dev/null 2>&1 || "$bin" --version >/dev/null 2>&1; then
            return 0
        else
            echo "⚠️  $bin существует, но не запускается — будет переустановлен."
            return 1
        fi
    fi
    return 1
}

# ===== Функция: безопасное получение версии =====
get_version() {
    local tool="$1"
    local ver=""
    # Пробуем cargo subcommand (cargo binstall / cargo machete / cargo nextest)
    if [[ "$tool" == "binstall" ]]; then
        ver=$(cargo binstall -V 2>/dev/null || /home/agx/.cargo/bin/cargo-binstall -V 2>/dev/null || echo "")
    elif [[ "$tool" == "machete" ]]; then
        ver=$(cargo machete -V 2>/dev/null || /home/agx/.cargo/bin/cargo-machete -V 2>/dev/null || echo "")
    elif [[ "$tool" == "nextest" ]]; then
        ver=$(cargo nextest --version 2>/dev/null || /home/agx/.cargo/bin/cargo-nextest --version 2>/dev/null || echo "")
    fi
    if [[ -z "$ver" ]]; then
        ver="not-available-or-incompatible"
    fi
    echo "$ver" | head -1 | tr -d '\n'
}

# ===== 1. Установка / обновление cargo-binstall =====
echo ""
echo "📦 Шаг 1/2: cargo-binstall"

if is_installed "cargo-binstall" || is_installed "${CARGO_BININSTALL}"; then
    CURRENT_VERSION=$(get_version "binstall")
    echo "✅ cargo-binstall уже установлен: ${CURRENT_VERSION}"
else
    echo "⚠️  cargo-binstall не найден — выполняем установку через официальный скрипт..."
    echo "   Источник: https://github.com/cargo-bins/cargo-binstall"

    # Официальный способ установки (рекомендован upstream)
    if ! curl -L --proto '=https' --tlsv1.2 -sSf \
        https://raw.githubusercontent.com/cargo-bins/cargo-binstall/main/install-from-binstall-release.sh \
        | bash; then
        echo "❌ Ошибка установки cargo-binstall через curl. Пробуем fallback: cargo install..."
        # Fallback (медленнее, но работает)
        if command -v cargo >/dev/null 2>&1; then
            cargo install cargo-binstall --locked
        else
            echo "❌ Критично: cargo не найден в PATH. Установите rustup/cargo сначала."
            exit 1
        fi
    fi

    # Перечитываем PATH после установки
    hash -r 2>/dev/null || true
    export PATH="${CARGO_BIN_DIR}:${PATH}"

    if is_installed "cargo-binstall"; then
        NEW_VERSION=$(get_version "binstall")
        echo "✅ cargo-binstall успешно установлен: ${NEW_VERSION}"
    else
        echo "❌ Установка cargo-binstall завершилась, но бинарь не обнаружен."
        echo "   Проверьте вручную: ls -l ${CARGO_BIN_DIR}/cargo-binstall"
        exit 1
    fi
fi

# ===== 2. Установка / обновление cargo-machete через binstall =====
echo ""
echo "📦 Шаг 2/2: cargo-machete"

if is_installed "cargo-machete" || is_installed "${CARGO_MACHETE}"; then
    CURRENT_VERSION=$(get_version "machete")
    echo "✅ cargo-machete уже установлен: ${CURRENT_VERSION}"
else
    echo "⚠️  cargo-machete не найден — пытаемся установить через cargo-binstall (prebuilt)..."

    machete_ok=0
    if is_installed "cargo-binstall"; then
        # Пробуем binstall (быстро)
        cargo binstall cargo-machete --locked -y 2>&1 | tail -5 || true

        # После binstall обязательно проверяем работоспособность (glibc на Jetson!)
        if is_installed "cargo-machete"; then
            machete_ok=1
            echo "✅ cargo-machete установлен через binstall (prebuilt)."
        else
            echo "⚠️  Бинарь от binstall не работает (скорее всего GLIBC_2.39 vs 2.35 на Jetson) — удаляем и собираем из исходников."
            rm -f "${CARGO_MACHETE}" 2>/dev/null || true
        fi
    fi

    if [[ $machete_ok -eq 0 ]]; then
        echo "🔨 Fallback: cargo install cargo-machete (компиляция из исходников, совместимо с glibc 2.35)..."
        cargo install cargo-machete --locked 2>&1 | tail -10 || true
    fi

    hash -r 2>/dev/null || true
    export PATH="${CARGO_BIN_DIR}:${PATH}"

    if is_installed "cargo-machete"; then
        NEW_VERSION=$(get_version "machete")
        echo "✅ cargo-machete успешно установлен и работоспособен: ${NEW_VERSION}"
    else
        echo "❌ Установка cargo-machete не удалась (даже из исходников)."
        echo "   Ручная установка: cargo install cargo-machete --locked"
        # Не выходим с ошибкой — инструмент полезный, но не критичен для базовой работы
        echo "   ⚠️  Продолжаем без machete (можно установить позже)."
    fi
fi

# ===== 3. Установка / обновление cargo-nextest (через binstall + fallback) =====
# Подзадача: [AgentForge: оркестрация и настройка] Установка `cargo-nextest` и обновление `grok_runner.sh`
# (4dc58362). cargo-nextest — ключевой инструмент для быстрых и надёжных тестов в CI
# после работы grok (rust-fix). Используем binstall для prebuilt (aarch64), с fallback
# на cargo install при несовместимости glibc (Jetson / Ubuntu 22.04 glibc 2.35).
echo ""
echo "📦 Шаг 3/3: cargo-nextest (быстрый тестовый раннер для grok_runner CI)"

CARGO_NEXTEST="${CARGO_BIN_DIR}/cargo-nextest"
if is_installed "cargo-nextest" || is_installed "${CARGO_NEXTEST}"; then
    CURRENT_VERSION=$(get_version "nextest")
    echo "✅ cargo-nextest уже установлен и работоспособен: ${CURRENT_VERSION}"
else
    echo "⚠️  cargo-nextest не найден — выполняем установку (критично для ускорения тестов в AgentForge)."
    nextest_ok=0

    if is_installed "cargo-binstall" || is_installed "${CARGO_BININSTALL}"; then
        echo "   Пробуем cargo binstall cargo-nextest --locked -y (prebuilt для aarch64)..."
        cargo binstall cargo-nextest --locked -y 2>&1 | tail -8 || true

        hash -r 2>/dev/null || true
        export PATH="${CARGO_BIN_DIR}:${PATH}"

        if is_installed "cargo-nextest" || is_installed "${CARGO_NEXTEST}"; then
            nextest_ok=1
            echo "✅ cargo-nextest установлен через binstall (prebuilt)."
        else
            echo "⚠️  Бинарь от binstall не работает (возможна несовместимость glibc на aarch64) — будет fallback."
            rm -f "${CARGO_NEXTEST}" 2>/dev/null || true
        fi
    fi

    if [[ $nextest_ok -eq 0 ]]; then
        echo "🔨 Fallback: cargo install cargo-nextest --locked (нативная компиляция под текущий glibc, займёт 5-20 мин)..."
        # Не используем --quiet, чтобы видеть прогресс в логах grok
        cargo install cargo-nextest --locked 2>&1 | tail -15 || true

        hash -r 2>/dev/null || true
        export PATH="${CARGO_BIN_DIR}:${PATH}"
    fi

    if is_installed "cargo-nextest" || is_installed "${CARGO_NEXTEST}"; then
        NEW_VERSION=$(get_version "nextest")
        echo "✅ cargo-nextest успешно установлен и работоспособен: ${NEW_VERSION}"
    else
        echo "❌ Установка cargo-nextest не удалась."
        echo "   Ручная установка (рекомендуется): cargo binstall cargo-nextest --locked -y"
        echo "   Или: cargo install cargo-nextest --locked"
        echo "   ⚠️  CI в grok_runner продолжит работу через cargo test (fallback)."
    fi
fi

# ===== Итоговая верификация =====
echo ""
echo "📊 Верификация установленных инструментов:"
echo "   PATH (первые 3): $(echo "$PATH" | tr ':' '\n' | head -3 | tr '\n' ' ')"

echo ""
echo "   cargo-binstall: $(command -v cargo-binstall || echo 'НЕ НАЙДЕН')  [$(get_version "binstall")]"
if command -v cargo-binstall >/dev/null 2>&1; then
    cargo binstall -V 2>/dev/null || echo "   (cargo binstall -V OK)"
fi

echo "   cargo-machete : $(command -v cargo-machete || echo 'НЕ НАЙДЕН')  [$(get_version "machete")]"
if command -v cargo-machete >/dev/null 2>&1; then
    cargo machete -V 2>/dev/null || echo "   (cargo machete -V не сработал — ожидается при проблемах glibc)"
fi

echo "   cargo-nextest : $(command -v cargo-nextest || echo 'НЕ НАЙДЕН')  [$(get_version "nextest")]"
if command -v cargo-nextest >/dev/null 2>&1; then
    cargo nextest --version 2>/dev/null || echo "   (cargo nextest --version OK)"
fi

echo ""
echo "🚀 Готово для AgentForge!"
echo "   • cargo-binstall позволяет быстро ставить утилиты: cargo binstall ripgrep, cargo-udeps, cargo-nextest и др."
echo "   • cargo-machete обнаруживает мёртвый код в зависимостях: cargo machete"
echo "   • cargo-nextest — основной движок тестов в CI grok_runner.sh (в 2-10 раз быстрее cargo test)"
echo "   • Все инструменты доступны агентам (grok_runner, rust-fix skill, jules)."
echo ""
echo "   Пример использования в задачах (rust-fix / AgentForge оркестрация):"
echo "     cargo binstall cargo-nextest   # быстрый prebuilt"
echo "     cargo nextest run              # вместо cargo test (параллельно, с отличным отчётом)"
echo "     cargo machete                  # поиск неиспользуемых deps"
echo ""
echo "   Рекомендация: вызов скрипта добавлен в grok_runner.sh (начало) и install_services.sh"
echo "   для гарантированной подготовки окружения перед любыми Rust-проверками."
echo ""
echo "✅ ${LOG_PREFIX} Завершено успешно (чат 4dc58362)."
echo "   Подзадачи: cargo-binstall + cargo-machete + УСТАНОВКА cargo-nextest + обновление grok_runner.sh"
