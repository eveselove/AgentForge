#!/bin/bash
# ============================================
# Turbo Mode Launcher - One command to start maximum agents
# Создано автоматически
# ============================================

set -e

echo "🚀 Запуск турбо-режима AgentForge..."

# Переходим в директорию проекта
cd ~/agentforge || exit 1

# Загружаем переменные окружения (если есть .env.xai)
if [ -f ".env.xai" ]; then
    export $(grep -v '^#' .env.xai | xargs)
    echo "✓ Загружен .env.xai"
else
    echo "⚠️  Файл .env.xai не найден! Создаю..."
    cp .env.xai.example .env.xai 2>/dev/null || echo "XAI_API_KEY=ВСТАВЬ_КЛЮЧ_СЮДА" > .env.xai
    export $(grep -v '^#' .env.xai | xargs)
fi

# Проверяем ключ
if [ -z "$XAI_API_KEY" ] || [[ "$XAI_API_KEY" == *"ВСТАВЬ"* ]]; then
    echo "❌ Ошибка: XAI_API_KEY не задан в .env.xai"
    exit 1
fi

echo "✓ Ключ xAI загружен"

# Количество облачных агентов (можно менять)
CLOUD_AGENTS=4
LOCAL_AGENTS=3

echo ""
echo "Запускаю $CLOUD_AGENTS облачных Grok-4 агентов + $LOCAL_AGENTS локальных..."

# Убиваем старые процессы (если были)
pkill -f grok_xai_worker.sh 2>/dev/null || true
pkill -f "grok_worker.sh" 2>/dev/null || true
sleep 1

# Запуск облачных агентов
for i in $(seq 1 $CLOUD_AGENTS); do
    nohup bash grok_xai_worker.sh > /dev/null 2>&1 &
    echo "  + Cloud Grok #$i запущен"
done

# Запуск локальных агентов
for i in $(seq 1 $LOCAL_AGENTS); do
    nohup bash grok_worker.sh > /dev/null 2>&1 &
    echo "  + Local Grok #$i запущен"
done

echo ""
echo "✅ Турбо-режим активирован!"
echo ""
echo "Проверить запущенные агенты:"
echo "  ps aux | grep -E 'grok_xai_worker|grok_worker' | grep -v grep"
echo ""
echo "Логи:"
echo "  tail -f logs/grok_xai_worker.log"
echo ""
echo "Чтобы остановить всех агентов:"
echo "  pkill -f 'grok_xai_worker\|grok_worker'"
