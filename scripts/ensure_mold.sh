#!/bin/bash
#
# ensure_mold.sh
# Скрипт обеспечения наличия mold (быстрого современного линкера) в ~/.cargo/bin/mold
# с корректными правами доступа.
#
# Подзадача: [AgentForge: оркестрация и настройка] Скопировать `mold` в `~/.cargo/bin/mold` и настроить права.
# (чат 4dc58362, часть серии оптимизаций Rust-сборок: jobs=12, облегчённые debug-символы, cargo-nextest, mold)
#
# Назначение:
#   - mold значительно ускоряет стадию линковки (linking) Rust-проектов (в 2-5x и более на больших крейтах).
#   - Используется через -C link-arg=-fuse-ld=mold в rustflags (в .cargo/config.toml или локально в worktree).
#   - Для AgentForge критично: большие workspace (planly_gateway + зависимости: candle, datafusion, duckdb и др.)
#     часто вызывают долгие линки при cargo build / test в задачах rust-fix и grok_runner.
#   - Бинарь помещается именно в ~/.cargo/bin (входит в PATH в grok_runner.sh и systemd-сервисах).
#
# Почему копирование, а не cargo install:
#   - mold — это не cargo-крейт, а нативный бинарь (prebuilt для aarch64-linux).
#   - Скачивание tar.gz + копирование — единственный надёжный способ на Erbox (aarch64, glibc 2.35).
#
# Источник mold: https://github.com/rui314/mold (версия 2.31.0, aarch64-linux, 2024)
#   Предполагается, что архив уже распакован в /tmp/mold-2.31.0-aarch64-linux (предыдущий шаг установки).
#   Скрипт идемпотентен: при повторных запусках не перезаписывает, если бинарь работоспособен.
#
# Использование:
#   bash /home/eveselove/agentforge/scripts/ensure_mold.sh
#   # или автоматически из grok_runner.sh / install_services.sh
#
# Все комментарии, сообщения и отчёты — строго на русском языке (требование задачи).
# Интеграция с остальными ensure_* (cargo optimization, rust devtools) — в том же стиле.
#

set -euo pipefail

LOG_PREFIX="[AgentForge mold]"
CARGO_BIN_DIR="${HOME}/.cargo/bin"
MOLD_TARGET="${CARGO_BIN_DIR}/mold"

# Возможные источники mold (после распаковки архива или предыдущих запусков)
MOLD_CANDIDATES=(
    "/tmp/mold-2.31.0-aarch64-linux/bin/mold"
    "/tmp/mold-*/bin/mold"
)

# URL для скачивания при отсутствии в /tmp (fallback, aarch64-specific)
MOLD_VERSION="2.31.0"
MOLD_TARBALL="mold-${MOLD_VERSION}-aarch64-linux.tar.gz"
MOLD_DOWNLOAD_URL="https://github.com/rui314/mold/releases/download/v${MOLD_VERSION}/${MOLD_TARBALL}"

echo "🔧 ${LOG_PREFIX} Проверка и установка mold (быстрый линкер для Rust) ..."
echo "   Цель: копирование в ${MOLD_TARGET} + права 755 (исполняемый для пользователя)."
echo "   Это ускоряет линковку в cargo build/test (используется -fuse-ld=mold)."

# Гарантируем наличие директории ~/.cargo/bin (как в ensure_rust_devtools.sh)
mkdir -p "${CARGO_BIN_DIR}"
export PATH="${CARGO_BIN_DIR}:${PATH}"

# ===== Функция: проверка работоспособности mold =====
is_mold_ok() {
    local mold_path="$1"
    if [[ -x "$mold_path" ]]; then
        if "$mold_path" --version >/dev/null 2>&1; then
            return 0
        fi
    fi
    return 1
}

# ===== Шаг 1: проверка существующего mold в ~/.cargo/bin =====
if is_mold_ok "${MOLD_TARGET}"; then
    CURRENT_VER=$("${MOLD_TARGET}" --version 2>/dev/null | head -1 || echo "unknown")
    echo "✅ ${LOG_PREFIX} mold уже установлен и работоспособен: ${CURRENT_VER}"
    echo "   Путь: ${MOLD_TARGET}"
    echo "   Права: $(ls -l "${MOLD_TARGET}" | awk '{print $1, $3, $4}')"
    echo ""
    echo "🚀 Готово для AgentForge (линковка с mold будет использоваться в rustflags)."
    exit 0
else
    echo "⚠️  ${LOG_PREFIX} mold в ${MOLD_TARGET} отсутствует или повреждён — требуется копирование/установка."
fi

# ===== Шаг 2: поиск в кандидатах (/tmp после распаковки) =====
MOLD_SRC=""
for candidate in "${MOLD_CANDIDATES[@]}"; do
    # Разворачиваем glob (если есть несколько /tmp/mold-*)
    for expanded in $candidate; do
        if [[ -f "$expanded" ]]; then
            if is_mold_ok "$expanded"; then
                MOLD_SRC="$expanded"
                echo "📦 Найден исходный mold: $MOLD_SRC"
                break 2
            fi
        fi
    done
done

