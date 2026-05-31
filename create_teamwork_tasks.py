#!/usr/bin/env python3
import urllib.request
import json

API = "http://localhost:8080"

tasks = [
    {
        "title": "Агент-резолвер для разрешения Merge Conflicts",
        "description": "Создать механизм (или отдельного агента), который автоматически разрешает конфликты git merge, возникающие при одновременной работе разных агентов в git worktrees. Если автоматическое слияние не удалось, резолвер должен анализировать код и сливать изменения, либо эскалировать человеку (HITL).",
        "priority": "high",
        "complexity": "complex",
        "tags": ["git", "merge", "resolver", "orchestration"],
        "preferred_agent": "grok"
    },
    {
        "title": "Оперативная память команды (Blackboard)",
        "description": "Реализовать общую 'доску' для активных агентов. Агенты должны иметь возможность публиковать сообщения о своих текущих действиях (например: 'Я меняю структуру БД') в реальном времени, чтобы другие агенты могли читать это и адаптировать свой код. Использовать in-memory структуру в FastAPI или Redis.",
        "priority": "high",
        "complexity": "medium",
        "tags": ["memory", "blackboard", "communication"],
        "preferred_agent": "grok"
    },
    {
        "title": "Service Discovery: Динамический поиск агентов по скиллам",
        "description": "Реализовать механизм обнаружения (Service Discovery). Один агент должен иметь возможность запросить у системы (например, через endpoint /agents/discover) список доступных агентов с определенными навыками (скиллами, например, 'Frontend'), чтобы делегировать им кусок работы напрямую.",
        "priority": "high",
        "complexity": "medium",
        "tags": ["service-discovery", "orchestration", "delegation"],
        "preferred_agent": "antigravity"
    }
]

print(f"Создаю {len(tasks)} задач для командной работы агентов...")
for t in tasks:
    data = json.dumps(t).encode()
    req = urllib.request.Request(
        f"{API}/tasks",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    try:
        resp = urllib.request.urlopen(req)
        result = json.loads(resp.read().decode())
        print(f"  ✅ Запланировано: {t['title'][:50]}... (ID: {result.get('id', '?')[:8]})")
    except Exception as e:
        print(f"  ❌ Ошибка при создании задачи {t['title'][:30]}: {e}")
