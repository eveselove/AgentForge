#!/usr/bin/env python3
import urllib.request
import json

API = "http://localhost:8080"

tasks = [
    {
        "title": "Зависимости задач (DAG - Граф выполнения)",
        "description": "Добавить в БД поле `depends_on` (JSON-список ID задач). Доработать API и воркер: задача не должна переходить из статуса `blocked` в `pending`, пока все задачи из её `depends_on` не получат статус `done`. Добавить визуализацию графа в дашборд.",
        "priority": "high",
        "complexity": "complex",
        "tags": ["dag", "orchestration", "database", "api"],
        "preferred_agent": "grok"
    },
    {
        "title": "Иерархическое делегирование (Агенты создают задачи)",
        "description": "Дать агентам права на создание подзадач. Разработать скрипт-инструмент (например, `agentforge_create_task`), который агент (особенно Архитектор) сможет вызывать из терминала для декомпозиции большой задачи. Реализовать логику ожидания: родительская задача ждет завершения дочерних.",
        "priority": "high",
        "complexity": "complex",
        "tags": ["delegation", "hierarchy", "orchestration"],
        "preferred_agent": "grok"
    },
    {
        "title": "Глобальная карта кодовой базы (RepoMap)",
        "description": "Внедрить инструмент генерации AST-карты проекта (аналог Aider RepoMap). Создать фоновый процесс, который строит граф классов/функций. Добавить скрипт `get_repo_map`, который агенты могут вызывать перед началом работы для быстрого понимания архитектуры без чтения всех файлов.",
        "priority": "high",
        "complexity": "complex",
        "tags": ["repomap", "ast", "context", "optimization"],
        "preferred_agent": "grok"
    },
    {
        "title": "Интеграция внешних инструментов (MCP / Web Browsing)",
        "description": "Интегрировать Model Context Protocol (MCP) в воркер. Позволить агентам использовать браузер (Puppeteer/Playwright) для чтения документации и парсинга сайтов во время работы над задачей. Настроить проброс инструментов в среду выполнения Grok.",
        "priority": "medium",
        "complexity": "complex",
        "tags": ["mcp", "tools", "browser", "integration"],
        "preferred_agent": "grok"
    }
]

print(f"Создаю {len(tasks)} задач для финальной архитектуры AgentForge...")
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
