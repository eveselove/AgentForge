#!/bin/bash
# Автозапуск AgentForge Gateway (Rust task API on 9090, replaces legacy task_queue.py)
cd /home/eveselove/agentforge

# Guard: gateway теперь под systemd (agentforge-gateway.service, Restart=always).
# Не поднимаем второй инстанс вручную — иначе конфликт за :9090 (ручной squat
# роняет systemd-gateway, как это уже случалось). Если сервис жив или порт занят —
# просто выходим.
if systemctl --user is-active --quiet agentforge-gateway.service 2>/dev/null; then
  echo "ℹ️  agentforge-gateway уже работает через systemd — ручной старт не нужен."
  echo "    Управление: systemctl --user {status,restart,stop} agentforge-gateway"
  exit 0
fi
if ss -tln 2>/dev/null | grep -q ':9090 '; then
  echo "ℹ️  Порт :9090 уже занят — gateway, видимо, запущен. Ручной старт пропущен." >&2
  exit 0
fi

# Prefer release gateway binary; fallback debug or error
if [ -x "./gateway/target/release/agentforge-gateway" ]; then
  exec ./gateway/target/release/agentforge-gateway
elif [ -x "./gateway/target/debug/agentforge-gateway" ]; then
  exec ./gateway/target/debug/agentforge-gateway
else
  echo "ERROR: agentforge-gateway binary not found. Build with: cd gateway && cargo build --release" >&2
  exit 1
fi
