"""
Suggestion Engine for AgentForge Evaluation

Generates concrete, prioritized recommendations on what to focus on next.
This is the kind of "improvement co-pilot" behavior that best teams have.
"""
from .insights import generate_insights
from .history import get_all_benchmarks_with_history, get_recent_summary
from .analyze_trajectories import load_trajectories, analyze
from .regression import detect_regressions, format_regression
# Phase 1: top-level import for PRM suggestions + test patching
from .generate_evaluation_report import load_evaluation_results


def generate_suggestions(limit: int = 6) -> list[str]:
    """Return prioritized list of concrete next actions."""
    suggestions = []

    # 1. From insights + regressions
    insights = generate_insights()
    for insight in insights[:3]:
        suggestions.append(insight)

    # 2. Declining or low-performing benchmarks + regression detection
    benchmarks = get_all_benchmarks_with_history()
    critical = []
    for bid in benchmarks:
        s = get_recent_summary(bid, window=6)
        if s.get("runs", 0) >= 4:
            if s.get("success_rate", 1.0) < 0.5:
                critical.append((bid, s['success_rate']))
            elif s.get("trend") == "declining":
                suggestions.append(f"Re-run and debug `{bid}` (recent trend is declining).")
            # Simple regression signal
            elif s.get("success_rate", 1.0) < 0.75 and s.get("trend") != "improving":
                suggestions.append(f"Watch `{bid}` — success rate is relatively low ({s['success_rate']*100:.0f}%).")

    if critical:
        critical.sort(key=lambda x: x[1])
        suggestions.insert(0, f"🔴 High priority: Fix performance on `{critical[0][0]}` (only {critical[0][1]*100:.0f}% success recently). Consider re-running it with more debugging.")

    # 3. High infrastructure overhead
    try:
        events = load_trajectories()
        traj = analyze(events)
        if traj.get("infra_steps"):
            top = sorted(traj["infra_steps"].items(), key=lambda x: -x[1])[0]
            if top[1] > 8:
                suggestions.append(f"Consider optimizing the `{top[0]}` step — it is one of the most frequent infrastructure operations.")
    except Exception:
        pass

    # 4. Default useful action
    if len(suggestions) < 3:
        suggestions.append("Consider running a broader set of real benchmarks (especially the ones with least recent data) to get better visibility.")

    # Phase 1: PRM-specific suggestions (e.g. low process quality despite success)
    try:
        results = load_evaluation_results()
        low_prm_but_success = [r for r in results if r.get("prm_overall_score") is not None and r.get("prm_overall_score") < 0.5 and r.get("outcome") == "success"]
        if low_prm_but_success:
            bid = low_prm_but_success[0].get("task_id")
            suggestions.insert(0, f"🔴 PRIORITY: Benchmark `{bid}` succeeded but had low PRM process score — replay with `python -m agentforge.eval view {bid} --prm --html` and harden weak steps.")
        very_low_prm = len([r for r in results if r.get("prm_overall_score") is not None and r.get("prm_overall_score") < 0.35])
        if very_low_prm >= 2:
            suggestions.append(f"Fix systematic low-quality steps across {very_low_prm} runs (PRM << 0.4). Add more explicit reasoning checkpoints.")
    except Exception:
        pass

    # Light deduplication (normalize similar messages)
    return _dedup_suggestions(suggestions)[:limit]


def _dedup_suggestions(suggestions: list[str]) -> list[str]:
    """Remove near-duplicate suggestions (simple but effective)."""
    seen = []
    for s in suggestions:
        norm = s.lower().strip()
        # Skip if we already have a very similar message
        if any(norm[:40] in existing.lower() or existing.lower()[:40] in norm for existing in seen):
            continue
        seen.append(s)
    return seen


def print_suggestions():
    print("\n=== Suggested Next Actions ===\n")
    for i, s in enumerate(generate_suggestions(), 1):
        print(f"{i}. {s}")
    print("\n(These suggestions are generated from recent evaluation and trajectory data.)\n")