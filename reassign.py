#!/usr/bin/env python3
"""Переназначить все pending задачи на grok"""
import urllib.request
import json

x = json.loads(urllib.request.urlopen("http://localhost:8080/tasks").read().decode())
count = 0
for t in x:
    if t["status"] == "pending" and t.get("preferred_agent") not in ("grok", "auto"):
        data = json.dumps({"preferred_agent": "grok"}).encode()
        req = urllib.request.Request(
            f"http://localhost:8080/tasks/{t['id']}",
            data=data,
            method="PATCH"
        )
        req.add_header("Content-Type", "application/json")
        urllib.request.urlopen(req)
        count += 1
        old = t.get("preferred_agent", "?")
        print(f"  {t['id']} {old:>12} -> grok  | {t['title'][:50]}")
print(f"\nReassigned: {count} tasks")
