import asyncio
import json
import urllib.request
import urllib.error
from typing import Any, Dict, Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

API_BASE = "http://localhost:9090"

server = Server("agentforge")


def make_request(method: str, path: str, data: Optional[Dict] = None) -> Any:
    url = f"{API_BASE}{path}"
    req = urllib.request.Request(url, method=method)
    if data is not None:
        req.data = json.dumps(data).encode("utf-8")
        req.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        return f"HTTP {e.code}: {error_body}"
    except Exception as e:
        return f"Error: {str(e)}"


@server.list_tools()
async def list_tools() -> list[Tool]:
    """Экспортируем инструменты AgentForge."""
    return [
        Tool(
            name="agentforge_list_tasks",
            description="Список задач из очереди AgentForge",
            inputSchema={
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "description": "Фильтр по статусу (pending, in_progress, dispatched, review, done, failed)",
                    }
                },
            },
        ),
        Tool(
            name="agentforge_create_task",
            description="Создание новой задачи в AgentForge",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "priority": {
                        "type": "string",
                        "enum": ["low", "medium", "high", "critical"],
                    },
                    "complexity": {
                        "type": "string",
                        "enum": ["simple", "medium", "complex"],
                    },
                    "tags": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["title"],
            },
        ),
        Tool(
            name="agentforge_dispatch_task",
            description="Назначить задачу агенту (отправить в работу)",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "agent": {
                        "type": "string",
                        "description": "ID агента (например, grok, jules, antigravity-subagent)",
                    },
                },
                "required": ["task_id", "agent"],
            },
        ),
        Tool(
            name="agentforge_get_task",
            description="Получить детали задачи по ID",
            inputSchema={
                "type": "object",
                "properties": {"task_id": {"type": "string"}},
                "required": ["task_id"],
            },
        ),
        Tool(
            name="agentforge_update_task",
            description="Обновить статус и/или результат задачи",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "status": {
                        "type": "string",
                        "enum": [
                            "pending",
                            "in_progress",
                            "dispatched",
                            "review",
                            "done",
                            "failed",
                        ],
                    },
                    "result": {
                        "type": "string",
                        "description": "Результат выполнения (markdown/text)",
                    },
                    "duration_seconds": {"type": "number"},
                },
                "required": ["task_id", "status"],
            },
        ),
        Tool(
            name="agentforge_metrics",
            description="Получить статистику и метрики (cost tracking, agent performance)",
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Обработчик вызовов инструментов."""
    try:
        if name == "agentforge_list_tasks":
            status = arguments.get("status")
            path = f"/tasks?status={status}" if status else "/tasks"
            res = make_request("GET", path)

            if isinstance(res, str) and res.startswith("Error"):
                return [TextContent(type="text", text=res)]

            tasks = res.get("tasks", [])
            output = f"📋 Найдено задач: {len(tasks)}\n\n"
            for t in tasks:
                t_id = t.get("id", "")[:8]
                stat = t.get("status", "unknown")
                icon = (
                    "⏳"
                    if stat == "pending"
                    else (
                        "🚀"
                        if stat in ["in_progress", "dispatched"]
                        else (
                            "✅"
                            if stat == "done"
                            else "👁️" if stat == "review" else "❌"
                        )
                    )
                )
                desc = str(t.get("description", "")).split("\n")[0][:80]
                agent = t.get("assigned_agent", "None")

                output += (
                    f"{icon} [{t_id}] {desc}... | статус: {stat} | агент: {agent}\n"
                )

            return [TextContent(type="text", text=output)]

        elif name == "agentforge_create_task":
            res = make_request("POST", "/tasks", arguments)
            return [
                TextContent(
                    type="text", text=json.dumps(res, ensure_ascii=False, indent=2)
                )
            ]

        elif name == "agentforge_dispatch_task":
            task_id = arguments["task_id"]
            agent = arguments["agent"]
            res = make_request("POST", f"/tasks/{task_id}/dispatch", {"agent": agent})
            if "status" in res and res["status"] == "dispatched":
                return [
                    TextContent(
                        type="text",
                        text=f"📤 Задача {task_id[:8]} отправлена агенту: {agent}\nСтатус: dispatched",
                    )
                ]
            return [
                TextContent(
                    type="text", text=json.dumps(res, ensure_ascii=False, indent=2)
                )
            ]

        elif name == "agentforge_get_task":
            task_id = arguments["task_id"]
            t = make_request("GET", f"/tasks/{task_id}")
            if "id" not in t:
                return [
                    TextContent(type="text", text=json.dumps(t, ensure_ascii=False))
                ]

            out = f"📌 Задача: {str(t.get('description', '')).split(chr(10))[0][:80]}...\n"
            out += f"   ID: {t.get('id')}\n"
            out += f"   Статус: {t.get('status')}\n"
            out += f"   Приоритет: {t.get('priority')}\n"
            out += f"   Сложность: {t.get('complexity')}\n"
            out += f"   Агент: {t.get('assigned_agent')}\n"
            out += f"   Теги: {', '.join(t.get('tags', []))}\n"
            out += f"   Создана: {t.get('created_at')}\n"
            out += f"   Описание: {t.get('description')}\n"

            if t.get("result"):
                out += f"   Результат: {t.get('result')}\n"

            return [TextContent(type="text", text=out)]

        elif name == "agentforge_update_task":
            task_id = arguments.pop("task_id")
            res = make_request("PATCH", f"/tasks/{task_id}", arguments)
            return [
                TextContent(
                    type="text", text=json.dumps(res, ensure_ascii=False, indent=2)
                )
            ]

        elif name == "agentforge_metrics":
            res = make_request("GET", "/metrics")
            return [
                TextContent(
                    type="text", text=json.dumps(res, ensure_ascii=False, indent=2)
                )
            ]

        else:
            return [TextContent(type="text", text=f"Неизвестный инструмент: {name}")]

    except Exception as e:
        return [
            TextContent(type="text", text=f"Ошибка выполнения инструмента: {str(e)}")
        ]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream, write_stream, server.create_initialization_options()
        )


if __name__ == "__main__":
    asyncio.run(main())
