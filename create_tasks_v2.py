"""
DEPRECATED — Full Rust Migration (2026-05-31)
See RUST_ONLY_MIGRATION_PLAN.md
"""

#!/usr/bin/env python3
"""
Создание задач AgentForge v2 — объединённые рекомендации Grok + Antigravity
Технологии уровня Google/Anthropic/OpenAI для мультиагентной разработки
"""
import urllib.request
import json

API = "http://127.0.0.1:9090"

# Объединённый список: Grok + Antigravity рекомендации
tasks = [
    # === CRITICAL ===
    {
        "title": "OpenTelemetry трейсинг агентских траекторий",
        "description": "Внедрить distributed tracing через OpenTelemetry для каждого LLM-вызова, tool invocation, memory read/write. Записывать полный causal graph с parent-child связями, токенами, латентностью и стоимостью. Интеграция с Langfuse (open-source) для визуализации. Добавить трейсинг в grok_worker.sh и task_queue.py.",
        "priority": "critical",
        "complexity": "complex",
        "tags": ["observability", "tracing", "opentelemetry", "langfuse"],
        "preferred_agent": "grok"
    },
    {
        "title": "Secure Sandbox: gVisor/Firecracker для исполнения агентского кода",
        "description": "Запуск всего агент-генерированного кода внутри изолированных MicroVM/контейнеров с лимитами CPU, RAM, сети, файловой системы. Использовать nsjail или bubblewrap (bwrap) на Jetson ARM64. Все tool-вызовы должны проходить через sandbox с audit trail.",
        "priority": "critical",
        "complexity": "complex",
        "tags": ["security", "sandboxing", "execution", "isolation"],
        "preferred_agent": "grok"
    },
    {
        "title": "Synthetic Environment Simulator для offline тестирования агентов",
        "description": "LLM-powered симулятор, генерирующий реалистичные сценарии: CLI-среды, API-ответы, ошибки сборки. Позволяет прогнать тысячи тестов без реальной инфраструктуры. Создать test_simulator.py с набором сценариев для regression testing агентов перед деплоем.",
        "priority": "critical",
        "complexity": "complex",
        "tags": ["evaluation", "testing", "simulation"],
        "preferred_agent": "grok"
    },
    # === HIGH ===
    {
        "title": "Process Reward Model (PRM) — пошаговое оценивание агентов",
        "description": "Модель, оценивающая качество КАЖДОГО промежуточного шага агента (tool call, reasoning, state transition), а не только финальный результат. Использовать LLM-as-Judge (Gemini/Claude) для scoring каждого шага из логов. Заменить текущий Guardian (grep 'fail') на интеллектуальный PRM-судью.",
        "priority": "high",
        "complexity": "complex",
        "tags": ["evaluation", "reward-models", "llm-judge", "guardian"],
        "preferred_agent": "grok"
    },
    {
        "title": "Mixture-of-Agents (MoA): параллельные решения + агрегатор",
        "description": "Паттерн DeepMind: несколько proposer-агентов генерируют параллельные решения, затем aggregator-агент синтезирует лучший результат. Расширить Arena Mode: вместо 2 агентов — N proposers + 1 judge. Добавить endpoint POST /tasks/{id}/moa с параметром num_proposals.",
        "priority": "high",
        "complexity": "medium",
        "tags": ["orchestration", "moa", "reasoning", "scaling"],
        "preferred_agent": "grok"
    },
    {
        "title": "DSPy: автоматическая оптимизация промптов и параметров",
        "description": "Внедрить DSPy-подобную систему для автоматического тюнинга промптов, few-shot примеров и tool selection логики. Создать optimize_prompts.py, который на основе success/fail истории задач из LanceDB автоматически улучшает шаблоны Skills YAML через Bayesian optimization.",
        "priority": "high",
        "complexity": "medium",
        "tags": ["optimization", "prompts", "dspy", "auto-tune"],
        "preferred_agent": "grok"
    },
    {
        "title": "Dynamic Team Orchestration: иерархические команды агентов",
        "description": "Manager-агент выполняет рекурсивную декомпозицию задач, динамически создаёт/удаляет sub-agents, управляет shared blackboard memory. Добавить в task_queue.py поддержку parent_task_id, subtasks[], team_state. Manager решает когда spawn новый агент vs переиспользовать.",
        "priority": "high",
        "complexity": "medium",
        "tags": ["orchestration", "teams", "delegation", "hierarchy"],
        "preferred_agent": "grok"
    },
    {
        "title": "A/B Testing и Canary Deploy для конфигураций агентов",
        "description": "Traffic splitting между вариантами агентов (разные промпты, модели, skills, memory стратегии). Автоматические статистические тесты на success rate, стоимость, латентность. Добавить POST /experiments/create и автоматическое продвижение победителя.",
        "priority": "high",
        "complexity": "medium",
        "tags": ["deployment", "ab-testing", "experimentation"],
        "preferred_agent": "grok"
    },
    {
        "title": "Cost Tracking: учёт токенов и стоимости по задачам",
        "description": "Парсить вывод grok CLI для подсчёта input/output токенов. Добавить поля cost_usd, tokens_in, tokens_out в tasks DB. Дашборд: график расходов, средняя стоимость задачи по агентам. Бюджетные лимиты с алертами.",
        "priority": "high",
        "complexity": "medium",
        "tags": ["cost", "tokens", "billing", "dashboard"],
        "preferred_agent": "grok"
    },
    # === MEDIUM ===
    {
        "title": "Automated Failure Clustering: таксономия ошибок агентов",
        "description": "Pipeline: собрать все failed траектории → embed через sentence-transformers → кластеризовать (HDBSCAN) → сгенерировать описания failure modes → обновлять taxonomy для целевых фиксов промптов и skills. Использовать LanceDB + memory_helper.py.",
        "priority": "medium",
        "complexity": "medium",
        "tags": ["analysis", "logs", "clustering", "improvement"],
        "preferred_agent": "grok"
    },
    {
        "title": "Trajectory DPO: обучение на successful vs failed traces",
        "description": "Собирать пары (successful_trace, failed_trace) из истории AgentForge. Экспортировать в формат для DPO/KTO fine-tuning. Создать export_trajectories.py для генерации training data из логов агентов. Даже без fine-tuning — использовать для few-shot примеров.",
        "priority": "medium",
        "complexity": "complex",
        "tags": ["optimization", "trajectories", "dpo", "training"],
        "preferred_agent": "grok"
    },
    {
        "title": "A2A Protocol (Google): стандартная межагентная коммуникация",
        "description": "Реализовать Agent2Agent protocol (Google/Linux Foundation) для стандартизированной коммуникации между Grok, Grok-2, Antigravity. Agent Card discovery, structured task delegation, OAuth2 auth. Позволит подключать внешних агентов через стандартный API.",
        "priority": "medium",
        "complexity": "complex",
        "tags": ["a2a", "protocol", "interoperability", "google"],
        "preferred_agent": "grok"
    },
    {
        "title": "Dynamic Model Router: автовыбор модели по сложности задачи",
        "description": "Классификатор сложности задачи (simple/medium/complex) на основе tags, description length, history. Simple → Flash (дёшево), Medium → Pro, Complex → Opus/Grok-3. Добавить в grok_worker.sh логику выбора модели перед запуском. Экономия до 70% на токенах.",
        "priority": "medium",
        "complexity": "simple",
        "tags": ["router", "models", "cost-optimization"],
        "preferred_agent": "grok"
    }
]

print(f"Создаю {len(tasks)} задач...")
created = 0
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
        task_id = result.get("id", "?")[:8]
        print(f"  ✅ {task_id} | {t['priority']:>8} | {t['title'][:55]}")
        created += 1
    except Exception as e:
        print(f"  ❌ FAIL: {t['title'][:40]} — {e}")

print(f"\n🚀 Создано: {created}/{len(tasks)} задач")
