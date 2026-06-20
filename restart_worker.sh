#!/bin/bash
# AgentForge worker restart — antigravity_worker.py (gemini + opus 4.6)
cd ~/agentforge

# 1. Stop running worker(s)
pkill -9 -f "antigravity_worker.py" 2>/dev/null || true
pkill -9 -f "grok_worker.sh" 2>/dev/null || true   # legacy safety
sleep 2

# 2. Release stuck tasks (best-effort)
for ep in /tasks /api/tasks; do
  curl -s "http://localhost:9090$ep" 2>/dev/null | python3 - "$ep" <<"PY" 2>/dev/null || true
import sys,json,urllib.request
ep=sys.argv[1]
try: tasks=json.load(sys.stdin)
except Exception: sys.exit(0)
for t in tasks if isinstance(tasks,list) else []:
    if t.get("status") in ("pending","in_progress") and t.get("assigned_agent") in ("grok","antigravity"):
        try:
            req=urllib.request.Request(f"http://localhost:9090{ep}/{t[\"id\"]}",
                data=json.dumps({"status":"pending","assigned_agent":None}).encode(),
                headers={"Content-Type":"application/json"},method="PATCH")
            urllib.request.urlopen(req,timeout=5)
        except Exception: pass
PY
done

# 3. Start antigravity worker
nohup python3 antigravity_worker.py >> logs/antigravity_worker.log 2>&1 &
echo "Antigravity worker (gemini+opus) запущен, pid $!"
disown
