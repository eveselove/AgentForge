"""
DEPRECATED — Full Rust Migration (2026-05-31)
See RUST_ONLY_MIGRATION_PLAN.md
"""

#!/usr/bin/env python3
"""
Скрипт для исправления задач, которые застряли на Antigravity после рефакторинга routing.

Использование:
    python fix_antigravity_tasks.py --dry-run          # только показать
    python fix_antigravity_tasks.py                    # перевести на grok (кроме deep-analysis)
    python fix_antigravity_tasks.py --force            # перевести ВСЁ, включая deep-analysis

Рекомендуется запускать после изменений в Фазе 1.
"""
import urllib.request
import json
import sys
import argparse

API = "http://localhost:9090"

DEEP_ANALYSIS_TAGS = {"deep-analysis", "architecture-decision", "critical-review", "antigravity-only", "principal-architect"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Только показать, что будет сделано")
    parser.add_argument("--force", action="store_true", help="Перевести даже задачи с тегами глубокого анализа")
    args = parser.parse_args()

    tasks = json.loads(urllib.request.urlopen(f"{API}/tasks").read().decode())

    stuck = []
    for t in tasks:
        if t["status"] not in ("pending", "dispatched", "failed"):
            continue
        agent = (t.get("assigned_agent") or t.get("preferred_agent") or "").lower()
        if agent == "antigravity":
            stuck.append(t)

    if not stuck:
        print("✅ Нет задач, застрявших на Antigravity.")
        return

    print(f"Найдено {len(stuck)} задач на Antigravity:\n")

    to_reassign = []
    for t in stuck:
        tags = set([str(x).lower() for x in (t.get("tags") or [])])
        is_deep = bool(tags & DEEP_ANALYSIS_TAGS)

        action = "SKIP (deep analysis)" if (is_deep and not args.force) else "→ grok"
        print(f"  {t['id'][:8]} | {t['status']:10} | {action:20} | {t['title'][:50]}")

        if not is_deep or args.force:
            to_reassign.append(t)

    if args.dry_run:
        print(f"\n[DRY RUN] Будет переведено: {len(to_reassign)} задач")
        return

    if not to_reassign:
        print("\nНечего переводить.")
        return

    confirm = input(f"\nПеревести {len(to_reassign)} задач на Grok? [y/N]: ").strip().lower()
    if confirm != "y":
        print("Отменено.")
        return

    count = 0
    for t in to_reassign:
        data = json.dumps({
            "preferred_agent": "grok",
            "assigned_agent": "grok",
            "result": "[MIGRATION] Автоматически переведена с Antigravity после рефакторинга routing (Фаза 1)"
        }).encode()

        try:
            req = urllib.request.Request(f"{API}/tasks/{t['id']}", data=data, method="PATCH")
            req.add_header("Content-Type", "application/json")
            urllib.request.urlopen(req)
            count += 1
            print(f"  ✅ {t['id'][:8]} переведена на grok")
        except Exception as e:
            print(f"  ❌ Ошибка с {t['id']}: {e}")

    print(f"\nГотово. Переведено: {count} задач.")
    print("Теперь можно запустить grok_worker, чтобы они подхватились.")


if __name__ == "__main__":
    main()