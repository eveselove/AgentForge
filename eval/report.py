"""
Results Aggregator and Reporter for AgentForge Evaluation.

This turns raw evaluation runs into actionable insights.
Critical for understanding where agents are strong/weak.
"""
import json
from collections import defaultdict
from pathlib import Path
from typing import List, Dict, Any

from .schemas import EvaluationResult, AgentQualityReport

import os
from pathlib import Path

_DEFAULT_RESULTS_DIR = Path(__file__).parent / "results"
RESULTS_DIR = Path(
    os.environ.get("AGENTFORGE_EVAL_RESULTS_DIR", str(_DEFAULT_RESULTS_DIR))
)


def load_all_results() -> List[EvaluationResult]:
    results = []
    for f in RESULTS_DIR.glob("*.json"):
        try:
            with open(f, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            results.append(EvaluationResult(**data))
        except Exception as e:
            print(f"Warning: failed to load {f}: {e}")
    return results


def generate_agent_report(results: List[EvaluationResult], agent: str) -> AgentQualityReport:
    agent_results = [r for r in results if r.agent == agent]
    if not agent_results:
        raise ValueError(f"No results for agent '{agent}'")

    total = len(agent_results)
    successes = sum(1 for r in agent_results if r.is_success())
    success_rate = successes / total if total > 0 else 0.0

    avg_duration = sum(r.duration_seconds for r in agent_results) / total
    avg_cost = sum(r.cost_usd for r in agent_results) / total
    avg_steps = sum(r.steps_taken for r in agent_results) / total
    total_cost = sum(r.cost_usd for r in agent_results)

    return AgentQualityReport(
        agent=agent,
        total_tasks=total,
        success_rate=round(success_rate, 3),
        avg_duration_seconds=round(avg_duration, 1),
        avg_cost_usd=round(avg_cost, 4),
        avg_steps=round(avg_steps, 1),
        total_cost_usd=round(total_cost, 4),
    )


def print_summary(results: List[EvaluationResult]):
    if not results:
        print("No evaluation results found.")
        return

    print("\n" + "=" * 70)
    print("AgentForge Evaluation Summary")
    print("=" * 70)

    by_agent = defaultdict(list)
    for r in results:
        by_agent[r.agent].append(r)

    for agent, agent_results in sorted(by_agent.items()):
        successes = sum(1 for r in agent_results if r.is_success())
        rate = successes / len(agent_results)
        avg_cost = sum(r.cost_usd for r in agent_results) / len(agent_results)
        avg_time = sum(r.duration_seconds for r in agent_results) / len(agent_results)

        print(f"\n{agent.upper():12} | Tasks: {len(agent_results):3} | "
              f"Success: {rate*100:5.1f}% | "
              f"Avg time: {avg_time:6.1f}s | "
              f"Avg cost: ${avg_cost:.4f}")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    results = load_all_results()
    print_summary(results)

    for agent in set(r.agent for r in results):
        try:
            report = generate_agent_report(results, agent)
            print(f"\nDetailed report for {agent}:")
            print(f"  Success rate: {report.success_rate*100:.1f}%")
            print(f"  Avg duration: {report.avg_duration_seconds}s")
            print(f"  Total cost  : ${report.total_cost_usd:.4f}")
        except Exception as e:
            print(f"Could not generate report for {agent}: {e}")