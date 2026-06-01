#!/usr/bin/env python3
import sqlite3
import uuid
import datetime
import json

DB_PATH = "/home/agx/agentforge/tasks.db"

new_tasks = [
    {
        "title": "[Flywheel 100] Добавить централизованный бюджет и мониторинг расхода xAI ключей",
        "description": "Создать систему учёта использования токенов по двум ключам (MB2 и MB3). Добавить простой дашборд/скрипт, который показывает текущий расход, оставшиеся лимиты и предупреждает при приближении к лимитам. Интегрировать в grok_xai_worker.sh.",
        "priority": "high",
        "complexity": "complex",
        "preferred_agent": "grok",
        "tags": ["xai", "cost", "monitoring", "multi-key"]
    },
    {
        "title": "[Flywheel 100] Улучшить логирование использования моделей в облачных воркерах",
        "description": "В grok_xai_worker.sh и launch скриптах сделать так, чтобы в результат задачи записывалась использованная модель, количество токенов и примерная стоимость.",
        "priority": "high",
        "complexity": "medium",
        "preferred_agent": "grok",
        "tags": ["workers", "logging", "xai"]
    },
    {
        "title": "[Rust] Рефакторинг task routing для поддержки нескольких облачных ключей",
        "description": "Улучшить систему распределения задач между локальными и облачными агентами. Добавить балансировку нагрузки между MB2 и MB3.",
        "priority": "high",
        "complexity": "complex",
        "preferred_agent": "grok",
        "tags": ["agentforge", "routing", "multi-key"]
    },
    {
        "title": "[Flywheel 100] Создать дашборд текущей загрузки всех агентов",
        "description": "Написать скрипт, который в реальном времени показывает количество запущенных агентов по ключам, какие задачи они выполняют и общую статистику турбо-режима.",
        "priority": "medium",
        "complexity": "medium",
        "preferred_agent": "grok",
        "tags": ["monitoring", "turbo-mode"]
    },
    {
        "title": "[Rust] Продолжить чистку Python вызовов в grok_worker.sh",
        "description": "Продолжить замену Python-вызовов на agentforge-runner в grok_worker.sh и связанных скриптах.",
        "priority": "high",
        "complexity": "medium",
        "preferred_agent": "grok",
        "tags": ["rust-migration", "cleanup"]
    },
    {
        "title": "[Flywheel 100] Актуальный статус готовности 100%",
        "description": "Проанализировать все пункты из RUST_FLYWHEEL_100_SPRINT.md и чеклистов. Сделать актуальный статус + список самых блокирующих задач на ближайшие дни.",
        "priority": "high",
        "complexity": "complex",
        "preferred_agent": "grok",
        "tags": ["docs", "planning", "flywheel-100"]
    },
    {
        "title": "[Worker] Разные профили настроек для MB2 и MB3",
        "description": "Дать возможность задавать разные MIN_COMPLEXITY / FORCE_MULTI_AGENT для каждого ключа.",
        "priority": "medium",
        "complexity": "medium",
        "preferred_agent": "grok",
        "tags": ["workers", "multi-key"]
    },
    {
        "title": "[Docs] Инструкция по работе с двумя xAI ключами",
        "description": "Создать документацию: как правильно использовать два ключа одновременно, рекомендуемые количества воркеров, мониторинг расхода.",
        "priority": "medium",
        "complexity": "medium",
        "preferred_agent": "grok",
        "tags": ["docs", "multi-key", "turbo"]
    },
]

def main():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.datetime.utcnow().isoformat()

    for task in new_tasks:
        task_id = str(uuid.uuid4())[:8]
        c.execute("""
            INSERT INTO tasks (id, title, description, priority, complexity, preferred_agent, status, tags, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            task_id, task["title"], task["description"], task["priority"], task["complexity"],
            task["preferred_agent"], "pending", json.dumps(task["tags"]), now, now
        ))
        print(f"✓ [{task_id}] {task['title'][:55]}...")

    conn.commit()
    conn.close()
    print(f"\n✅ Добавлено {len(new_tasks)} задач во вторую волну.")

if __name__ == "__main__":
    main()
