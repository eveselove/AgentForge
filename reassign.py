#!/usr/bin/env python3
"""
Переводит "застрявшие" pending задачи на Grok.

Используется как инструмент восстановления после неправильной маршрутизации
(особенно после старой логики, которая массово кидала всё на antigravity).

Новая рекомендация (2026-06):
- Запускать этот скрипт после изменений в routing.
- Он теперь щадяще переводит только реально проблемные задачи.
"""
import urllib.request
import json

API = "http://localhost:8080"

tasks = json.loads(urllib.request.urlopen(f"{API}/tasks").read().decode())

count = 0
for t in tasks:
    if t["status"] != "pending":
        continue

    pref = t.get("preferred_agent", "auto")
    if pref in ("grok", "auto", "jules"):
        continue

    # Не трогаем задачи, которые явно предназначены для глубокого анализа
    tags = [str(x).lower() for x in (t.get("tags") or [])]
    if any(x in tags for x in ["deep-analysis", "architecture-decision", "critical-review", "antigravity-only"]):
        continue

    # Переводим на grok
    data = json.dumps({"preferred_agent": "grok"}).encode()
    req = urllib.request.Request(
        f"{API}/tasks/{t['id']}",
        data=data,
        method="PATCH"
    )
    req.add_header("Content-Type", "application/json")
    try:
        urllib.request.urlopen(req)
        count += 1
        old = t.get("preferred_agent", "?")
        print(f"  {t['id'][:8]}  {old:>12} -> grok   | {t['title'][:55]}")
    except Exception as e:
        print(f"  ERROR on {t['id']}: {e}")

print(f"\nReassigned to grok: {count} tasks")
print("Рекомендация: после массового reassignment запусти grok_worker, чтобы задачи подхватились.")
