#!/bin/bash
# Патч дашборда: реальные номера агентов + рестарт воркера
set -e

DASHBOARD="/home/agx/agentforge/dashboard.html"
WORKER="/home/agx/agentforge/grok_worker.sh"

echo "=== Патч дашборда: агентские бейджи ==="
# Заменяем захардкоженные потоки на реальный подсчёт
python3 << 'PYEOF'
with open("/home/agx/agentforge/dashboard.html", "r") as f:
    content = f.read()

old_block = """                // Потоки каждого агента
                const agentThreads = { grok: 10, jules: 1, antigravity: 5 };
                const threads = agentThreads[agent] || '?';
                const agentName = agent === 'auto' ? 'Авто'
                    : agent.toUpperCase() + ` ×${threads}`;"""

new_block = """                // Реальное кол-во задач этого агента в работе
                const agentCount = allTasks.filter(t =>
                    (t.status === 'dispatched' || t.status === 'in_progress') &&
                    (t.assigned_agent || t.preferred_agent) === agent
                ).length;
                const agentName = agent === 'auto' ? 'Авто'
                    : agent.toUpperCase() + (agentCount > 0 ? ` ×${agentCount}` : '');"""

if old_block in content:
    content = content.replace(old_block, new_block)
    with open("/home/agx/agentforge/dashboard.html", "w") as f:
        f.write(content)
    print("✅ Бейджи агентов исправлены — теперь показывают реальное кол-во")
else:
    # Попробуем без учёта пробелов
    import re
    old_pattern = r"const agentThreads = \{ grok: 10, jules: 1, antigravity: 5 \};"
    if re.search(old_pattern, content):
        content = re.sub(old_pattern, 
            "const agentCount = allTasks.filter(t => (t.status === 'dispatched' || t.status === 'in_progress') && (t.assigned_agent || t.preferred_agent) === agent).length;",
            content)
        content = content.replace(
            "const threads = agentThreads[agent] || '?';",
            "// threads заменён на agentCount"
        )
        content = content.replace(
            ": agent.toUpperCase() + ` ×${threads}`;",
            ": agent.toUpperCase() + (agentCount > 0 ? ` ×${agentCount}` : '');"
        )
        with open("/home/agx/agentforge/dashboard.html", "w") as f:
            f.write(content)
        print("✅ Бейджи исправлены (regex)")
    else:
        print("⚠️ Паттерн не найден — возможно Grok уже менял dashboard")
        # Покажем что есть
        import subprocess
        subprocess.run(["grep", "-n", "agentThreads\|threads\|×", "/home/agx/agentforge/dashboard.html"])
PYEOF

echo ""
echo "=== Рестарт воркера ==="
# Останавливаем старый
systemctl --user stop agentforge-worker 2>/dev/null || true
pkill -f grok_worker.sh 2>/dev/null || true
pkill -f 'grok.*always-approve' 2>/dev/null || true
sleep 2

# Фикс line endings
sed -i 's/\r$//' "$WORKER"

# Запускаем через systemd
systemctl --user start agentforge-worker
sleep 3

echo "Воркер:"
systemctl --user is-active agentforge-worker
echo ""
tail -5 /home/agx/agentforge/logs/grok_worker.log
echo ""
echo "Grok процессы:"
ps aux | grep 'grok.*always' | grep -v grep | wc -l
echo "=== DONE ==="
