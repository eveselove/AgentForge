#!/usr/bin/env python3
"""
MCP (Model Context Protocol) сервер для AgentForge Task Queue.
Позволяет любому чату Antigravity IDE управлять очередью задач напрямую.
Транспорт: stdio
"""

import json
import asyncio
import urllib.request
import urllib.error
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

# Базовый URL API AgentForge
_cached_api_base = None

def _get_api_base() -> str:
    """
    Динамически определяет рабочий адрес API AgentForge.
    Сначала проверяет локальные порты туннелей (9090, 8080), затем удаленный IP.
    """
    global _cached_api_base
    if _cached_api_base:
        try:
            req = urllib.request.Request(f"{_cached_api_base}/health", method="GET")
            with urllib.request.urlopen(req, timeout=1) as resp:
                return _cached_api_base
        except Exception:
            _cached_api_base = None

    candidates = [
        "http://localhost:9090",
        "http://localhost:8080",
        "http://146.120.89.199:8080"
    ]
    for base in candidates:
        try:
            req = urllib.request.Request(f"{base}/health", method="GET")
            with urllib.request.urlopen(req, timeout=1) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if data.get("status") == "ok":
                    _cached_api_base = base
                    return base
        except Exception:
            continue
    return "http://localhost:8080"

# Создаём MCP сервер
server = Server("agentforge")


def _api_request(path: str, method: str = "GET", data: dict | None = None) -> dict | list | str:
    """
    Выполняет HTTP-запрос к AgentForge API.
    Возвращает распарсенный JSON или текст ответа.
    """
    url = f"{_get_api_base()}{path}"
    headers = {"Content-Type": "application/json"}

    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")

    req = urllib.request.Request(url, data=body, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return raw
    except urllib.error.HTTPError as e:
        # Читаем тело ошибки для более информативного сообщения
        error_body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code}: {error_body}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Ошибка подключения к API: {e.reason}") from e


