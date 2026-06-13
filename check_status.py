#!/usr/bin/env python3
import urllib.request
import json
import urllib.error

try:
    with urllib.request.urlopen("http://localhost:9090/metrics") as r:
        metrics = json.loads(r.read().decode())
        print("=== МЕТРИКИ СИСТЕМЫ ===")
        print(json.dumps(metrics, indent=2, ensure_ascii=False))

    with urllib.request.urlopen("http://localhost:9090/tasks") as r:
        tasks = json.loads(r.read().decode())
        print("\n=== АКТИВНЫЕ ЗАДАЧИ ===")
        for t in tasks:
            if t["status"] in ("pending", "dispatched", "in_progress", "failed"):
                print(f"[{t['status'].upper()}] {t['title'][:60]} (Agent: {t['assigned_agent']})")
                
except Exception as e:
    print("Error:", e)
