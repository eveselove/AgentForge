#!/usr/bin/env python3
"""
Trajectory Analyzer for AgentForge Evaluation Framework

This tool analyzes the structured .jsonl logs produced by the runners.
It is a key component for moving from "we run tasks" to "we understand and improve our agents".

!!! AGGRESSIVE FINAL DEPRECATION SWEEP (RUST_FULL_MIGRATION_PLAN.md + PHASE4_REMOVAL_PLAN.md) !!!
This file is CORE EVAL (prm/trajectory analysis) — EXEMPT from Phase 4 Python DEPRECATED (Tier 2 surgical, see docs/JULES_PY_REMOVAL_HANDOFF_f29c675b.md and PHASE4 checklist) orchestration removal.
Only DEPRECATED (Tier 2 surgical, see docs/JULES_PY_REMOVAL_HANDOFF_f29c675b.md and PHASE4 checklist) glue (e.g. in post_process.py, runner.py orchestration entrypoints) is deprecated.
Trajectory analysis for pure eval paths remains fully supported + independent of DEPRECATED (Tier 2 surgical, see docs/JULES_PY_REMOVAL_HANDOFF_f29c675b.md and PHASE4 checklist) proposal/candidate/continuous.
Guard logic + banners apply only to orchestration (see learning/utils.py + PHASE4_* docs for full targets list).
Non-orchestration eval/ is out of Phase 4 DEPRECATED (Tier 2 surgical, see docs/JULES_PY_REMOVAL_HANDOFF_f29c675b.md and PHASE4 checklist) scope (see PLAN exemptions).

Usage:
    python -m agentforge.eval.analyze_trajectories
    python -m agentforge.eval.analyze_trajectories --agent grok --json
"""
import argparse
import json
from collections import defaultdict, Counter
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional
import os

# Configurable via env for portability, CI, and unit testing (critical for testability).
# Default: package-local 'trajectories/' directory (avoids brittle hardcoded absolute path).
_DEFAULT_TRAJECTORIES_DIR = Path(__file__).parent / "trajectories"
TRAJECTORIES_DIR = Path(
    os.environ.get("AGENTFORGE_EVAL_TRAJECTORIES_DIR", str(_DEFAULT_TRAJECTORIES_DIR))
)


def _parse_event_line(line: str) -> Optional[Dict[str, Any]]:
    """Robust parser for our slightly imperfect JSONL logs."""
    line = line.strip()
    if not line:
        return None
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        # Try to fix common malformation: sometimes the last field is a raw object
        # e.g. ... "agent":"grok",{"foo":"bar"}}
        try:
            # Find the last comma before the final object and turn it into a proper key
            if ',"{' in line:
                # Very rough fix for our current logging format
                idx = line.rfind(',{')
                if idx != -1:
                    fixed = line[:idx] + ',"data":' + line[idx+1:]
                    return json.loads(fixed)
        except Exception:
            pass
        return None


def load_trajectories() -> List[Dict[str, Any]]:
    """Legacy flat event loader (for backward compat). Prefer load_trajectory(..., include_prm=True) + modern normalized events for PRM work."""
    events = []
    for file in TRAJECTORIES_DIR.glob("*.jsonl"):
        try:
            with open(file, "r", encoding="utf-8") as f:
                for line in f:
                    event = _parse_event_line(line)
                    if event:
                        events.append(event)
        except Exception:
            continue
    # Also pull modern .json trajectories (normalized) for richer analysis
    try:
        from .trajectory import load_trajectory, find_trajectory_file
        for jf in TRAJECTORIES_DIR.glob("*.json"):
            try:
                t = load_trajectory(jf, include_prm=True)
                # Flatten normalized events for legacy consumers
                for ev in t.get("events", []):
                    ev2 = dict(ev)
                    ev2["task_id"] = t.get("task_id")
                    ev2["agent"] = t.get("agent")
                    events.append(ev2)
            except Exception:
                continue
    except Exception:
        pass
    return events