@server.list_tools()
async def list_tools() -> list[Tool]:
    """Регистрирует все доступные инструменты MCP-сервера."""
    return [
        Tool(
            name="agentforge_list_tasks",
            description="Получить список всех задач. Можно фильтровать по статусу (pending, dispatched, running, completed, failed).",
            inputSchema={
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "description": "Фильтр по статусу задачи (необязательно)",
                        "enum": ["pending", "dispatched", "running", "completed", "failed"],
                    }
                },
                "required": [],
            },
        ),
        Tool(
            name="agentforge_create_task",
            description="Создать новую задачу в очереди AgentForge.",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Название задачи",
                    },
                    "description": {
                        "type": "string",
                        "description": "Подробное описание задачи",
                    },
                    "priority": {
                        "type": "string",
                        "description": "Приоритет: low, medium, high, critical",
                        "enum": ["low", "medium", "high", "critical"],
                        "default": "medium",
                    },
                    "complexity": {
                        "type": "string",
                        "description": "Сложность: simple, medium, complex, critical",
                        "enum": ["simple", "medium", "complex", "critical"],
                        "default": "medium",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Теги для маршрутизации задачи (напр. rust, python, frontend)",
                    },
                },
                "required": ["title", "description"],
            },
        ),
        Tool(
            name="agentforge_dispatch_task",
            description="Отправить задачу на выполнение конкретному агенту.",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "ID задачи для отправки",
                    },
                    "agent": {
                        "type": "string",
                        "description": "Имя агента-исполнителя (напр. grok, jules, antigravity)",
                    },
                },
                "required": ["task_id", "agent"],
            },
        ),
        Tool(
            name="agentforge_get_task",
            description="Получить детальную информацию о задаче по ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "ID задачи",
                    }
                },
                "required": ["task_id"],
            },
        ),
        Tool(
            name="agentforge_update_task",
            description="Обновить статус или результат задачи.",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "ID задачи",
                    },
                    "status": {
                        "type": "string",
                        "description": "Новый статус задачи",
                        "enum": ["pending", "dispatched", "running", "completed", "failed"],
                    },
                    "result": {
                        "type": "string",
                        "description": "Результат выполнения задачи (текст)",
                    },
                },
                "required": ["task_id"],
            },
        ),
        Tool(
            name="agentforge_metrics",
            description="Получить метрики очереди задач: общее количество, по статусам, по агентам, среднее время выполнения.",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Обрабатывает вызов инструмента от клиента MCP."""

    try:
        if name == "agentforge_list_tasks":
            return await _handle_list_tasks(arguments)
        elif name == "agentforge_create_task":
            return await _handle_create_task(arguments)
        elif name == "agentforge_dispatch_task":
            return await _handle_dispatch_task(arguments)
        elif name == "agentforge_get_task":
            return await _handle_get_task(arguments)
        elif name == "agentforge_update_task":
            return await _handle_update_task(arguments)
        elif name == "agentforge_metrics":
            return await _handle_metrics(arguments)
        else:
            return [TextContent(type="text", text=f"❌ Неизвестный инструмент: {name}")]
    except RuntimeError as e:
        return [TextContent(type="text", text=f"❌ Ошибка API: {e}")]
    except Exception as e:
        return [TextContent(type="text", text=f"❌ Непредвиденная ошибка: {type(e).__name__}: {e}")]


async def _handle_list_tasks(arguments: dict) -> list[TextContent]:
    """Получение списка задач с опциональной фильтрацией по статусу."""
    status_filter = arguments.get("status")

    # Запрос к API в отдельном потоке (чтобы не блокировать event loop)
    result = await asyncio.to_thread(_api_request, "/tasks")

    # Фильтрация по статусу, если указан
    if status_filter and isinstance(result, list):
        result = [t for t in result if t.get("status") == status_filter]

    # Форматирование вывода
    if isinstance(result, list):
        if not result:
            text = "📋 Задач не найдено."
        else:
            lines = [f"📋 Найдено задач: {len(result)}\n"]
            for task in result:
                status_emoji = {
                    "pending": "⏳",
                    "dispatched": "📤",
                    "running": "🔄",
                    "completed": "✅",
                    "failed": "❌",
                }.get(task.get("status", ""), "❓")
                priority_emoji = {
                    "low": "🟢",
                    "medium": "🟡",
                    "high": "🟠",
                    "critical": "🔴",
                }.get(task.get("priority", ""), "⚪")
                lines.append(
                    f"{status_emoji} [{task.get('id', '?')}] {priority_emoji} {task.get('title', 'Без названия')} "
                    f"| статус: {task.get('status', '?')} | агент: {task.get('assigned_agent', '-')}"
                )
            text = "\n".join(lines)
    else:
        text = json.dumps(result, ensure_ascii=False, indent=2)

    return [TextContent(type="text", text=text)]


async def _handle_create_task(arguments: dict) -> list[TextContent]:
    """Создание новой задачи."""
    payload = {
        "title": arguments["title"],
        "description": arguments["description"],
        "priority": arguments.get("priority", "medium"),
        "complexity": arguments.get("complexity", "medium"),
        "tags": arguments.get("tags", []),
    }

    result = await asyncio.to_thread(_api_request, "/tasks", "POST", payload)
    task_id = result.get("id", "?") if isinstance(result, dict) else "?"

    text = (
        f"✅ Задача создана!\n"
        f"ID: {task_id}\n"
        f"Название: {payload['title']}\n"
        f"Приоритет: {payload['priority']}\n"
        f"Сложность: {payload['complexity']}\n"
        f"Теги: {', '.join(payload['tags']) if payload['tags'] else '-'}"
    )
    return [TextContent(type="text", text=text)]


async def _handle_dispatch_task(arguments: dict) -> list[TextContent]:
    """Отправка задачи на выполнение агенту."""
    task_id = arguments["task_id"]
    agent = arguments["agent"]

    result = await asyncio.to_thread(
        _api_request, f"/tasks/{task_id}/dispatch", "POST", {"agent": agent}
    )

    text = f"📤 Задача {task_id} отправлена агенту: {agent}"
    if isinstance(result, dict) and "status" in result:
        text += f"\nСтатус: {result['status']}"

    return [TextContent(type="text", text=text)]


async def _handle_get_task(arguments: dict) -> list[TextContent]:
    """Получение деталей задачи по ID."""
    task_id = arguments["task_id"]
    result = await asyncio.to_thread(_api_request, f"/tasks/{task_id}")

    if isinstance(result, dict):
        # Красиво форматируем информацию о задаче
        lines = [
            f"📌 Задача: {result.get('title', 'Без названия')}",
            f"   ID: {result.get('id', '?')}",
            f"   Статус: {result.get('status', '?')}",
            f"   Приоритет: {result.get('priority', '?')}",
            f"   Сложность: {result.get('complexity', '?')}",
            f"   Агент: {result.get('assigned_agent', '-')}",
            f"   Теги: {', '.join(result.get('tags', [])) or '-'}",
            f"   Создана: {result.get('created_at', '?')}",
            f"   Описание: {result.get('description', '-')}",
        ]
        # Добавляем результат, если есть
        if result.get("result"):
            lines.append(f"   Результат: {result['result']}")
        text = "\n".join(lines)
    else:
        text = json.dumps(result, ensure_ascii=False, indent=2)

    return [TextContent(type="text", text=text)]


async def _handle_update_task(arguments: dict) -> list[TextContent]:
    """Обновление статуса или результата задачи."""
    task_id = arguments["task_id"]

    # Собираем только переданные поля для обновления
    payload = {}
    if "status" in arguments:
        payload["status"] = arguments["status"]
    if "result" in arguments:
        payload["result"] = arguments["result"]

    if not payload:
        return [TextContent(type="text", text="⚠️ Не указаны поля для обновления (status или result).")]

    result = await asyncio.to_thread(
        _api_request, f"/tasks/{task_id}", "PATCH", payload
    )

    updates = ", ".join(f"{k}={v}" for k, v in payload.items())
    text = f"✅ Задача {task_id} обновлена: {updates}"

    return [TextContent(type="text", text=text)]


async def _handle_metrics(arguments: dict) -> list[TextContent]:
    """Получение метрик очереди задач."""
    result = await asyncio.to_thread(_api_request, "/metrics")

    if isinstance(result, dict):
        lines = ["📊 Метрики AgentForge Task Queue\n"]

        # Общее количество задач
        lines.append(f"   Всего задач: {result.get('total_tasks', '?')}")

        # По статусам
        by_status = result.get("by_status", {})
        if by_status:
            lines.append("\n   По статусам:")
            status_emojis = {
                "pending": "⏳",
                "dispatched": "📤",
                "running": "🔄",
                "completed": "✅",
                "failed": "❌",
            }
            for status, count in by_status.items():
                emoji = status_emojis.get(status, "❓")
                lines.append(f"     {emoji} {status}: {count}")

        # По агентам
        by_agent = result.get("by_agent", {})
        if by_agent:
            lines.append("\n   По агентам:")
            for agent, count in by_agent.items():
                lines.append(f"     🤖 {agent}: {count}")

        # Среднее время выполнения
        avg_time = result.get("avg_completion_time")
        if avg_time is not None:
            lines.append(f"\n   ⏱️ Среднее время выполнения: {avg_time:.1f} сек")

        text = "\n".join(lines)
    else:
        text = json.dumps(result, ensure_ascii=False, indent=2)

    return [TextContent(type="text", text=text)]


async def main():
    """Точка входа — запуск MCP-сервера через stdio."""
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
