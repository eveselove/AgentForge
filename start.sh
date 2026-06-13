#!/bin/bash
# Автозапуск AgentForge Gateway (Rust task API on 9090, replaces legacy task_queue.py)
cd /home/eveselove/agentforge
# Prefer release gateway binary; fallback debug or error
if [ -x "./gateway/target/release/agentforge-gateway" ]; then
  exec ./gateway/target/release/agentforge-gateway
elif [ -x "./gateway/target/debug/agentforge-gateway" ]; then
  exec ./gateway/target/debug/agentforge-gateway
else
  echo "ERROR: agentforge-gateway binary not found. Build with: cd gateway && cargo build --release" >&2
  exit 1
fi
