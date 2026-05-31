#!/usr/bin/env python3
"""
AgentForge Evaluation CLI

Convenient command-line interface for the Evaluation Framework.

This is the kind of tooling that makes evaluation a first-class, low-friction activity —
exactly how top agent teams operate.

Usage examples:
    python -m agentforge.eval run lancedb_parser_bottleneck --real --wait --report
    python -m agentforge.eval run-all --real --wait
    python -m agentforge.eval report
    python -m agentforge.eval status
    python -m agentforge.eval analyze --agent grok
"""
import argparse
import os
import sys
import time
from pathlib import Path
from datetime import datetime

from .runner import run_benchmark_task, load_benchmark_task
from .generate_evaluation_report import main as generate_report_main
from .analyze_trajectories import main as analyze_trajectories_main
from .mappings import get_all_mappings
from .history import get_recent_summary, get_all_benchmarks_with_history, load_history
from .insights import print_insights
from .suggest import print_suggestions
from .trajectory_viewer import main as viewer_main  # supports direct call with argv


EXAMPLES_DIR = Path(__file__).parent / "examples"


def _get_all_benchmarks():
    return sorted([p.stem for p in EXAMPLES_DIR.glob("*.json")])


def cmd_run(args):
    """Run a single benchmark task."""
    benchmark_path = EXAMPLES_DIR / f"{args.benchmark}.json"
    if not benchmark_path.exists():
        benchmark_path = Path(args.benchmark)
        if not benchmark_path.exists():
            print(f"Error: Benchmark not found: {args.benchmark}")
            print(f"Available: {', '.join(_get_all_benchmarks())}")
            sys.exit(1)

    task = load_benchmark_task(str(benchmark_path))

    print(f"\n[CLI] Running benchmark: {task.id}")
    print(f"      Real={args.real}, Wait={args.wait}, Agent={args.agent}")

    result = run_benchmark_task(
        task,
        agent=args.agent,
        simulate=not args.real,
        wait=args.wait,
        timeout_minutes=args.timeout,
    )

    print(f"\n[CLI] Final outcome: {result.outcome}")
    if result.real_task_id:
        print(f"[CLI] Real task ID: {result.real_task_id}")

    # Auto-generate report for real + waited runs (excellent default behavior)
    should_report = args.report or (args.real and args.wait)
    if should_report:
        print("\n[CLI] Generating report (auto-triggered)...")
        generate_report_main()


