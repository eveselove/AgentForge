#!/bin/bash
# Установка systemd сервисов для Grok XAI Cloud Workers

set -e

echo "=== Установка Grok XAI Workers ==="

if [ ! -f /home/eveselove/agentforge/.env.xai ]; then
    echo "Создаю .env.xai из примера..."
    cp /home/eveselove/agentforge/.env.xai.example /home/eveselove/agentforge/.env.xai
    echo "!!! Отредактируй /home/eveselove/agentforge/.env.xai и вставь туда свой XAI_API_KEY !!!"
    exit 1
fi

echo "Копирую unit-файлы..."
sudo cp /home/eveselove/agentforge/systemd/grok-xai-worker.service /etc/systemd/system/
sudo cp /home/eveselove/agentforge/systemd/grok-xai-worker@.service /etc/systemd/system/

echo "Перезагружаю systemd..."
sudo systemctl daemon-reload

echo ""
echo "Готово!"
echo ""
echo "Примеры команд:"
echo "  systemctl enable --now grok-xai-worker          # один инстанс"
echo "  systemctl enable --now grok-xai-worker@1        # инстанс 1"
echo "  systemctl enable --now grok-xai-worker@2        # инстанс 2"
echo "  systemctl status grok-xai-worker@1"
echo "  journalctl -u grok-xai-worker@1 -f"
echo ""
echo "Чтобы запустить 3 параллельных облачных агента:"
echo "  systemctl enable --now grok-xai-worker@{1..3}"
