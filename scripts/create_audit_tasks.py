#!/usr/bin/env python3
# PHASE4_REMOVAL_PLAN AGGRESSIVE FINAL DEPRECATION SWEEP: contains "flywheel" only in audit task descriptions for completeness; keep. Marker added.
"""
Создаёт группу задач для комплексного аудита AgentForge.
Каждая задача — отдельный аспект аудита, назначается на разных агентов.
"""

import json
import subprocess
import sys
import tempfile
import urllib.request

API = "http://localhost:9090/tasks"
RUNNER = "agentforge-runner"  # prefers pure-Rust entrypoint (live to gw); falls back to direct HTTP if needed or no binary in PATH

AUDIT_TASKS = [
    # === 1. МЁРТВЫЙ КОД / ДУБЛИКАТЫ ===
    {
        "title": "[АУДИТ-1] Мёртвый код и дубликаты — Python скрипты",
        "description": """Проанализируй ВСЕ Python файлы в /home/eveselove/agentforge/ (root + core/ + scripts/ + bin/).
Найди:
1. Файлы которые НИКОГДА не вызываются (не импортируются, не запускаются из sh/systemd/cron)
2. Дубликаты функциональности (например create_tasks.py vs create_tasks_v2.py vs create_final_100_tasks.py)
3. Legacy код с пометками 'deprecated', 'legacy', 'old', 'TODO: remove'
4. Скрипты которые делают одно и то же разными способами

Формат ответа:
- МЁРТВЫЙ КОД: файл → причина
- ДУБЛИКАТЫ: [файл1, файл2] → что дублируют
- LEGACY: файл → что устарело
- РЕКОМЕНДАЦИЯ: что удалить/объединить""",
        "preferred_agent": "grok",
        "priority": "high",
        "complexity": "complex",
        "tags": ["audit", "dead-code", "python"]
    },
    {
        "title": "[АУДИТ-2] Мёртвый код и дубликаты — Shell скрипты и bin/",
        "description": """Проанализируй ВСЕ shell скрипты: dispatcher.sh, grok_worker.sh, grok_xai_worker.sh, agents/*.sh, bin/*.sh, scripts/*.sh.
Найди:
1. Скрипты которые не вызываются ни из systemd, ни из других скриптов, ни из Python
2. Дубликаты логики (например enable/disable flywheel — сколько скриптов делают одно и то же?)
3. bin/ скрипты которые больше не нужны
4. Hardcoded пути, magic numbers, небезопасные конструкции

Формат: МЁРТВЫЙ КОД / ДУБЛИКАТЫ / ПРОБЛЕМЫ / РЕКОМЕНДАЦИЯ""",
        "preferred_agent": "grok",
        "priority": "high",
        "complexity": "complex",
        "tags": ["audit", "dead-code", "shell"]
    },

    # === 2. АРХИТЕКТУРА И ПОТОКИ ДАННЫХ ===
    {
        "title": "[АУДИТ-3] Архитектура: поток задачи от создания до завершения",
        "description": """Проследи ПОЛНЫЙ путь задачи через систему AgentForge:
1. Создание задачи (API POST /tasks) → task_queue.py
2. Диспатч (dispatcher.sh / antigravity_worker.py / grok_xai_worker.sh) — КТО решает какой агент?
3. Выполнение (grok_runner.sh / agy_runner.sh / gemini_runner.sh)
4. Статус-переходы (pending → dispatched → in_progress → review → done/failed)
5. Мониторинг (watchdog.py)

Нарисуй полную схему. Найди:
- Где задача может "потеряться" (застрять в статусе навсегда)
- Race conditions (два воркера хватают одну задачу)
- Неконсистентные статус-переходы
- Кто обрабатывает ошибки и как

Ключевые файлы: task_queue.py, dispatcher.sh, antigravity_worker.py, watchdog.py, agents/*.sh""",
        "preferred_agent": "auto",
        "priority": "critical",
        "complexity": "complex",
        "tags": ["audit", "architecture", "data-flow"]
    },
    {
        "title": "[АУДИТ-4] Конфликт воркеров: кто перехватывает задачи",
        "description": """КРИТИЧЕСКИЙ ВОПРОС: В системе есть НЕСКОЛЬКО потребителей задач, которые конкурируют:
1. dispatcher.sh — вызывается через POST /tasks/{id}/dispatch
2. antigravity_worker.py — ПОЛЛИТ очередь и сам забирает pending задачи
3. grok_xai_worker.sh — тоже поллит и забирает

Проблема: antigravity_worker.py забирает задачи БЫСТРЕЕ чем dispatcher, и задачи не попадают в tmux-изоляцию.

Проанализируй:
- Как именно каждый потребитель забирает задачи (poll interval, фильтры, claim mechanism)
- Есть ли CAS/lock при claim? Или два воркера могут взять одну задачу?
- Какой должна быть правильная архитектура: один dispatcher или несколько?
- Предложи решение конфликта""",
        "preferred_agent": "grok",
        "priority": "critical",
        "complexity": "complex",
        "tags": ["audit", "architecture", "race-condition"]
    },

    # === 3. SYSTEMD И ИНФРАСТРУКТУРА ===
    {
        "title": "[АУДИТ-5] Systemd сервисы: что запущено, что лишнее, что сломано",
        "description": """Проверь ВСЕ systemd user-сервисы agentforge-*:
Файлы: ~/.config/systemd/user/agentforge-*.service и agentforge-*.timer
Также: /home/eveselove/agentforge/*.service (шаблоны)

Для каждого сервиса:
1. Что он делает (ExecStart)
2. Статус (active/failed/inactive)
3. Нужен ли он вообще?
4. Правильно ли настроен (Restart, WatchdogSec, зависимости)
5. Конфликтует ли с другими сервисами

Особое внимание:
- agentforge-flywheel vs agentforge-worker — это одно и то же?
- agentforge-antigravity — работает ли после наших изменений dispatcher?
- agentforge-builder — что это?
- Логи: journalctl --user -u agentforge-* — есть ли ошибки?""",
        "preferred_agent": "auto",
        "priority": "high",
        "complexity": "high",
        "tags": ["audit", "systemd", "infrastructure"]
    },

    # === 4. RUST GATEWAY И API ===
    {
        "title": "[АУДИТ-6] Rust Gateway: API endpoints, ошибки, производительность",
        "description": """Проанализируй Rust Gateway (gateway/src/main.rs и связанные crates):
1. Какие API endpoints есть? Полный список с методами
2. Есть ли endpoints которые не используются?
3. Как обрабатываются ошибки (panic, unwrap, graceful degradation?)
4. Есть ли rate limiting на уровне gateway?
5. Как gateway взаимодействует с task_queue.py (Python) — это proxy или standalone?
6. Производительность: есть ли блокирующие операции в async контексте?

Файлы: rust/crates/*/src/*.rs, gateway/src/main.rs""",
        "preferred_agent": "grok",
        "priority": "high",
        "complexity": "complex",
        "tags": ["audit", "rust", "api", "gateway"]
    },

    # === 5. ДОКУМЕНТАЦИЯ VS РЕАЛЬНОСТЬ ===
    {
        "title": "[АУДИТ-7] Документация: что устарело, что не соответствует коду",
        "description": """Сверь документацию (docs/*.md) с реальным кодом:
1. AGENTS.md — соответствуют ли описанные процессы реальным?
2. PHASE1/2/3_TASK_BREAKDOWN.md — актуальны ли? Или давно выполнены?
3. Все *_PLAN.md файлы — выполнены или заброшены?
4. REVIEW_CHECKLIST.md — используется ли на практике?
5. BRANCHING_STRATEGY.md — следуют ли ей?

Результат: таблица [документ | статус: актуален/устарел/частично | что исправить]""",
        "preferred_agent": "auto",
        "priority": "medium",
        "complexity": "high",
        "tags": ["audit", "docs", "consistency"]
    },

    # === 6. БЕЗОПАСНОСТЬ И ОШИБКИ ===
    {
        "title": "[АУДИТ-8] Безопасность: секреты, пути, уязвимости",
        "description": """Проверь безопасность AgentForge:
1. Захардкоженные секреты, API ключи, токены в коде (grep для key, token, secret, password, api_key)
2. .env файл — что в нём, не коммитится ли в git?
3. OAuth токены — как хранятся? (~/.grok/auth.json — безопасно?)
4. Curl запросы без HTTPS (http://localhost OK, но есть ли внешние?)
5. Выполнение произвольного кода через task description (injection через $DESC в shell?)
6. Права на файлы — не слишком ли открытые?
7. /tmp usage — безопасно ли? (symlink attacks, race conditions)

Формат: КРИТИЧЕСКОЕ / СРЕДНЕЕ / НИЗКОЕ → описание → fix""",
        "preferred_agent": "grok",
        "priority": "critical",
        "complexity": "complex",
        "tags": ["audit", "security"]
    },

    # === 7. ЧТО МОЖНО ДОБАВИТЬ ===
    {
        "title": "[АУДИТ-9] Улучшения: что добавить для production-ready системы",
        "description": """На основе текущего состояния AgentForge, предложи что добавить:
1. МОНИТОРИНГ: метрики (Prometheus?), алерты, дашборд
2. RETRY LOGIC: как обрабатываются failed задачи? Есть ли retry с backoff?
3. ОЧЕРЕДЬ ПРИОРИТЕТОВ: priority field используется? Как?
4. SCALING: можно ли добавить второй сервер? Как синхронизировать?
5. ТЕСТЫ: есть ли unit/integration тесты? Что нужно протестировать?
6. CI/CD: текущий pipeline достаточен?
7. OBSERVABILITY: трейсинг, structured logging
8. GRACEFUL SHUTDOWN: что происходит при restart? Задачи теряются?

Для каждого предложения: приоритет, сложность, примерный план""",
        "preferred_agent": "auto",
        "priority": "high",
        "complexity": "complex",
        "tags": ["audit", "improvements", "roadmap"]
    },
]

