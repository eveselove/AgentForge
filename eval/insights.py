"""
Actionable Insights Generator for AgentForge Evaluation

This module turns raw evaluation + history + trajectory data into clear, prioritized recommendations.
This is one of the highest-leverage capabilities that best teams have.
"""
from collections import Counter
from typing import List, Dict, Any

from .history import get_all_benchmarks_with_history, get_recent_summary
from .analyze_trajectories import load_trajectories, analyze
from .regression import detect_regressions, format_regression
# Phase 1 PRM cross-ref (imported at top for clean patching in tests + usage in PRM insights)
from .generate_evaluation_report import load_evaluation_results


def generate_insights(limit: int = 8) -> List[str]:
    """Return a list of actionable insight strings."""
    insights = []

    # 1. Benchmarks with concerning recent trends
    benchmarks = get_all_benchmarks_with_history()
    declining = []
    for bid in benchmarks:
        s = get_recent_summary(bid, window=6)
        if s.get("trend") == "declining" and s.get("runs", 0) >= 4:
            declining.append(bid)

    if declining:
        insights.append(f"Declining performance detected on: {', '.join(declining[:4])}. Investigate recent changes.")

    # 2. High infrastructure overhead from trajectories
    traj_stats = {}
    try:
        events = load_trajectories()
        traj_stats = analyze(events)
        if traj_stats.get("infra_steps"):
            top_infra = sorted(traj_stats["infra_steps"].items(), key=lambda x: -x[1])[:2]
            total_infra = sum(traj_stats["infra_steps"].values())
            if total_infra > 20:
                insights.append(f"High infrastructure overhead: {top_infra}. Consider optimizing setup steps.")
    except Exception:
        pass

    # 3. Low RAG usage (only if we actually got real trajectory stats)
    try:
        if traj_stats and traj_stats.get("total_tasks", 0) > 0:
            if traj_stats.get("rag_usage", 0) < traj_stats.get("total_tasks", 1) * 0.35:
                insights.append("Relatively low RAG usage across recent tasks. Memory system may be underutilized.")
    except Exception:
        pass

    # 4. Regression detection (new high-value signal)
    try:
        regressions = detect_regressions(threshold=0.12)
        if regressions:
            reg_lines = [format_regression(r) for r in regressions[:3]]
            insights.append("Performance regressions detected: " + "; ".join(reg_lines))
    except Exception:
        pass

    # 5. General success rate signal
    if not insights:
        insights.append("No major red flags in recent data. Keep running evaluations to surface opportunities.")

    # Phase 1 PRM-driven insights (tasks with low process quality despite success etc.)
    try:
        results = load_evaluation_results()
        low_prm_success = [r for r in results
                           if r.get("prm_overall_score") is not None
                           and r.get("prm_overall_score") < 0.5
                           and r.get("outcome") == "success"]
        if low_prm_success:
            ids = ", ".join(r.get("task_id", "?")[:20] for r in low_prm_success[:3])
            insights.append(f"🚨 {len(low_prm_success)} successes with low process quality (PRM<0.5): {ids}. These are brittle — investigate via `view --prm`.")
        low_prm_any = [r for r in results if r.get("prm_overall_score") is not None and r.get("prm_overall_score") < 0.4]
        if len(low_prm_any) >= 3:
            insights.append(f"Multiple trajectories ({len(low_prm_any)}) show critically low step quality. Strong signal for prompt / reasoning improvements.")
    except Exception:
        pass

    return insights[:limit]


def print_insights():
    print("\n=== AgentForge Evaluation Insights ===\n")
    for i, insight in enumerate(generate_insights(), 1):
        print(f"{i}. {insight}")
    print("\n(These insights improve automatically as more evaluation data is collected.)\n")