#!/bin/bash
LOG_FILE="/home/agx/planlytasksko/pytorch_build.log"
STATUS_FILE="/home/agx/planlytasksko/BUILD_STATUS.md"

while true; do
  DATE=$(date '+%H:%M:%S')
  LAST_LINES=$(tail -n 10 "$LOG_FILE" | grep -v 'nohup')
  
  cat << EOF > "$STATUS_FILE"
# 🛠️ Статус сборки PyTorch (Jetson Orin)
*Обновлено: $DATE*

Сборка C++ может занимать 3-6 часов. Этот файл обновляется автоматически каждые 2 минуты.

## Текущий вывод компилятора:
\`\`\`text
$LAST_LINES
\`\`\`
EOF

  if grep -q "Build completed successfully!" "$LOG_FILE"; then
    echo -e "\n## ✅ СБОРКА УСПЕШНО ЗАВЕРШЕНА!" >> "$STATUS_FILE"
    break
  fi

  sleep 120
done
