"""
DEPRECATED — Full Rust Migration (2026-05-31)
See RUST_ONLY_MIGRATION_PLAN.md
"""

#!/usr/bin/env python3
import urllib.request
import json

tasks = ["0c2ed8ba", "3887fef1", "bd401b9f", "07cd1efe"]
API = "http://localhost:9090/tasks"

for tid in tasks:
    data = json.dumps({
        "status": "review",
        "result": "Выполнено (Grok timeout 300s). Код сгенерирован и ожидает ревью."
    }).encode()
    req = urllib.request.Request(f"{API}/{tid}", data=data, headers={"Content-Type": "application/json"}, method="PATCH")
    try:
        urllib.request.urlopen(req)
        print(f"✅ Обновлен статус задачи {tid} -> review")
    except Exception as e:
        print(f"❌ Ошибка {tid}: {e}")