print(f"🔍 Создаю {len(AUDIT_TASKS)} задач аудита AgentForge...")
print("")

created = []
# Prefer Rust entrypoint (agentforge-runner task create --from-file) for full py->rust migration completeness (task-5af0e350)
use_runner = False
try:
    # quick check if runner binary available (in PATH or common rust target)
    subprocess.check_call([RUNNER, "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    use_runner = True
except Exception:
    # fallback to direct (old http path, still works)
    pass

if use_runner:
    # serialize all to temp json array, one call (mass --from-file)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tf:
        json.dump(AUDIT_TASKS, tf)
        tmp_path = tf.name
    try:
        out = subprocess.check_output(
            [RUNNER, "--json", "task", "create", "--from-file", tmp_path],
            stderr=subprocess.STDOUT,
            timeout=30,
        )
        resp = json.loads(out.decode())
        # runner --from-file json returns {"created": N, "ids": [...]}
        ids = resp.get("ids", [])
        for i, task in enumerate(AUDIT_TASKS, 1):
            tid = ids[i-1] if i-1 < len(ids) else "?"
            agent = task["preferred_agent"]
            prio = task["priority"]
            print(f"  ✅ #{i} [{prio:>8}] [{agent:>5}] {task['title']}")
            print(f"     → ID: {str(tid)[:8]}  (via {RUNNER})")
            created.append({"id": tid, "agent": agent, "title": task["title"]})
    except Exception as e:
        print(f"  runner --from-file failed ({e}); falling back to direct HTTP")
        use_runner = False
    finally:
        try:
            import os; os.unlink(tmp_path)
        except Exception:
            pass

if not use_runner:
    # legacy direct path (for when runner not in env yet)
    for i, task in enumerate(AUDIT_TASKS, 1):
        data = json.dumps(task).encode()
        req = urllib.request.Request(API, data=data, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read().decode())
                tid = result.get("id", "?")
                agent = task["preferred_agent"]
                prio = task["priority"]
                print(f"  ✅ #{i} [{prio:>8}] [{agent:>5}] {task['title']}")
                print(f"     → ID: {tid[:8]}")
                created.append({"id": tid, "agent": agent, "title": task["title"]})
        except Exception as e:
            print(f"  ❌ #{i} {task['title']}: {e}")

print("")
print(f"═══════════════════════════════════════════════════════")
print(f"  Создано {len(created)} задач аудита")
print(f"  Grok:  {sum(1 for c in created if c['agent'] == 'grok')}")
print(f"  Auto:  {sum(1 for c in created if c['agent'] == 'auto')}")
print(f"  Просмотр: http://localhost:9090/tasks (or via: {RUNNER} task list --status pending)")
print(f"  (used {'runner --from-file (pure Rust live)' if use_runner else 'direct HTTP fallback'})")
print(f"═══════════════════════════════════════════════════════")
