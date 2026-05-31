"""
Regression Detection for AgentForge Evaluation

This module provides simple but effective detection of performance regressions
across benchmarks over time. This is a core capability of mature evaluation systems.

A regression is flagged when recent performance is meaningfully worse than the
historical baseline for that benchmark.
"""
from typing import List, Dict, Any, Optional

from .history import load_history, get_recent_summary, get_all_benchmarks_with_history


def detect_regressions(
    benchmark_id: Optional[str] = None,
    window: int = 8,
    baseline_window: int = 20,
    threshold: float = 0.15,
) -> List[Dict[str, Any]]:
    """
    Detect benchmarks that are currently regressing.

    Args:
        benchmark_id: If provided, check only this benchmark.
        window: Number of recent runs to consider as "current".
        baseline_window: Number of older runs to use as baseline.
        threshold: Minimum relative drop in success rate to flag as regression
                   (e.g. 0.15 = 15% worse).

    Returns:
        List of regression reports.
    """
    regressions = []
    benchmarks = [benchmark_id] if benchmark_id else get_all_benchmarks_with_history()

    for bid in benchmarks:
        history = load_history(bid)

        if len(history) < window + 5:
            continue  # Not enough data for reliable comparison

        # Recent window
        recent = history[-window:]
        recent_success = sum(1 for r in recent if r.get("outcome") == "success")
        recent_rate = recent_success / len(recent)

        # Baseline (older runs)
        baseline = history[-(window + baseline_window) : -window] if len(history) > window + baseline_window else history[:-window]
        if not baseline:
            continue

        baseline_success = sum(1 for r in baseline if r.get("outcome") == "success")
        baseline_rate = baseline_success / len(baseline)

        drop = baseline_rate - recent_rate

        if drop >= threshold:
            regressions.append({
                "benchmark_id": bid,
                "baseline_rate": round(baseline_rate, 3),
                "recent_rate": round(recent_rate, 3),
                "absolute_drop": round(drop, 3),
                "drop_percentage": round(drop * 100, 1),
                "relative_drop": round(drop / baseline_rate, 3) if baseline_rate > 0 else 0,
                "recent_runs": len(recent),
                "baseline_runs": len(baseline),
                "severity": round(drop * 100),  # simple 0-100-ish severity for reports
            })

    # Sort by severity (absolute drop)
    regressions.sort(key=lambda x: x["absolute_drop"], reverse=True)
    return regressions


def has_regressions(threshold: float = 0.15) -> bool:
    """Quick check if any regressions exist."""
    return len(detect_regressions(threshold=threshold)) > 0


def format_regression(reg: Dict[str, Any]) -> str:
    """Human-readable one-liner for a regression."""
    return (
        f"{reg['benchmark_id']}: "
        f"{reg['baseline_rate']*100:.0f}% → {reg['recent_rate']*100:.0f}% "
        f"(drop {reg['absolute_drop']*100:.0f}pp / {reg['relative_drop']*100:.0f}%)"
    )