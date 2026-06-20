#!/bin/bash
# Turbo launcher — antigravity_worker.py (gemini + opus 4.6)
cd ~/agentforge || exit 1
WORKERS=${1:-2}
pkill -f "antigravity_worker.py" 2>/dev/null || true
pkill -f "grok_worker.sh" 2>/dev/null || true
pkill -f "grok_xai_worker.sh" 2>/dev/null || true
sleep 1
for i in $(seq 1 "$WORKERS"); do
  nohup python3 antigravity_worker.py >> logs/antigravity_worker.log 2>&1 &
  echo "  + Antigravity worker #$i (pid $!)"
done
echo "✅ Запущено $WORKERS antigravity-воркеров (gemini + opus 4.6)"
echo "Логи: tail -f logs/antigravity_worker.log"
echo "Стоп:  pkill -f antigravity_worker.py"
