#!/bin/bash
# Автозапуск AgentForge Task Queue
cd /home/eveselove/agentforge
/usr/bin/python3 -m uvicorn task_queue:app --host 0.0.0.0 --port 9090 >> /home/eveselove/agentforge/logs/server.log 2>&1
