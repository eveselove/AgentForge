#!/usr/bin/env python3
"""
AgentForge Routing Statistics & Health Tool

Показывает текущее распределение задач по агентам.
Очень полезно после рефакторинга маршрутизации (Фаза 1, 2026-06).

!!! AGGRESSIVE FINAL DEPRECATION SWEEP + PHASE 4 PREP (RUST_FULL_MIGRATION_PLAN.md + PHASE4_REMOVAL_PLAN.md) !!!
FLYWHEEL STATS PATHS IN THIS FILE DEPRECATED.
Python flywheel orchestration (including stats reporting for candidates/proposals) deprecated in favor of
agentforge-runner candidate list --json + flywheel health JSON + Rust-native metrics.
All flywheel-related output here is legacy. See utils.is_pure_rust_flywheel() + direct binary.
Full removal order, risks, rollback: PHASE4_REMOVAL_PLAN.md (Tier 1/3).
Non-flywheel routing stats may persist.
"""
import urllib.request
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime

API = "http://localhost:9090"

def fetch_tasks():
    try:
        with urllib.request.urlopen(f"{API}/tasks", timeout=10) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        print(f"❌ Не удалось подключиться к AgentForge API ({API}): {e}")
        sys.exit(1)

def main():
    args = sys.argv[1:]
    json_output = "--json" in args
    stuck_only = "--stuck-only" in args

    tasks = fetch_tasks()

    if not tasks:
        print("Нет задач в системе.")
        return

    # Статистика
    by_assigned = Counter()
    by_preferred = Counter()
    by_status = Counter()

    antigravity_stuck = []
    long_running = []

    now = datetime.now()

    for t in tasks:
        assigned = t.get("assigned_agent") or "none"
        preferred = t.get("preferred_agent") or "auto"
        status = t.get("status", "unknown")

        by_assigned[assigned] += 1
        by_preferred[preferred] += 1
        by_status[status] += 1

        # Ищем проблемы
        if assigned == "antigravity" and status in ("pending", "dispatched", "in_progress"):
            antigravity_stuck.append(t)

        # Долгие задачи
        created = t.get("created_at")
        if created and status in ("dispatched", "in_progress"):
            try:
                created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                age_minutes = (now - created_dt.replace(tzinfo=None)).total_seconds() / 60
                if age_minutes > 120:  # больше 2 часов
                    long_running.append((t, round(age_minutes)))
            except:
                pass

    if json_output:
        print(json.dumps({
            "by_assigned": dict(by_assigned),
            "by_preferred": dict(by_preferred),
            "by_status": dict(by_status),
            "antigravity_stuck_count": len(antigravity_stuck),
            "long_running_count": len(long_running),
        }, indent=2, ensure_ascii=False))
        return

    print("=" * 70)
    print("📊 AgentForge — Статистика маршрутизации (после рефакторинга 2026-06)")
    print("=" * 70)

    print("\nПо назначенному агенту (assigned_agent):")
    for agent, count in sorted(by_assigned.items(), key=lambda x: -x[1]):
        marker = " ← основной" if agent == "grok" else ""
        print(f"  {agent:15} : {count:4}{marker}")

    print("\nПо предпочитаемому агенту (preferred_agent):")
    for agent, count in sorted(by_preferred.items(), key=lambda x: -x[1]):
        marker = ""
        if agent == "antigravity":
            marker = " ← должно быть мало после рефакторинга"
        elif agent == "grok":
            marker = " ← ожидаемо много"
        print(f"  {agent:15} : {count:4}{marker}")

    print("\nПо статусу:")
    for status, count in sorted(by_status.items(), key=lambda x: -x[1]):
        print(f"  {status:15} : {count:4}")

    # Проблемные зоны
    print("\n" + "-" * 70)
    if antigravity_stuck:
        print(f"⚠️  Задач на Antigravity в работе/ожидании: {len(antigravity_stuck)}")
        print("   Рекомендация: запусти fix_antigravity_tasks.py")
        if not stuck_only:
            for t in antigravity_stuck[:5]:
                print(f"     • {t['id'][:8]}  {t['status']:12}  {t['title'][:45]}")
            if len(antigravity_stuck) > 5:
                print(f"     ... и ещё {len(antigravity_stuck)-5}")
    else:
        print("✅ Нет задач, застрявших на Antigravity.")

    if long_running:
        print(f"\n⏳ Долгие задачи (>2ч в dispatched/in_progress): {len(long_running)}")
        for t, age in sorted(long_running, key=lambda x: -x[1])[:5]:
            print(f"     • {t['id'][:8]}  {age:4} мин   {t.get('assigned_agent','?'):12}  {t['title'][:40]}")

    print("\n" + "=" * 70)
    print("Совет: после рефакторинга routing большинство новых задач должно идти на 'grok'.")
    print("См. AGENTFORGE_ROUTING_AND_EXECUTION_REFACTOR_PLAN.md")
    print("=" * 70)

    # === Flywheel Safeguards Metrics (rich export health for safe default Rust Flywheel) ===
    try:
        import json
        from pathlib import Path
        hf = Path("/tmp/agentforge_rust_flywheel/flywheel_health.json")
        if hf.exists():
            h = json.loads(hf.read_text(encoding="utf-8"))
            rich = h.get("rich_exports") or {}
            print("\n🌀 Flywheel Safeguards & Rich Export Health:")
            print(f"  success_rate     : {rich.get('success_rate', 'n/a')}")
            print(f"  error_rate       : {rich.get('error_rate', 'n/a')}")
            print(f"  consec_failures  : {rich.get('consecutive_failures', 0)}")
            print(f"  total_attempts   : {rich.get('total_attempts', 0)}")
            print(f"  last_success     : {rich.get('last_success_iso', rich.get('last_success_unix', 'n/a'))}")
            print(f"  degraded         : {h.get('degraded', False)} (reason: {h.get('degraded_reason', 'n/a')})")
            print(f"  (see watchdog logs + /tmp/.../watchdog_flywheel_status.json for full + auto-suggestions)")
        else:
            print("\n🌀 Flywheel Safeguards: no health snapshot yet (run continuous or post_process with Rust)")
    except Exception:
        print("\n🌀 Flywheel Safeguards: health read error (non-fatal)")

if __name__ == "__main__":
    main()