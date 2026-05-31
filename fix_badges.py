"""
DEPRECATED — Full Rust Migration (2026-05-31)
See RUST_ONLY_MIGRATION_PLAN.md
"""

#!/usr/bin/env python3
"""Убрать нумерацию агентов — оставить только имя"""
with open("/home/agx/agentforge/dashboard.html", "r") as f:
    c = f.read()

# Ищем блок с agentCount и agentName
old = """                // Реальное кол-во задач этого агента в работе
                const agentCount = allTasks.filter(t =>
                    (t.status === 'dispatched' || t.status === 'in_progress') &&
                    (t.assigned_agent || t.preferred_agent) === agent
                ).length;
                const agentName = agent === 'auto' ? 'Авто'
                    : agent.toUpperCase() + (agentCount > 0 ? ` \u00d7${agentCount}` : '');"""

new = """                // Имя агента без нумерации
                const agentName = agent === 'auto' ? 'АВТО' : agent.toUpperCase();"""

if old in c:
    c = c.replace(old, new)
    print("✅ Убрана нумерация (новый формат)")
else:
    # Fallback — ищем любой вариант с agentThreads или agentCount
    import re
    # Убираем всё между "// Потоки" или "// Реальное" и строкой с agentName
    c = re.sub(
        r"                // (Потоки|Реальное)[^\n]*\n.*?const agentName = agent === 'auto' \? '[^']+'\n\s*: agent\.toUpperCase\(\)[^;]+;",
        "                // Имя агента\n                const agentName = agent === 'auto' ? 'АВТО' : agent.toUpperCase();",
        c,
        flags=re.DOTALL
    )
    print("✅ Убрана нумерация (regex fallback)")

with open("/home/agx/agentforge/dashboard.html", "w") as f:
    f.write(c)

# Проверяем
import subprocess
subprocess.run(["grep", "-n", "agentName", "/home/agx/agentforge/dashboard.html"])
