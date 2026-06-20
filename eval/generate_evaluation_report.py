#!/usr/bin/env python3
"""
Combined Evaluation Report Generator for AgentForge

This tool produces a professional Markdown report that combines:
- Benchmark results (from eval/results/)
- Trajectory insights (from analyze_trajectories)

This is the kind of deliverable that top agent teams use to drive real improvement.

Usage:
    python -m agentforge.eval.generate_evaluation_report
    python -m agentforge.eval.generate_evaluation_report --output reports/my_report.md
"""
import argparse
import json
from datetime import datetime
from pathlib import Path
from collections import defaultdict
from typing import List, Dict, Any
import urllib.request

from .mappings import get_all_mappings
from .history import get_recent_summary, get_all_benchmarks_with_history

import os

_DEFAULT_RESULTS_DIR = Path(__file__).parent / "results"
_DEFAULT_REPORTS_DIR = Path(__file__).parent / "reports"

RESULTS_DIR = Path(
    os.environ.get("AGENTFORGE_EVAL_RESULTS_DIR", str(_DEFAULT_RESULTS_DIR))
)
REPORTS_DIR = Path(
    os.environ.get("AGENTFORGE_EVAL_REPORTS_DIR", str(_DEFAULT_REPORTS_DIR))
)
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

AGENTFORGE_API = "http://localhost:9090"


def calculate_health_score(
    rate_real: float,
    total_real: int,
    rate_sim: float,
    total_sim: int,
    regression_count: int = 0,
    positive_trend_count: int = 0,
) -> tuple[int, str]:
    """Pure function for the rate-based part of Health Score. Easy to test.
    Regression and trend penalties/bonuses can be passed in (pre-computed).
    """
    score = 50
    signals = []

    if rate_real > 0:
        signals.append(rate_real * 0.55)
    if rate_sim > 0:
        signals.append(rate_sim * 0.20)

    if regression_count > 0:
        reg_penalty = min(regression_count * 8, 25)
        signals.append(-reg_penalty)

    if positive_trend_count > 0:
        trend_bonus = min(positive_trend_count * 3, 12)
        signals.append(trend_bonus)

    if signals:
        score = max(0, min(100, int(sum(signals))))

    health = "Strong"
    if score < 65:
        health = "Needs Attention"
    elif score < 82:
        health = "Acceptable"

    return score, health


def determine_key_verdict(score: int, rate_real: float, total_real: int) -> str:
    """Pure function for Key Verdict logic. Easy to test."""
    if score < 65:
        return "Critical: Multiple signals indicate the evaluation loop needs immediate attention."
    if score < 82:
        return "Acceptable, but several clear opportunities for quick wins on regressions and declining trends."
    if rate_real < 80 and total_real > 0:
        return "Strong signals overall, but real-run success rate still has headroom — focus on production reliability."
    return "System is healthy and improving."


