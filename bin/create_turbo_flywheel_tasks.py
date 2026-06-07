#!/usr/bin/env python3
"""
Turbo Flywheel 100% Task Creator
Создаёт пачку высококачественных задач напрямую в БД.
Запуск: python3 bin/create_turbo_flywheel_tasks.py
"""

import sqlite3
import uuid
import datetime
import json

DB_PATH = "/home/eveselove/agentforge/tasks.db"

TASKS = [
    {
        "title": "[Flywheel 100] Жёстко закрепить canonical engine во всех генераторах flywheel_health и манифестов",
        "description": "Пройтись по всем местам генерации flywheel_health.json и evaluation manifests. Заменить все 'MISSING', 'rust_flywheel', старые строки на константу RUST_FLYWHEEL_ENGINE из learning/utils.py. Добавить автоматическую валидацию в ключевых скриптах. Создать отчёт о нарушениях.",
        "priority": "critical",
        "complexity": "complex",
        "preferred_agent": "grok",
        "tags": ["rust-flywheel", "provenance", "hardening"],
    },
    {
        "title": "[Flywheel 100] Усилить phase4_pre_removal_audit.sh жёсткими гейтами provenance",
        "description": "Добавить в bin/phase4_pre_removal_audit.sh обязательные проверки: все flywheel_health используют канонический engine, нет python в provenance для Rust-шагов, отсутствие устаревших flywheel компонентов. Сделать так, чтобы аудит падал при нарушениях.",
        "priority": "high",
        "complexity": "complex",
        "preferred_agent": "grok",
        "tags": ["rust-flywheel", "audit", "provenance"],
    },
    {
        "title": "[Flywheel 100] Создать инструмент массовой генерации задач для завершения Flywheel",
        "description": "Сделать скрипт/механизм, который по RUST_FLYWHEEL_100_SPRINT.md и 100_PERCENT_READINESS_CHECKLIST.md автоматически создаёт хорошо сформулированные задачи с правильным preferred_agent, priority, complexity и тегами. Это позволит поддерживать очередь в турбо-режиме.",
        "priority": "high",
        "complexity": "complex",
        "preferred_agent": "grok",
        "tags": ["agentforge", "task-system", "productivity"],
    },
    {
        "title": "[Infra] Улучшить grok_xai_worker.sh: защита от перерасхода + usage stats",
        "description": "Добавить в grok_xai_worker.sh учёт примерной стоимости, автоматическое снижение приоритета при высоком расходе, возможность ставить daily budget, лучшее логирование использованных моделей и токенов. Писать usage stats в result задачи.",
        "priority": "high",
        "complexity": "complex",
        "preferred_agent": "grok",
        "tags": ["xai", "cost-control", "worker"],
    },
    {
        "title": "[Flywheel 100] Подготовить инфраструктуру 14-дневного soak monitoring",
        "description": "Создать дашборд/скрипты мониторинга ключевых метрик чистого Rust Flywheel (fidelity, shadow, composite, error rate, provenance violations). Определить, какие метрики должны собираться автоматически во время soak.",
        "priority": "high",
        "complexity": "complex",
        "preferred_agent": "grok",
        "tags": ["rust-flywheel", "monitoring", "soak"],
    },
    {
        "title": "[Flywheel 100] Точный список удаления Python flywheel компонентов (Phase 4)",
        "description": "На основе текущего состояния сделать проверяемый список файлов/модулей Python flywheel, которые можно безопасно удалить после доказательства стабильности Rust Flywheel. Разделить по tiers, добавить комментарии в код.",
        "priority": "high",
        "complexity": "complex",
        "preferred_agent": "grok",
        "tags": ["rust-flywheel", "deprecation", "cleanup"],
    },
    {
        "title": "[Worker] Улучшить Dynamic Model Router с учётом загрузки облака и локали",
        "description": "Сделать роутер в grok_worker.sh и grok_xai_worker.sh умнее: учитывать текущую загрузку облачных vs локальных агентов, историческую успешность моделей на похожих задачах. Добавить централизованную конфигурацию.",
        "priority": "medium",
        "complexity": "medium",
        "preferred_agent": "grok",
        "tags": ["routing", "workers", "optimization"],
    },
    {
        "title": "[Docs] Создать TURBO_MODE.md с правилами максимального параллелизма",
        "description": "Описать текущую конфигурацию (локальные + 4+ облачных агента), как правильно ставить задачи под разные типы агентов, когда использовать Jules, как мониторить расход xAI, лучшие практики.",
        "priority": "medium",
        "complexity": "medium",
        "preferred_agent": "grok",
        "tags": ["docs", "turbo-mode", "process"],
    },
]

def create_tasks():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    now = datetime.datetime.utcnow().isoformat()

    created = 0
    for task in TASKS:
        task_id = str(uuid.uuid4())[:8]

        c.execute("""
            INSERT INTO tasks (
                id, title, description, priority, complexity,
                preferred_agent, status, tags,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            task_id,
            task["title"],
            task["description"],
            task["priority"],
            task["complexity"],
            task["preferred_agent"],
            "pending",
            json.dumps(task["tags"]),
            now,
            now
        ))
        created += 1
        print(f"✓ Created: [{task_id}] {task['title'][:65]}...")

    conn.commit()
    conn.close()
    print(f"\n✅ Создано {created} задач в турбо-волне.")

if __name__ == "__main__":
    create_tasks()
