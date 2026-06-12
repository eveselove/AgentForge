#!/bin/bash
LOG_FILE="/home/agx/planlytasksko/pytorch_build.log"
while true; do
  sleep 1200
  LAST_LINE=$(tail -n 1 "$LOG_FILE" | grep -v 'nohup')
  notify-send "Сборка PyTorch" "Статус: $LAST_LINE" -i face-cool -t 10000
  if grep -q "Build completed successfully!" "$LOG_FILE"; then
    notify-send -u critical "Сборка PyTorch ЗАВЕРШЕНА" "Пакет успешно скомпилирован!" -i face-win
    break
  fi
done