def load_evaluation_results() -> List[Dict[str, Any]]:
    results = []
    for f in RESULTS_DIR.glob("*.json"):
        try:
            with open(f, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            # Tag the result as simulated or real
            data["_mode"] = "real" if data.get("real_task_id") else "simulated"
            results.append(data)
        except Exception:
            continue
    return results


def load_trajectory_stats() -> Dict[str, Any]:
    """Run the analyzer and return stats (simple integration for now). Phase 1: includes PRM aggregates when available."""
    try:
        from .analyze_trajectories import load_trajectories, analyze, analyze_prm_quality
        events = load_trajectories()
        base = analyze(events)
        prm_stats = analyze_prm_quality()
        base.update({"prm": prm_stats})
        return base
    except Exception as e:
        return {"error": str(e), "total_tasks": 0}


def fetch_real_tasks_from_mappings() -> List[Dict[str, Any]]:
    """Fetch actual task data from AgentForge for all mapped real tasks."""
    mappings = get_all_mappings()
    real_tasks = []

    for benchmark_id, mapping in mappings.items():
        real_id = mapping.get("real_task_id")
        if not real_id:
            continue
        try:
            req = urllib.request.Request(f"{AGENTFORGE_API}/tasks/{real_id}")
            with urllib.request.urlopen(req, timeout=8) as resp:
                task_data = json.loads(resp.read().decode())
            real_tasks.append({
                "benchmark_id": benchmark_id,
                "real_task_id": real_id,
                "agent": mapping.get("agent"),
                "data": task_data
            })
        except Exception as e:
            real_tasks.append({
                "benchmark_id": benchmark_id,
                "real_task_id": real_id,
                "error": str(e)
            })

    return real_tasks


def generate_report(results: List[Dict], trajectory_stats: Dict) -> str:
    now = datetime.utcnow().isoformat() + "Z"

    # Separate simulated and real results
    simulated_results = [r for r in results if r.get("_mode") == "simulated"]
    real_results = [r for r in results if r.get("_mode") == "real"]

    total_sim = len(simulated_results)
    success_sim = sum(1 for r in simulated_results if r.get("outcome") == "success")
    rate_sim = (success_sim / total_sim * 100) if total_sim > 0 else 0

    total_real = len(real_results)
    success_real = sum(1 for r in real_results if r.get("outcome") == "success")
    rate_real = (success_real / total_real * 100) if total_real > 0 else 0

    real_tasks = fetch_real_tasks_from_mappings()

    lines = []
    lines.append("# AgentForge Evaluation Report")
    lines.append(f"\n**Generated:** {now}")
    lines.append("\n---\n")

    # === Executive Summary (new, high-quality section) ===
    lines.append("## Executive Summary\n")

    # Pre-compute expensive signals (best effort)
    regression_count = 0
    positive_trend_count = 0
    try:
        from .regression import detect_regressions
        regression_count = len(detect_regressions(threshold=0.10))
    except Exception:
        pass
    try:
        from .history import get_all_benchmarks_with_history, get_recent_summary
        hist = get_all_benchmarks_with_history()
        positive_trend_count = sum(
            1 for b in hist if get_recent_summary(b, window=6).get("trend") == "improving"
        )
    except Exception:
        pass

    score, health = calculate_health_score(
        rate_real, total_real, rate_sim, total_sim,
        regression_count=regression_count,
        positive_trend_count=positive_trend_count,
    )
    lines.append(f"**Overall Evaluation Health Score:** **{score}/100** ({health})")
    lines.append("")

    verdict = determine_key_verdict(score, rate_real, total_real)
    lines.append(f"**Key Verdict:** {verdict}")
    lines.append("")

    lines.append(f"- Real runs success rate: **{rate_real:.1f}%** ({total_real} evaluations)")
    lines.append(f"- Simulated runs success rate: **{rate_sim:.1f}%** ({total_sim} evaluations)")

    if trajectory_stats.get("avg_duration_sec"):
        lines.append(f"- Average task duration (from trajectories): **{trajectory_stats['avg_duration_sec']}s**")

    # PRM process quality signal (Phase 1) - FIRST-CLASS CITIZEN: global + per-benchmark
    try:
        prm_scores = [r.get("prm_overall_score") for r in results if r.get("prm_overall_score") is not None]
        if prm_scores:
            avg_prm = sum(prm_scores) / len(prm_scores)
            lines.append(f"- Average Process Quality (PRM): **{avg_prm:.3f}** (from {len(prm_scores)} trajectories)")
            low_prm = [r for r in results if r.get("prm_overall_score") is not None and r.get("prm_overall_score") < 0.45]
            if low_prm:
                lines.append(f"  ⚠️  {len(low_prm)} trajectories had poor process quality (<0.45) — high risk of fragile success or hidden inefficiency.")
            high_prm = [r for r in results if r.get("prm_overall_score") is not None and r.get("prm_overall_score") >= 0.75]
            if high_prm:
                lines.append(f"  🟢 {len(high_prm)} trajectories showed excellent process quality (≥0.75).")
    except Exception:
        pass

    # Quick trend signal
    try:
        from .history import get_all_benchmarks_with_history, get_recent_summary
        hist = get_all_benchmarks_with_history()
        improving = declining = 0
        for b in hist:
            s = get_recent_summary(b, window=6)
            if s.get("trend") == "improving":
                improving += 1
            elif s.get("trend") == "declining":
                declining += 1
        if hist:
            lines.append(f"- Benchmarks with trend data: {len(hist)} | Improving: {improving} | Declining: {declining}")
    except Exception:
        pass

    lines.append("")
    lines.append("---")
    lines.append("")

    # Simulated vs Real Comparison
    lines.append("\n## Simulated vs Real Comparison\n")

    # Group by benchmark
    by_benchmark = defaultdict(lambda: {"sim": [], "real": []})
    for r in results:
        bid = r.get("task_id", "unknown")
        if r.get("_mode") == "simulated":
            by_benchmark[bid]["sim"].append(r)
        else:
            by_benchmark[bid]["real"].append(r)

    # Nice Markdown table
    lines.append("| Benchmark | Simulated | Real | Delta |")
    lines.append("|-----------|-----------|------|-------|")

    for bid, data in sorted(by_benchmark.items()):
        sim = data["sim"]
        real = data["real"]

        if sim:
            s = sim[0]
            s_status = s.get("outcome", "?")
            s_rate = 100 if s_status == "success" else 0
            s_line = f"{s_status} ({s_rate}%)"
        else:
            s_line = "_no data_"

        if real:
            r = real[0]
            r_status = r.get("outcome", "?")
            r_rate = 100 if r_status == "success" else 0
            r_line = f"{r_status} ({r_rate}%)"
            delta = f"{r_rate - s_rate:+d}%" if sim else "—"
        else:
            r_line = "_no real run_"
            delta = "—"

        lines.append(f"| `{bid}` | {s_line} | {r_line} | {delta} |")

    lines.append("")

    # Real Executions Detail
    if real_tasks:
        lines.append("## Real Executions Detail\n")
        for item in real_tasks:
            if "error" in item:
                lines.append(f"- `{item['benchmark_id']}` → `{item['real_task_id']}` — Error: {item['error']}")
                continue

            d = item["data"]
            status = d.get("status", "?")
            result_preview = (d.get("result") or "")[:180].replace("\n", " ")
            lines.append(f"- **{item['benchmark_id']}** → `{item['real_task_id']}` | Status: **{status}**")
            if result_preview:
                lines.append(f"  Result: {result_preview}...")
            lines.append("")

    # Trajectory Insights
    lines.append("## Trajectory Insights\n")
    if trajectory_stats.get("error"):
        lines.append(f"_Could not load trajectory analysis: {trajectory_stats['error']}_")
    else:
        lines.append(f"- Tasks analyzed: {trajectory_stats.get('total_tasks', 0)}")
        lines.append(f"- Total events:   {trajectory_stats.get('total_events', 0)}")

        if trajectory_stats.get("avg_duration_sec"):
            lines.append(f"- Avg duration:   {trajectory_stats['avg_duration_sec']}s")

        if trajectory_stats.get("infra_steps"):
            lines.append("\n**Top infrastructure steps:**")
            for step, count in sorted(trajectory_stats["infra_steps"].items(), key=lambda x: -x[1])[:4]:
                lines.append(f"  - {step}: {count}")

        lines.append(f"\n- RAG used in:  {trajectory_stats.get('rag_usage', 0)} tasks")
        lines.append(f"- HITL in:      {trajectory_stats.get('hitl_feedback', 0)} tasks")

    # === PRM Per-Benchmark Process Quality Trends (FIRST-CLASS, Phase 1) ===
    lines.append("\n## Process Quality Trends (PRM)\n")
    try:
        prm_by_bench: Dict[str, List[float]] = defaultdict(list)
        for r in results:
            bid = r.get("task_id", "unknown")
            sc = r.get("prm_overall_score")
            if sc is not None:
                prm_by_bench[bid].append(sc)

        if prm_by_bench:
            lines.append("| Benchmark | Runs w/ PRM | Avg PRM | High-Q (≥0.75) | Low-Q (<0.45) | Status |")
            lines.append("|-----------|-------------|---------|----------------|---------------|--------|")
            for bid in sorted(prm_by_bench.keys()):
                scores = prm_by_bench[bid]
                avg = sum(scores) / len(scores)
                hi = sum(1 for s in scores if s >= 0.75)
                lo = sum(1 for s in scores if s < 0.45)
                status = "🟢 Excellent" if avg >= 0.72 else ("🔴 Fragile" if avg < 0.5 else "🟡 Mixed")
                lines.append(f"| `{bid}` | {len(scores)} | {avg:.3f} | {hi} | {lo} | {status} |")
            lines.append("")
            lines.append("_PRM (Process Reward Model) measures step-by-step decision quality, not just final outcome. Low PRM on successes = brittle process._")
            lines.append("  Replay any trajectory: `python -m agentforge.eval view <task_id> --prm --html` (beautiful interactive + heatmap).")
        else:
            lines.append("_No PRM scores yet in results. Run benchmarks with real trajectories (and `log_trajectory`) to populate process quality trends._")
    except Exception as e:
        lines.append(f"_PRM trend computation unavailable: {e}_")

        # Phase 1: PRM process quality
        prm_data = trajectory_stats.get("prm", {})
        if prm_data.get("average_prm_score"):
            lines.append(f"\n**Process Quality (PRM):** avg {prm_data['average_prm_score']:.2f} across {prm_data.get('trajectories_with_prm', 0)} trajectories")
            if prm_data.get("low_process_quality_count", 0) > 0:
                lines.append(f"  ⚠️  {prm_data['low_process_quality_count']} trajectories had poor process quality (<0.45)")

    # Longitudinal Trends with simple visualization
    lines.append("\n## Recent Performance Trends (Last 8 runs)\n")
    try:
        from .history import get_all_benchmarks_with_history, get_recent_summary, load_history

        def sparkline(values):
            """Very simple ASCII sparkline for success rates."""
            if not values:
                return ""
            chars = "▁▂▃▄▅▆▇█"
            min_v, max_v = min(values), max(values)
            if max_v == min_v:
                return "█" * len(values)
            return "".join(chars[int((v - min_v) / (max_v - min_v) * (len(chars) - 1))] for v in values)

        history_benchmarks = get_all_benchmarks_with_history()
        if history_benchmarks:
            for bid in history_benchmarks[:5]:
                hist = load_history(bid, limit=8)
                if len(hist) >= 3:
                    rates = []
                    for r in hist:
                        # crude success indicator
                        rates.append(1.0 if r.get("outcome") == "success" else 0.0)

                    summary = get_recent_summary(bid, window=8)
                    trend = summary.get("trend", "stable")
                    symbol = "↑" if trend == "improving" else ("↓" if trend == "declining" else "→")
                    sp = sparkline(rates)
                    lines.append(f"- `{bid}`: {sp}  {summary['success_rate']*100:.0f}% last 8 {symbol} ({trend})")

            # Mermaid trend charts for up to 3 benchmarks with sufficient history (clean & safe)
            mermaid_charts = []
            for bid in history_benchmarks[:3]:
                hist = load_history(bid, limit=8)
                if len(hist) >= 4:
                    recent = hist[-6:]
                    rates = [100 if r.get("outcome") == "success" else 0 for r in recent]
                    dates = [r["timestamp"][:10] for r in recent]
                    values = ",".join(str(r) for r in rates)
                    x_labels = " ".join(f'"{d}"' for d in dates)

                    chart = []
                    chart.append("```mermaid")
                    chart.append("xychart-beta")
                    chart.append(f'    title "{bid} Success Rate Trend"')
                    chart.append(f"    x-axis {x_labels}")
                    chart.append("    y-axis Success % 0 --> 100")
                    chart.append(f"    line [{values}]")
                    chart.append("```")
                    mermaid_charts.append((bid, "\n".join(chart)))

            if mermaid_charts:
                lines.append("")
                lines.append("**Mermaid Trend Charts** (render beautifully on GitHub / Markdown viewers):")
                for bid, chart in mermaid_charts:
                    lines.append(f"\n*Benchmark: `{bid}`*")
                    lines.append(chart)
                lines.append("")
            else:
                lines.append("_Not enough history yet for Mermaid charts. Run more evaluations (with history recording) to populate trends._")
        else:
            lines.append("_Not enough history yet. Run more evaluations to see trends._")
    except Exception:
        lines.append("_History module not available._")

    # === Recommended Next Actions — the heart of the report (categorized, prioritized, frontier-grade) ===
    lines.append("\n## Recommended Next Actions\n")
    lines.append("Prioritized, categorized actions synthesized from regressions, trends, suggestions, and trajectory signals.\n")

    regressions = []
    try:
        from .regression import detect_regressions
        regressions = detect_regressions(threshold=0.12)
    except Exception:
        pass

    suggestions = []
    try:
        from .suggest import generate_suggestions
        suggestions = generate_suggestions(limit=10)
    except Exception:
        pass

    # Category 1: Critical Regressions (always highest priority)
    lines.append("### 🔴 Critical Regressions (investigate immediately)")
    if regressions:
        for reg in regressions[:4]:
            drop_pp = reg.get("drop_percentage", (reg['baseline_rate'] - reg['recent_rate']) * 100)
            sev = reg.get("severity", int(drop_pp))
            lines.append(f"- **{reg['benchmark_id']}**: dropped from {reg['baseline_rate']*100:.0f}% → {reg['recent_rate']*100:.0f}% (drop {drop_pp:.1f} pp, severity={sev})")
            lines.append(f"  → Action: Deep-dive root cause + add regression test case to the benchmark suite.")
    else:
        lines.append("_No regressions detected above threshold. Excellent._")

    # Category 2: Declining Trends
    lines.append("\n### 📉 Declining Trends (watch + reverse)")
    declining_found = False
    try:
        from .history import get_all_benchmarks_with_history, get_recent_summary
        for bid in get_all_benchmarks_with_history():
            s = get_recent_summary(bid, window=6)
            if s.get("trend") == "declining":
                declining_found = True
                lines.append(f"- `{bid}`: {s['success_rate']*100:.0f}% recent success rate — trend is declining.")
        if not declining_found:
            lines.append("_No declining trends in current window._")
    except Exception:
        lines.append("_Trend analysis unavailable._")

    # Category 3: High-Impact Opportunities (from suggest + infra signals)
    lines.append("\n### 🟢 High-Impact Opportunities")
    high_impact = [a for a in suggestions if any(kw in a.lower() for kw in ["infra", "cost", "duration", "rag", "hitl", "overhead", "critical"])]
    if high_impact:
        for a in high_impact[:5]:
            lines.append(f"- {a}")
    else:
        for a in suggestions[:4]:
            lines.append(f"- {a}")
    if not high_impact and not suggestions:
        lines.append("_No high-impact suggestions surfaced this cycle._")

    # Note: Deduplication is now also handled inside generate_suggestions()

    # Phase 1 bridge signal
    try:
        from .export_learning_dataset import LEARNING_DATASETS_DIR
        dataset_count = len(list(LEARNING_DATASETS_DIR.glob("*.jsonl"))) if LEARNING_DATASETS_DIR.exists() else 0
        if dataset_count > 0:
            lines.append(f"- {dataset_count} learning dataset(s) already exported in `{LEARNING_DATASETS_DIR}` — ready for trajectory-based training (PRM/DPO).")
            # Check for pairs
            pair_files = list(LEARNING_DATASETS_DIR.glob("*pairs*.jsonl"))
            if pair_files:
                lines.append(f"  → Preference pairs available ({len(pair_files)} files) — use for DPO/KTO training.")
        else:
            lines.append("- No learning datasets exported yet. Use `python -m agentforge.eval export --generate-pairs` (best for DPO) once you have real runs.")
    except Exception:
        pass

    # Category 4: Quick Wins & Hygiene
    lines.append("\n### ⚡ Quick Wins & Hygiene")
    quick = [a for a in suggestions if a not in high_impact][:3]
    if quick:
        for a in quick:
            lines.append(f"- {a}")
    else:
        lines.append("- Keep running regular eval cycles (`run-all --wait`) to build longitudinal signal.")
        lines.append("- Add 2-3 new real benchmarks from recent hard tasks.")

    # Category 5: Process Quality (PRM) — new first-class signal (Phase 1)
    lines.append("\n### 🧠 Process Quality Alerts (PRM-driven)")
    low_prm_alerts = [r for r in results if r.get("prm_overall_score") is not None and r.get("prm_overall_score") < 0.5]
    success_but_low_prm = [r for r in low_prm_alerts if r.get("outcome") == "success"]
    if success_but_low_prm:
        for r in success_but_low_prm[:3]:
            lines.append(f"- **{r.get('task_id')}**: Success but low PRM ({r.get('prm_overall_score'):.2f}) — fragile win. Use `view {r.get('task_id')} --prm` + debug step quality.")
    elif low_prm_alerts:
        lines.append(f"- {len(low_prm_alerts)} runs with poor process quality (<0.5). Prioritize fixing reasoning/tool selection even on eventual successes.")
    else:
        lines.append("_No low-PRM alerts this cycle. Good — process discipline is holding._")
    lines.append("  → Action: `python -m agentforge.eval prm <task_id>` or `view <id> --prm --html` for detailed step heatmap.")

    lines.append("")

    # Compact Regression Summary Table (if any)
    if regressions:
        lines.append("**Regression Summary Table**")
        lines.append("| Benchmark | Baseline | Recent | Drop | Severity |")
        lines.append("|-----------|----------|--------|------|----------|")
        for reg in regressions[:5]:
            drop_pp = reg.get("drop_percentage", (reg['baseline_rate'] - reg['recent_rate']) * 100)
            sev = reg.get("severity", int(drop_pp))
            lines.append(f"| `{reg['benchmark_id']}` | {reg['baseline_rate']*100:.0f}% | {reg['recent_rate']*100:.0f}% | {drop_pp:.1f}pp | {sev} |")
        lines.append("")

    # Observations (kept concise)
    lines.append("## Key Observations\n")
    obs = []

    if rate_real > 0 and rate_sim > 0:
        diff = rate_real - rate_sim
        if diff > 15:
            obs.append(f"- Real runs are performing **{diff:.0f}% better** than simulation. Good sign (simulation is conservative).")
        elif diff < -15:
            obs.append(f"- Real runs are performing **{abs(diff):.0f}% worse** than simulation — investigate distribution shift or missing env fidelity.")

    if trajectory_stats.get("avg_duration_sec", 0) > 400:
        obs.append("- High average duration detected — profile infra overhead vs pure reasoning time (see `analyze_trajectories`).")

    if trajectory_stats.get("total_tasks", 0) > 0 and trajectory_stats.get("rag_usage", 0) == 0:
        obs.append("- Zero RAG usage in recent trajectories — verify retrieval is wired in the runner.")

    if obs:
        lines.extend(obs)
    else:
        lines.append("_No strong cross-cutting signals this cycle. Run more real evaluations to surface patterns._")

    lines.append("\n---\n")
    lines.append("*Generated by AgentForge Evaluation Framework — part of the continuous improvement loop.*")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", help="Path to save the Markdown report")
    args = parser.parse_args()

    results = load_evaluation_results()
    trajectory_stats = load_trajectory_stats()

    report = generate_report(results, trajectory_stats)

    if args.output:
        out_path = Path(args.output)
    else:
        timestamp = datetime.utcnow().strftime("%Y-%m-%d_%H%M")
        out_path = REPORTS_DIR / f"evaluation_report_{timestamp}.md"

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"Report saved to: {out_path}")
    print("\n" + report[:1500] + "\n... (truncated)")


if __name__ == "__main__":
    main()