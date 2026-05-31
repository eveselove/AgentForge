"""
DEPRECATED — Full Rust Migration in Progress (2026-05-31)
=========================================================
This task creation script is legacy Python.

All new task creation logic should move to Rust (either via agentforge-runner CLI
or a future dedicated Rust task service).

See RUST_ONLY_MIGRATION_PLAN.md
"""

import requests
import json

BASE = 'http://localhost:8080'

tasks = [
    {
        'title': 'Auto-Decompose: автоматическая декомпозиция задач',
        'priority': 'high',
        'complexity': 'complex',
        'tags': ['architecture', 'decompose', 'llm'],
        'preferred_agent': 'grok',
        'description': 'При создании complex задачи автоматически разбить на подзадачи через LLM. Добавить POST /tasks/{id}/decompose.'
    },
    {
        'title': 'Agent Code Review: агенты ревьюят друг друга',
        'priority': 'medium',
        'complexity': 'medium',
        'tags': ['review', 'quality', 'a2a'],
        'preferred_agent': 'grok',
        'description': 'После завершения задачи Grok автоматически отправить diff на ревью Jules или второму Grok.'
    },
    {
        'title': 'Dynamic Model Router: выбор модели по сложности',
        'priority': 'medium',
        'complexity': 'medium',
        'tags': ['optimization', 'cost', 'routing'],
        'preferred_agent': 'grok',
        'description': 'Для simple задач использовать быструю модель Flash, для complex мощную Pro/Opus.'
    },
    {
        'title': 'Git Auto-Rollback при CI fail',
        'priority': 'high',
        'complexity': 'simple',
        'tags': ['git', 'ci', 'safety'],
        'preferred_agent': 'grok',
        'description': 'В grok_worker после CI fail автоматически git revert. Main branch никогда не ломается.'
    },
    {
        'title': 'SLA и дедлайны для задач',
        'priority': 'medium',
        'complexity': 'medium',
        'tags': ['sla', 'deadline', 'dashboard'],
        'preferred_agent': 'grok',
        'description': 'Добавить поле deadline в tasks. Watchdog проверяет просрочку. Dashboard показывает оставшееся время.'
    },
    {
        'title': 'Coverage Guard: блок мёржа при падении покрытия',
        'priority': 'medium',
        'complexity': 'medium',
        'tags': ['coverage', 'ci', 'quality'],
        'preferred_agent': 'grok',
        'description': 'В CI добавить cargo tarpaulin. Если coverage упало больше 2 процентов CI fail.'
    },
    {
        'title': 'Benchmark Regression Detection',
        'priority': 'low',
        'complexity': 'medium',
        'tags': ['benchmark', 'performance', 'ci'],
        'preferred_agent': 'grok',
        'description': 'cargo bench до и после. Если регрессия больше 10 процентов CI fail.'
    },
    {
        'title': 'Agent Leaderboard: рейтинг агентов',
        'priority': 'medium',
        'complexity': 'medium',
        'tags': ['metrics', 'dashboard', 'leaderboard'],
        'preferred_agent': 'grok',
        'description': 'GET /leaderboard с рейтингом агентов по скорости, CI pass rate, escalation count.'
    },
    {
        'title': 'RAG по логам: обучение на прошлых задачах',
        'priority': 'medium',
        'complexity': 'complex',
        'tags': ['rag', 'knowledge', 'ai'],
        'preferred_agent': 'grok',
        'description': 'Поиск похожих завершённых задач через text similarity. SQLite FTS5 для полнотекстового поиска.'
    },
    {
        'title': 'Multi-Repo: работа с несколькими репозиториями',
        'priority': 'low',
        'complexity': 'medium',
        'tags': ['multi-repo', 'scale'],
        'preferred_agent': 'grok',
        'description': 'Добавить поле repo в tasks. Grok/Jules работают в указанном репо.'
    },
    {
        'title': 'Auto-PR Merge: автоматический мёрж',
        'priority': 'high',
        'complexity': 'simple',
        'tags': ['git', 'merge', 'automation'],
        'preferred_agent': 'grok',
        'description': 'Если Guardian approved плюс CI passed - автоматически git merge в main.'
    },
    {
        'title': 'Notification Webhooks при событиях',
        'priority': 'medium',
        'complexity': 'medium',
        'tags': ['webhooks', 'notifications', 'integration'],
        'preferred_agent': 'grok',
        'description': 'При смене статуса задачи POST на подписанные URL. Можно подключить Slack, Discord.'
    },
]

# Создаём задачи
print('=== Создание 12 задач в AgentForge ===')
print()
created = 0
for i, task in enumerate(tasks, 1):
    title = task['title']
    try:
        r = requests.post(BASE + '/tasks', json=task, timeout=10)
        if r.status_code in (200, 201):
            data = r.json()
            task_id = data.get('id', 'N/A')
            print(f'[{i}/12] OK: {title} -> id={task_id}')
            created += 1
        else:
            print(f'[{i}/12] FAIL: {title} -> HTTP {r.status_code}: {r.text[:100]}')
    except Exception as e:
        print(f'[{i}/12] ERROR: {title} -> {e}')

print()
print(f'=== Создано: {created}/12 ===')
print()

# Получаем метрики
try:
    r = requests.get(BASE + '/metrics', timeout=10)
    if r.status_code == 200:
        metrics = r.json()
        print('Метрики:')
        print(json.dumps(metrics, indent=2, ensure_ascii=False))
    else:
        print(f'Метрики недоступны: HTTP {r.status_code}')
except Exception as e:
    print(f'Ошибка получения метрик: {e}')