def cmd_run_all(args):
    """Run multiple (or all) benchmarks, optionally in parallel."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    benchmarks = args.benchmarks if args.benchmarks else _get_all_benchmarks()
    concurrency = max(1, args.concurrency)

    print(f"\n[CLI] Running {len(benchmarks)} benchmarks (concurrency={concurrency})...")
    print(f"      Real={args.real}, Wait={args.wait}, Agent={args.agent}")

    def _run_one(name: str):
        benchmark_path = EXAMPLES_DIR / f"{name}.json"
        if not benchmark_path.exists():
            return (name, None, "not found")

        task = load_benchmark_task(str(benchmark_path))
        print(f"  → Starting {task.id}")

        try:
            result = run_benchmark_task(
                task,
                agent=args.agent,
                simulate=not args.real,
                wait=args.wait,
                timeout_minutes=args.timeout,
            )
            return (name, result, None)
        except Exception as e:
            return (name, None, str(e))

    results = []
    if concurrency == 1:
        for name in benchmarks:
            res = _run_one(name)
            results.append(res)
    else:
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            future_to_name = {executor.submit(_run_one, name): name for name in benchmarks}
            for future in as_completed(future_to_name):
                res = future.result()
                results.append(res)

    print("\n[CLI] All runs completed.")

    # Auto-generate report after real waited runs
    should_report = args.report or (args.real and args.wait)
    if should_report:
        print("\n[CLI] Generating combined report (auto-triggered)...")
        generate_report_main()

    # Summary
    print("\n=== Summary ===")
    for name, res, err in results:
        if err:
            print(f"  {name:40} → ERROR: {err}")
        elif res:
            print(f"  {name:40} → {res.outcome}")
        else:
            print(f"  {name:40} → SKIPPED")


def cmd_report(args):
    """Generate evaluation report."""
    sys.argv = ["generate_evaluation_report.py"]
    if args.output:
        sys.argv.extend(["--output", args.output])
    generate_report_main()


def cmd_analyze(args):
    """Analyze trajectories."""
    sys.argv = ["analyze_trajectories.py"]
    if args.agent:
        sys.argv.extend(["--agent", args.agent])
    if args.json:
        sys.argv.append("--json")
    analyze_trajectories_main()


def cmd_view(args):
    """View / replay a trajectory (text or HTML) with optional PRM scores."""
    argv = [args.task_or_file]
    if args.html:
        argv.append("--html")
    if args.prm:
        argv.append("--prm")
    if args.output:
        argv.extend(["--output", str(args.output)])
    viewer_main(argv)


def cmd_status(args):
    """Show status of real evaluation runs."""
    mappings = get_all_mappings()
    if not mappings:
        print("No real evaluation runs found.")
        return

    print("\n=== Active / Recent Real Evaluation Runs ===\n")
    for benchmark_id, info in sorted(mappings.items(), key=lambda x: x[1].get("updated_at", ""), reverse=True):
        print(f"{benchmark_id}")
        print(f"  Real ID   : {info.get('real_task_id')}")
        print(f"  Agent     : {info.get('agent')}")
        print(f"  Status    : {info.get('status', 'unknown')}")
        print(f"  Dispatched: {info.get('dispatched_at', '?')}")
        print(f"  Updated   : {info.get('updated_at', '?')}")
        if info.get("evaluation_result_path"):
            print(f"  Result    : {info['evaluation_result_path']}")
        print()


def cmd_list(args):
    """List available benchmarks."""
    print("Available benchmark tasks:")
    for name in _get_all_benchmarks():
        print(f"  - {name}")


def cmd_history(args):
    """Show historical performance for a benchmark or overall."""
    if args.benchmark:
        summary = get_recent_summary(args.benchmark, window=args.window)
        print(f"\nRecent history for `{args.benchmark}` (last {args.window} runs):")
        if summary.get("runs", 0) == 0:
            print("  No history yet.")
            return
        print(f"  Runs: {summary['runs']}")
        print(f"  Success rate: {summary['success_rate']*100:.1f}%")
        if summary.get("avg_duration"):
            print(f"  Avg duration: {summary['avg_duration']}s")
        print(f"  Trend: {summary.get('trend', 'unknown')}")
        print(f"  Last outcome: {summary.get('last_outcome')}")
        # PRM in history (Phase 1)
        if summary.get("avg_prm_score"):
            print(f"  Avg PRM process quality: {summary['avg_prm_score']} (low-PRM runs: {summary.get('low_prm_runs',0)})")
    else:
        benchmarks = get_all_benchmarks_with_history()
        print(f"\nBenchmarks with history ({len(benchmarks)}):")
        for bid in benchmarks[:15]:
            s = get_recent_summary(bid, window=6)
            trend = s.get("trend", "?")
            prm_str = f" | PRM:{s.get('avg_prm_score','?')}" if s.get("avg_prm_score") else ""
            print(f"  {bid:45} | {s.get('success_rate', 0)*100:5.1f}% over {s.get('runs', 0):2} runs | {trend}{prm_str}")


def cmd_compare(args):
    """Compare recent performance of different agents on the same benchmark."""
    summary = get_recent_summary(args.benchmark, window=args.window)
    print(f"\nComparison for `{args.benchmark}` (last {args.window} runs):")
    if summary.get("runs", 0) == 0:
        print("  No history yet for this benchmark.")
        return

    print(f"  Overall: {summary['success_rate']*100:.1f}% success | Trend: {summary.get('trend')}")
    print("  (Agent-specific breakdown coming in next iteration — currently aggregated)")


def cmd_insights(args):
    """Show actionable insights based on recent evaluation data."""
    if args.json:
        try:
            from .insights import generate_insights
            import json
            print(json.dumps(generate_insights(limit=10), ensure_ascii=False, indent=2))
        except Exception as e:
            print(json.dumps({"error": str(e)}))
    else:
        print_insights()


def cmd_suggest(args):
    """Show prioritized suggestions on what to focus on next."""
    if args.json:
        try:
            from .suggest import generate_suggestions
            import json
            print(json.dumps(generate_suggestions(limit=8), ensure_ascii=False, indent=2))
        except Exception as e:
            print(json.dumps({"error": str(e)}))
    else:
        print_suggestions()


def cmd_dashboard(args):
    """Quick one-screen overview of the current evaluation system health."""
    print("\n" + "=" * 70)
    print("AgentForge Evaluation Dashboard")
    print("=" * 70)

    # Try to get latest report data
    try:
        from .generate_evaluation_report import load_evaluation_results, load_trajectory_stats, fetch_real_tasks_from_mappings
        results = load_evaluation_results()
        traj = load_trajectory_stats()
        real = fetch_real_tasks_from_mappings()

        sim = [r for r in results if r.get("_mode") == "simulated"]
        real_res = [r for r in results if r.get("_mode") == "real"]

        rate_sim = (sum(1 for r in sim if r.get("outcome") == "success") / len(sim) * 100) if sim else 0
        rate_real = (sum(1 for r in real_res if r.get("outcome") == "success") / len(real_res) * 100) if real_res else 0

        print(f"\nSimulated runs: {len(sim):>3}   | Success: {rate_sim:5.1f}%")
        print(f"Real runs:      {len(real_res):>3}   | Success: {rate_real:5.1f}%")

        if traj.get("avg_duration_sec"):
            print(f"Avg duration (trajectories): {traj['avg_duration_sec']}s")

        # Dedicated PRM dashboard integration (Phase 1)
        prm = traj.get("prm") or {}
        if prm.get("average_prm_score"):
            print(f"Process Quality (PRM avg): {prm['average_prm_score']} over {prm.get('trajectories_analyzed', '?')} trajs")
            if prm.get("low_process_quality_count"):
                print(f"  ⚠️ Low-PRM trajectories: {prm['low_process_quality_count']} (use `prm` / `view --prm`)")
            if prm.get("average_step_quality"):
                print(f"  Avg step quality: {prm['average_step_quality']}")

        print(f"\nReal tasks currently tracked: {len(real)}")

        # Quick insights
        print("\n--- Quick Insights ---")
        try:
            from .insights import generate_insights
            ins = generate_insights(limit=3)
            for i, s in enumerate(ins, 1):
                print(f"{i}. {s}")
        except Exception:
            print("Insights not available right now.")

        print("\n" + "=" * 70)
        print("Run `python -m agentforge.eval suggest` for prioritized next actions.")
        print("=" * 70 + "\n")

    except Exception as e:
        print(f"Could not build dashboard: {e}")


def cmd_export(args):
    """Export learning dataset (Phase 1 on-ramp)."""
    from .export_learning_dataset import export_dataset

    result = export_dataset(
        output_path=args.output,
        include_trajectories=args.include_trajectories,
        max_events_per_traj=args.max_events,
        only_real=args.only_real,
        only_success=args.only_success,
        only_failed=args.only_failed,
        since_days=args.since_days,
        generate_pairs=args.generate_pairs,
        with_prm=args.with_prm,
    )
    kind = "pairs" if args.generate_pairs else "records"
    print(f"\n[Export] Done. {result['count']} {kind} ready for learning.")


def cmd_prm(args):
    """Score trajectory with PRM (Phase 1) or run full analysis."""
    from .prm import ProcessRewardModel
    from .analyze_trajectories import analyze_prm_quality
    from pathlib import Path
    import json as json_module

    if getattr(args, "analyze_all", False):
        res = analyze_prm_quality()
        if args.json:
            print(json_module.dumps(res, indent=2, ensure_ascii=False))
        else:
            print("\n=== Process Reward Model Quality Across All Trajectories ===")
            print(f"Trajectories analyzed: {res['trajectories_analyzed']}")
            if res.get("average_prm_score"):
                print(f"Average PRM score: {res['average_prm_score']:.3f}")
            print(f"Low process quality (<0.45): {res['low_process_quality_count']}")
            if res.get("low_quality_examples"):
                print("\nExamples of low process quality:")
                for ex in res["low_quality_examples"]:
                    print(f"  - {ex.get('task_id', ex.get('file'))}: {ex.get('prm_score'):.2f} ({ex.get('low_steps')} low steps)")
        return

    # Single trajectory scoring
    path = Path(args.trajectory)
    if not path.exists():
        candidates = list(Path("/home/agx/agentforge/eval/trajectories").glob(f"*{args.trajectory[:8]}*.json*"))
        if candidates:
            path = candidates[0]
        else:
            print(f"Trajectory not found: {args.trajectory}")
            return

    try:
        use_judge = getattr(args, "llm_judge", False) or (os.environ.get("AGENTFORGE_PRM_USE_LLM_JUDGE", os.environ.get("AGENTFORGE_PRM_LLM_JUDGE", "0")).lower() in ("1","true","yes","on"))
        prm = ProcessRewardModel(use_llm_judge=use_judge)
        # Robust canonical loader (json/jsonl, malformed tolerant, normalized)
        from .trajectory import load_trajectory
        traj = load_trajectory(path, include_prm=False)
        result = prm.score_trajectory(traj)

        if args.json:
            print(json_module.dumps({
                "task_id": result.task_id,
                "overall_prm_score": result.overall_prm_score,
                "high_quality_steps": result.num_high_quality_steps,
                "low_quality_steps": result.num_low_quality_steps,
                "suggestions": result.suggestions_for_improvement
            }, indent=2, ensure_ascii=False))
        else:
            print(f"\n=== Process Reward Model Score ===")
            print(f"Task: {result.task_id}")
            print(f"Overall PRM Score: {result.overall_prm_score:.3f}")
            print(f"High-quality steps: {result.num_high_quality_steps}")
            print(f"Low-quality steps:  {result.num_low_quality_steps}")
            print(f"\nSuggestions:")
            for s in result.suggestions_for_improvement:
                print(f"  - {s}")
            print()
    except Exception as e:
        print(f"Failed to score trajectory: {e}")


def main():
    parser = argparse.ArgumentParser(
        prog="agentforge-eval",
        description="AgentForge Evaluation Framework CLI — high-quality evaluation + Phase 1 observability (PRM, trajectory view, export for learning)"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # run
    run_parser = subparsers.add_parser("run", help="Run a single benchmark")
    run_parser.add_argument("benchmark", help="Benchmark name (without .json)")
    run_parser.add_argument("--real", action="store_true", help="Execute against real AgentForge")
    run_parser.add_argument("--wait", action="store_true", help="Wait for completion (requires --real)")
    run_parser.add_argument("--agent", default="grok", help="Agent to use")
    run_parser.add_argument("--timeout", type=int, default=120, help="Timeout in minutes")
    run_parser.add_argument("--report", action="store_true", help="Generate report after run")
    run_parser.set_defaults(func=cmd_run)

    # run-all
    run_all_parser = subparsers.add_parser("run-all", help="Run multiple benchmarks")
    run_all_parser.add_argument("benchmarks", nargs="*", help="Benchmark names (empty = all)")
    run_all_parser.add_argument("--real", action="store_true")
    run_all_parser.add_argument("--wait", action="store_true")
    run_all_parser.add_argument("--agent", default="grok")
    run_all_parser.add_argument("--timeout", type=int, default=180)
    run_all_parser.add_argument("--report", action="store_true", help="Generate report after all runs")
    run_all_parser.add_argument("--concurrency", type=int, default=1, help="How many benchmarks to run in parallel (default=1)")
    run_all_parser.set_defaults(func=cmd_run_all)

    # report
    report_parser = subparsers.add_parser("report", help="Generate combined evaluation report")
    report_parser.add_argument("--output", help="Custom output path")
    report_parser.set_defaults(func=cmd_report)

    # analyze
    analyze_parser = subparsers.add_parser("analyze", help="Analyze trajectories")
    analyze_parser.add_argument("--agent")
    analyze_parser.add_argument("--json", action="store_true")
    analyze_parser.set_defaults(func=cmd_analyze)

    # view (Phase 1 — trajectory replay + PRM)
    view_parser = subparsers.add_parser("view", help="View/replay a trajectory (text timeline or self-contained HTML)")
    view_parser.add_argument("task_or_file", help="Task ID (partial) or path to .json/.jsonl")
    view_parser.add_argument("--html", action="store_true", help="Generate beautiful offline HTML replay")
    view_parser.add_argument("--prm", action="store_true", help="Attach / compute Process Reward Model scores")
    view_parser.add_argument("--output", type=Path, help="Output HTML path (only with --html)")
    view_parser.set_defaults(func=cmd_view)

    # status
    status_parser = subparsers.add_parser("status", help="Show status of real evaluation runs")
    status_parser.set_defaults(func=cmd_status)

    # list
    list_parser = subparsers.add_parser("list", help="List available benchmarks")
    list_parser.set_defaults(func=cmd_list)

    # history
    history_parser = subparsers.add_parser("history", help="Show performance history and trends")
    history_parser.add_argument("benchmark", nargs="?", help="Specific benchmark (optional)")
    history_parser.add_argument("--window", type=int, default=8, help="Number of recent runs to consider")
    history_parser.set_defaults(func=cmd_history)

    # compare (placeholder for future agent-specific comparison)
    compare_parser = subparsers.add_parser("compare", help="Compare agents on a benchmark (history)")
    compare_parser.add_argument("benchmark")
    compare_parser.add_argument("--window", type=int, default=10)
    compare_parser.set_defaults(func=cmd_compare)

    # insights
    insights_parser = subparsers.add_parser("insights", help="Show actionable insights from recent data")
    insights_parser.add_argument("--json", action="store_true", help="Output as JSON (useful for scripting)")
    insights_parser.set_defaults(func=cmd_insights)

    # suggest (what to do next)
    suggest_parser = subparsers.add_parser("suggest", help="Get prioritized recommendations on what to focus on next")
    suggest_parser.add_argument("--json", action="store_true", help="Output as JSON")
    suggest_parser.set_defaults(func=cmd_suggest)

    # dashboard (quick one-screen health overview)
    dashboard_parser = subparsers.add_parser("dashboard", help="Quick dashboard of current evaluation system health")
    dashboard_parser.set_defaults(func=cmd_dashboard)

    # export (Phase 1 bridge — learning datasets from trajectories + results)
    export_parser = subparsers.add_parser("export", help="Export learning-ready dataset (trajectories + outcomes) for Phase 1 training")
    export_parser.add_argument("--output", type=Path, help="Output JSONL path")
    export_parser.add_argument("--include-trajectories", action="store_true", help="Inline full trajectory events (large, for PRM/critic)")
    export_parser.add_argument("--max-events", type=int, default=200)
    export_parser.add_argument("--only-real", action="store_true")
    export_parser.add_argument("--only-success", action="store_true")
    export_parser.add_argument("--only-failed", action="store_true")
    export_parser.add_argument("--since-days", type=int)
    export_parser.add_argument("--generate-pairs", action="store_true",
                               help="Export DPO-style preference pairs instead of flat records")
    export_parser.add_argument("--with-prm", action="store_true",
                               help="Attach Process Reward Model scores (step-level quality)")
    export_parser.set_defaults(func=cmd_export)

    # prm (Phase 1) — score a trajectory with Process Reward Model
    prm_parser = subparsers.add_parser("prm", help="Score a trajectory with Process Reward Model (step-level quality)")
    prm_parser.add_argument("trajectory", help="Path to trajectory .json or .jsonl, or task_id")
    prm_parser.add_argument("--json", action="store_true", help="Output as JSON")
    prm_parser.add_argument("--analyze-all", action="store_true", help="Analyze PRM quality across all trajectories (no argument needed)")
    prm_parser.add_argument("--llm-judge", action="store_true", help="Enable real LLM-as-Judge (uses grok CLI; env AGENTFORGE_PRM_USE_LLM_JUDGE also works)")
    prm_parser.set_defaults(func=cmd_prm)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()