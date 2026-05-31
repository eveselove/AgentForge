#!/usr/bin/env python3
import urllib.request
import json

API = "http://localhost:8080"

tasks = [
    {
        "title": "Агенты-Критики (Actor-Critic Architecture)",
        "description": "Внедрить паттерн 'Писатель-Критик' внутри воркера. Перед завершением задачи (коммитом) должен запускаться агент-критик (LLM-as-a-Judge), который ищет логические ошибки и уязвимости в коде основного агента. Если найдены критические баги, код возвращается на доработку без вмешательства человека.",
        "priority": "high",
        "complexity": "complex",
        "tags": ["actor-critic", "architecture", "testing", "quality"],
        "preferred_agent": "grok"
    },
    {
        "title": "Саморасширяющаяся библиотека скиллов (Tool Creation)",
        "description": "Научить систему самообучаться: если агент пишет скрипт для парсинга, деплоя или взаимодействия с новой API, он должен в конце автоматически сгенерировать YAML-playbook (скилл) и сохранить его в директорию ~/agentforge/skills/. Так другие агенты смогут использовать этот инструмент в будущем.",
        "priority": "high",
        "complexity": "complex",
        "tags": ["skills", "learning", "tools", "automation"],
        "preferred_agent": "grok"
    },
    {
        "title": "Активный RAG на прошлых ошибках (Episodic Memory)",
        "description": "Проактивное использование LanceDB. Изменить логику старта задачи: перед генерацией промпта агент должен запрашивать векторную БД на предмет похожих прошлых задач. Найденные прошлые ошибки и пути их решения должны встраиваться в системный промпт (например, 'Избегай X, в прошлый раз это привело к ошибке Y').",
        "priority": "high",
        "complexity": "complex",
        "tags": ["rag", "memory", "lancedb", "optimization"],
        "preferred_agent": "grok"
    },
    {
        "title": "Сторожевой пес бюджетов (Resource & Cost Watchdog)",
        "description": "Создать независимого фонового агента-аудитора, который мониторит время выполнения, количество попыток и затраченные токены/API косты. Если задача уходит в бесконечный цикл галлюцинаций и сжигает ресурсы без коммитов — принудительно убивать процесс (kill) и переводить задачу в статус 'failed' (requires human intervention).",
        "priority": "critical",
        "complexity": "medium",
        "tags": ["watchdog", "cost", "security", "monitoring"],
        "preferred_agent": "grok"
    },
    {
        "title": "Co-Piloting в реальном времени (Shared Workspace)",
        "description": "Реализовать возможность совместной работы человека и агента. Добавить в дашборд встроенный веб-терминал (Xterm.js) или IDE-view, подключенный к активному git worktree агента. Человек должен иметь возможность видеть печать кода в реальном времени и вносить свои правки прямо во время выполнения задачи.",
        "priority": "medium",
        "complexity": "complex",
        "tags": ["copilot", "dashboard", "websocket", "ui"],
        "preferred_agent": "antigravity"
    }
]

print(f"Создаю {len(tasks)} задач для достижения 100% AgentForge AGI...")
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
