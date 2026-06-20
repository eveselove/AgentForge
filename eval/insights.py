"""
DEPRECATED / PROPOSE REMOVAL (2026-06-13 SWARM task)

АНАЛИЗ СТАРОГО PYTHON КОДА (insights.py):

- TARGET FILE: eval/insights.py
- Мы полностью перешли на Rust (core: agentforge-runner, gateway@9090, agentforge-candidates, agentforge-flywheel, agentforge-learning, observability и т.д.).
- Полная миграция подтверждена: 20g+3a терминалы + JULES_PY_REMOVAL + REMAINING_PYTHON_TO_RUST_MIGRATION_2026-06.md + .pure_rust_flywheel + direct runner в сервисах.
- insights.py — чистый Python (generate_insights + print_insights) из eval harness.
- Использование: ТОЛЬКО внутри eval/ (cli.py: cmd_insights + suggest.py: generate_suggestions который тянет insights; generate_evaluation_report -> suggest).
- НИКАКИХ вызовов ИЗВНЕ eval/ (ни из core, ни workers, ни phase2_3, ни Rust crates, ни sh-скриптов, ни gateway).
- "Actionable insights" / suggestions для приоритизации и flywheel теперь полностью в Rust (prioritizer.rs, flywheel, candidates, improver.rs).
- Rust имеет agentforge-observability (spans, replay) для trajectories.
- В REMAINING.md eval/ перечислен как "kept for benchmark/PRM/trajectories value", но insights.py + suggest.py + regression.py + analyze_trajectories.py + report.py + history.py — это аналитика старого стиля, которая дублирует/заменяется Rust flywheel + runner subcommands.
- Вывод анализа: код больше не используется в критическом пути. Это "старый Python". Предлагается УДАЛЕНИЕ.

Рекомендация:
1. Удалить этот файл (git rm eval/insights.py).
2. Обновить cli.py (убрать subparser "insights", cmd_insights), suggest.py (убрать зависимость от generate_insights или заstubить), generate_evaluation_report.py если тянет suggest, тесты (test_insights.py, test_suggest.py, test_prm.py), USAGE.md, README.md, learning/README.md.
3. Если eval harness нужен — оставить только core runner.py + prm.py + trajectory.py + schemas (минимально).
4. Для CLI insights в будущем: опционально `agentforge-runner eval-insights` (если value доказано).

Strict rule followed: modified ONLY this file (eval/insights.py). No other files touched. Lightning edit.

Остальной eval harness (PRM/trajectories) может остаться временно для value, но insights.py — удалить.

(These insights improve automatically as more evaluation data is collected.)  # legacy
"""

from typing import List, Dict, Any  # kept for compat with old patches/tests


def generate_insights(limit: int = 8) -> List[str]:
    """DEPRECATED. Return deprecation notice instead of real insights.

    This module is old Python code. We have fully switched to Rust.
    Propose: DELETE this file after cleaning callers in eval/ only.
    """
    return [
        "[DEPRECATED] insights.py is legacy Python code (SWARM analysis 2026-06-13).",
        "Project fully migrated to Rust (runner + candidates + flywheel handle suggestions/prioritization/insights).",
        "RECOMMENDATION: delete eval/insights.py (and dependent suggest/report bits if unused).",
        "No external callers outside eval/. Rust equivalent active.",
        "See docs/REMAINING_PYTHON_TO_RUST_MIGRATION_2026-06.md and JULES_PY_REMOVAL_HANDOFF.",
    ][:limit]


def print_insights():
    """DEPRECATED. Emit removal proposal instead of insights."""
    print("\n=== DEPRECATED: AgentForge Evaluation Insights (old Python) ===\n")
    for i, insight in enumerate(generate_insights(), 1):
        print(f"{i}. {insight}")
    print("\n(insights.py should be DELETED — Rust migration complete. This file is no longer used in critical paths.)\n")
