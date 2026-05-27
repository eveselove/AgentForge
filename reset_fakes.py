#!/usr/bin/env python3
"""Скрипт для сброса фейковых задач обратно в pending"""
import urllib.request
import json

# Загружаем все задачи
x = json.loads(urllib.request.urlopen("http://localhost:8080/tasks").read().decode())

fakes = []
for t in x:
    if t["status"] != "done":
        continue
    dur = t.get("duration_seconds") or 0
    agent = t.get("assigned_agent") or ""
    result = t.get("result") or ""
    # Фейковые: grok за 0 секунд
    if dur == 0 and agent == "grok":
        fakes.append(t)
        print(f"FAKE: {t['id']} - {t['title'][:60]}")

print(f"\nTotal fake: {len(fakes)}")

# Сбрасываем
for t in fakes:
    data = json.dumps({
        "status": "pending",
        "assigned_agent": None,
        "result": None,
        "preferred_agent": "grok"
    }).encode()
    req = urllib.request.Request(
        f"http://localhost:8080/tasks/{t['id']}",
        data=data,
        method="PATCH"
    )
    req.add_header("Content-Type", "application/json")
    urllib.request.urlopen(req)
    print(f"  RESET: {t['id']}")

print(f"\nDone: {len(fakes)} tasks reset to pending")