# ===== Шаг 3: если не найден — скачивание и распаковка =====
if [[ -z "$MOLD_SRC" ]]; then
    echo "🌐 ${LOG_PREFIX} mold не найден в /tmp — выполняем скачивание из GitHub Releases..."
    echo "   URL: ${MOLD_DOWNLOAD_URL}"
    echo "   (Это разовая операция; в будущем будет использоваться кэш в ~/.cargo/bin)"

    TMP_DL=$(mktemp -d /tmp/mold-dl-XXXXXX)
    TARBALL_PATH="${TMP_DL}/${MOLD_TARBALL}"

    if ! curl -L --proto '=https' --tlsv1.2 --retry 2 --retry-delay 2 --max-time 120 -o "${TARBALL_PATH}" "${MOLD_DOWNLOAD_URL}"; then
        echo "❌ ${LOG_PREFIX} Ошибка скачивания mold. Проверьте сеть или скачайте вручную:"
        echo "   curl -L -o /tmp/${MOLD_TARBALL} ${MOLD_DOWNLOAD_URL}"
        echo "   tar -xzf /tmp/${MOLD_TARBALL} -C /tmp"
        echo "   Затем повторно запустите этот скрипт."
        rm -rf "${TMP_DL}" 2>/dev/null || true
        exit 1
    fi

    echo "📦 Распаковка ${MOLD_TARBALL} ..."
    if ! tar -xzf "${TARBALL_PATH}" -C "${TMP_DL}"; then
        echo "❌ Ошибка распаковки tarball."
        rm -rf "${TMP_DL}" 2>/dev/null || true
        exit 1
    fi

    EXTRACTED_MOLD="${TMP_DL}/mold-${MOLD_VERSION}-aarch64-linux/bin/mold"
    if [[ -f "${EXTRACTED_MOLD}" ]]; then
        MOLD_SRC="${EXTRACTED_MOLD}"
        echo "✅ Распакован: ${MOLD_SRC}"
    else
        echo "❌ В архиве не найден бинарь mold. Структура архива изменилась?"
        rm -rf "${TMP_DL}" 2>/dev/null || true
        exit 1
    fi

    # Не удаляем TMP_DL сразу — скопируем позже, cleanup после копирования
fi

# ===== Шаг 4: копирование и настройка прав =====
echo ""
echo "📋 Копирование mold в ${MOLD_TARGET} ..."

if ! cp -f "${MOLD_SRC}" "${MOLD_TARGET}"; then
    echo "❌ Не удалось скопировать ${MOLD_SRC} → ${MOLD_TARGET}"
    echo "   Проверьте права на запись в ${CARGO_BIN_DIR}"
    # cleanup если скачивали
    if [[ -n "${TMP_DL:-}" ]]; then rm -rf "${TMP_DL}" 2>/dev/null || true; fi
    exit 1
fi

echo "🔒 Настройка прав: chmod 755 (rwxr-xr-x) ..."
if ! chmod 755 "${MOLD_TARGET}"; then
    echo "⚠️  Не удалось установить chmod 755 (возможно запуск от root?). Пробуем chown + chmod."
    sudo chown "$(whoami):$(whoami)" "${MOLD_TARGET}" 2>/dev/null || true
    chmod 755 "${MOLD_TARGET}" 2>/dev/null || true
fi

# Дополнительно: если запускали от root — исправляем владельца на реального пользователя
if [[ "$(stat -c '%U' "${MOLD_TARGET}" 2>/dev/null || echo root)" == "root" ]]; then
    REAL_USER="${SUDO_USER:-agx}"
    echo "👤 Исправление владельца на ${REAL_USER} (избежание проблем с правами в будущем)..."
    sudo chown "${REAL_USER}:${REAL_USER}" "${MOLD_TARGET}" 2>/dev/null || true
    sudo chmod 755 "${MOLD_TARGET}" 2>/dev/null || true
fi

# Очистка временных файлов после успешного копирования
if [[ -n "${TMP_DL:-}" ]]; then
    rm -rf "${TMP_DL}" 2>/dev/null || true
fi

# ===== Шаг 5: финальная верификация =====
if is_mold_ok "${MOLD_TARGET}"; then
    FINAL_VER=$("${MOLD_TARGET}" --version 2>/dev/null | head -1)
    echo ""
    echo "✅ ${LOG_PREFIX} УСПЕШНО: mold скопирован и настроен."
    echo "   Путь:    ${MOLD_TARGET}"
    echo "   Версия:  ${FINAL_VER}"
    echo "   Права:   $(ls -l "${MOLD_TARGET}" | awk '{print $1, $3, $4}')"
    echo "   Размер:  $(du -h "${MOLD_TARGET}" | cut -f1)"
    echo ""
    echo "🚀 mold готов к использованию в AgentForge."
    echo "   В cargo-сборках будет применяться через:"
    echo "     -C link-arg=-fuse-ld=mold   (в [target.<triple>] rustflags .cargo/config.toml)"
    echo "   Эффект: ускорение линковки release/debug сборок в 2-5 раз."
    echo ""
    echo "   Подзадача выполнена: копирование + права (чат 4dc58362)."
    echo "   Рекомендуется добавить mold в rustflags в cargo config (отдельная подзадача)."
    echo ""
    echo "✅ ${LOG_PREFIX} Завершено успешно."
else
    echo "❌ ${LOG_PREFIX} Копирование выполнено, но mold не запускается. Проверьте:"
    echo "   file ${MOLD_TARGET}"
    echo "   ldd ${MOLD_TARGET}   # зависимости (libc и т.д.)"
    exit 1
fi