def analyze(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not events:
        return {"total_events": 0}

    by_task: Dict[str, List[Dict]] = defaultdict(list)
    for e in events:
        task_id = e.get("task_id", "unknown")
        by_task[task_id].append(e)

    stats = {
        "total_tasks": len(by_task),
        "total_events": len(events),
        "event_types": Counter(e.get("type", "unknown") for e in events),
        "by_agent": defaultdict(lambda: {"tasks": 0, "events": 0}),
        "infra_steps": Counter(),
        "rag_usage": 0,
        "hitl_feedback": 0,
        "durations": [],
        "tasks_with_high_infra": [],
        "agent_efficiency": {},
        # Phase 1 PRM placeholders (populated by analyze_prm_quality or cross-call)
        "prm_overall": None,
        "prm_high_quality_steps_total": 0,
        "prm_low_quality_steps_total": 0,
    }

    task_infra_counts = defaultdict(int)
    task_start_times = {}
    task_end_times = {}

    for task_id, task_events in by_task.items():
        agent = task_events[0].get("agent", "unknown") if task_events else "unknown"
        stats["by_agent"][agent]["tasks"] += 1
        stats["by_agent"][agent]["events"] += len(task_events)

        infra_count = 0
        task_durations = []

        for e in task_events:
            etype = e.get("type")
            ts = e.get("ts")

            if etype == "infra_step":
                step = e.get("step", "unknown")
                stats["infra_steps"][step] += 1
                infra_count += 1

            if etype == "rag_context":
                stats["rag_usage"] += 1

            if etype == "hitl_feedback":
                stats["hitl_feedback"] += 1

            if etype == "grok_execution_end":
                duration = e.get("duration_seconds")
                if duration:
                    stats["durations"].append(duration)
                    task_durations.append(duration)

            # Track time windows if possible
            if ts:
                if etype == "task_start":
                    task_start_times[task_id] = ts
                if etype in ("task_finished", "grok_execution_end"):
                    task_end_times[task_id] = ts

        task_infra_counts[task_id] = infra_count

        if infra_count > 4:  # heuristic for "too many infra steps"
            stats["tasks_with_high_infra"].append({
                "task_id": task_id,
                "agent": agent,
                "infra_steps": infra_count
            })

    # Post-process
    stats["by_agent"] = dict(stats["by_agent"])
    stats["event_types"] = dict(stats["event_types"])
    stats["infra_steps"] = dict(stats["infra_steps"])

    if stats["durations"]:
        stats["avg_duration_sec"] = round(sum(stats["durations"]) / len(stats["durations"]), 1)
        stats["max_duration_sec"] = max(stats["durations"])
        stats["min_duration_sec"] = min(stats["durations"])
    else:
        stats["avg_duration_sec"] = None

    # Simple efficiency signal per agent
    for agent, data in stats["by_agent"].items():
        if data["tasks"] > 0:
            # Rough efficiency: events per task (lower can be better if less noise)
            data["events_per_task"] = round(data["events"] / data["tasks"], 1)

    stats["tasks_with_high_infra"] = sorted(
        stats["tasks_with_high_infra"], key=lambda x: -x["infra_steps"]
    )[:5]

    # Phase 1: attach PRM quality aggregates directly into stats (uses modern loader)
    try:
        prm_agg = analyze_prm_quality(TRAJECTORIES_DIR)
        stats["prm"] = prm_agg
        stats["prm_overall"] = prm_agg.get("average_prm_score")
        stats["prm_high_quality_steps_total"] = sum(e.get("num_high_quality_steps",0) for e in [])  # populated via prm
        stats["prm_low_quality_steps_total"] = sum(e.get("num_low_quality_steps",0) for e in [])
    except Exception:
        stats["prm"] = {"error": "prm analysis failed"}

    return stats


def print_report(stats: Dict[str, Any]):
    print("\n" + "=" * 72)
    print("AgentForge — Trajectory Intelligence Report")
    print(f"Generated: {datetime.utcnow().isoformat()}Z")
    print("=" * 72)

    total_tasks = stats.get("total_tasks", 0)
    total_events = stats.get("total_events", 0)

    print(f"\nTasks analyzed: {total_tasks:>5}     Events: {total_events:>6}")

    if stats.get("avg_duration_sec"):
        print(f"Avg duration:   {stats['avg_duration_sec']:>5.1f}s    "
              f"(min: {stats.get('min_duration_sec', 'N/A')}s  max: {stats.get('max_duration_sec', 'N/A')}s)")

    # Event distribution
    print("\n--- Event Distribution ---")
    for etype, count in sorted(stats.get("event_types", {}).items(), key=lambda x: -x[1]):
        pct = (count / total_events * 100) if total_events else 0
        print(f"  {etype:26} {count:5}  ({pct:5.1f}%)")

    # Agent comparison
    print("\n--- Per Agent ---")
    for agent, data in sorted(stats.get("by_agent", {}).items()):
        ep = data.get("events_per_task", "?")
        print(f"  {agent:12} {data['tasks']:3} tasks   {data['events']:4} events   (~{ep} events/task)")

    # Infrastructure insight
    if stats.get("infra_steps"):
        print("\n--- Infrastructure Overhead ---")
        total_infra = sum(stats["infra_steps"].values())
        print(f"  Total infra steps recorded: {total_infra}")
        for step, count in sorted(stats["infra_steps"].items(), key=lambda x: -x[1]):
            print(f"    {step:24} {count:4}")

        if stats.get("tasks_with_high_infra"):
            print("\n  Tasks with unusually high infra steps:")
            for t in stats["tasks_with_high_infra"]:
                print(f"    • {t['task_id'][:8]} ({t['agent']}) — {t['infra_steps']} infra steps")

    # Usage of advanced features
    print(f"\n--- Advanced Features Usage ---")
    print(f"  Tasks that used RAG:            {stats.get('rag_usage', 0)}")
    print(f"  Tasks with HITL feedback:       {stats.get('hitl_feedback', 0)}")

    # Phase 1: PRM Process Quality (first-class in analyzer)
    try:
        prm = stats.get("prm") or {}
        if prm and prm.get("trajectories_analyzed", 0) > 0:
            print("\n--- Process Quality (PRM) ---")
            print(f"  Trajectories scored: {prm.get('trajectories_analyzed')}")
            if prm.get("average_prm_score"):
                print(f"  Average trajectory PRM: {prm['average_prm_score']}")
            if prm.get("average_step_quality"):
                print(f"  Avg per-step quality:   {prm['average_step_quality']} (sample {prm.get('step_quality_distribution_sample_size')})")
            print(f"  High-PRM trajectories:  {prm.get('high_quality_trajectories', 0)}")
            print(f"  Low-PRM trajectories:   {prm.get('low_process_quality_count', 0)} (fragile/brittle risk)")
            if prm.get("high_quality_step_pct") is not None:
                print(f"  Step distribution: High-quality steps ~{prm['high_quality_step_pct']}% | Low ~{prm.get('low_quality_step_pct', '?')}%")
            print(f"  Note: {prm.get('correlation_note', '')}")
    except Exception:
        pass

    # Actionable insights
    print("\n--- Observations & Opportunities ---")
    if stats.get("avg_duration_sec") and stats["avg_duration_sec"] > 300:
        print("  • Average task duration is quite high — consider investigating slow paths.")
    if total_infra > total_tasks * 3:
        print("  • High number of infrastructure steps per task — potential optimization area.")
    if stats.get("rag_usage", 0) < total_tasks * 0.3:
        print("  • Relatively low RAG usage — memory system might be underutilized.")
    prm = stats.get("prm") or {}
    if prm.get("low_process_quality_count", 0) > 0:
        print("  • Low-PRM trajectories detected — run `prm` / `view --prm` on them and improve step-level reasoning.")

    print("\n" + "=" * 72)
    print("This analysis is input for the Learning Flywheel (Phase 1+). PRM = step-level process reward.")
    print("=" * 72 + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="Output raw JSON instead of human report")
    parser.add_argument("--agent", help="Filter by agent")
    args = parser.parse_args()

    events = load_trajectories()

    if args.agent:
        events = [e for e in events if e.get("agent") == args.agent]

    stats = analyze(events)

    if args.json:
        print(json.dumps(stats, indent=2, ensure_ascii=False))
    else:
        print_report(stats)


if __name__ == "__main__":
    main()


# Phase 1: PRM-aware analysis helper (can be used by reports and CLI) - deeply integrated
def analyze_prm_quality(trajectories_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Analyze process quality using the Process Reward Model across trajectories.
    Delivers: average step quality, high/low quality step distribution, correlation hooks with outcome.
    """
    from .prm import ProcessRewardModel
    from .trajectory import load_trajectory
    prm = ProcessRewardModel()

    if trajectories_dir is None:
        trajectories_dir = TRAJECTORIES_DIR

    scores = []
    low_quality = []
    high_quality = []
    step_quality_samples = []
    low_step_count = 0
    high_step_count = 0

    for f in list(trajectories_dir.glob("*.json")) + list(trajectories_dir.glob("*.jsonl")):
        try:
            traj = load_trajectory(f, include_prm=True)
            prm_res = traj.get("prm_result") or prm.score_trajectory(traj)
            if isinstance(prm_res, dict):
                sc = prm_res.get("overall_prm_score")
                step_scores = prm_res.get("step_scores", []) or []
                hi = prm_res.get("num_high_quality_steps", 0)
                lo = prm_res.get("num_low_quality_steps", 0)
            else:
                sc = getattr(prm_res, "overall_prm_score", None)
                step_scores = getattr(prm_res, "step_scores", []) or []
                hi = getattr(prm_res, "num_high_quality_steps", 0)
                lo = getattr(prm_res, "num_low_quality_steps", 0)

            if sc is None:
                continue
            scores.append(sc)
            high_step_count += hi
            low_step_count += lo

            if sc >= 0.75:
                high_quality.append({"file": f.name, "task_id": traj.get("task_id"), "prm_score": round(sc, 3)})
            if sc < 0.45:
                low_quality.append({
                    "file": str(f.name),
                    "task_id": traj.get("task_id"),
                    "prm_score": round(sc, 3),
                    "low_steps": lo
                })

            for ss in step_scores[:15]:
                if isinstance(ss, dict) and "score" in ss:
                    step_quality_samples.append(ss["score"])
        except Exception:
            continue

    avg_step = round(sum(step_quality_samples) / len(step_quality_samples), 3) if step_quality_samples else None
    total_steps = len(step_quality_samples)
    high_pct = round((high_step_count / total_steps * 100), 1) if total_steps > 0 else None
    low_pct = round((low_step_count / total_steps * 100), 1) if total_steps > 0 else None

    corr_note = "Cross-reference results/*.json (prm_overall_score + outcome) for outcome-PRM correlation."
    if scores:
        corr_note = f"PRM distribution ready for correlation analysis ({len(low_quality)} low-PRM trajs)"

    return {
        "trajectories_analyzed": len(scores),
        "average_prm_score": round(sum(scores) / len(scores), 3) if scores else None,
        "average_step_quality": avg_step,
        "high_quality_trajectories": len(high_quality),
        "low_process_quality_count": len(low_quality),
        "low_quality_examples": low_quality[:5],
        "high_quality_examples": high_quality[:3],
        "step_quality_distribution_sample_size": total_steps,
        "high_quality_step_pct": high_pct,
        "low_quality_step_pct": low_pct,
        "correlation_note": corr_note,
        "prm_summary": f"Avg PRM process quality: {sum(scores)/len(scores):.3f if scores else 'N/A'}. High-step%: {high_pct}"
    }