#!/bin/bash
# Автозапуск AgentForge Task Queue
cd /home/agx/agentforge
/usr/bin/python3 -m uvicorn task_queue:app --host 0.0.0.0 --port 8080 >> /home/agx/agentforge/logs/server.log 2>&1
