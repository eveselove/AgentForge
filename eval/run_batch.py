#!/usr/bin/env python3
"""
Simple batch evaluation runner for Phase 0.

Usage:
    python -m agentforge.eval.run_batch
    python -m agentforge.eval.run_batch --agent grok --limit 5
"""
import argparse
import json
from pathlib import Path

from .runner import run_benchmark_task
from .schemas import BenchmarkTask


EVAL_EXAMPLES_DIR = Path(__file__).parent / "examples"


def load_all_examples() -> list[BenchmarkTask]:
    tasks = []
    for f in sorted(EVAL_EXAMPLES_DIR.glob("*.json")):
        with open(f, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        tasks.append(BenchmarkTask(**data))
    return tasks


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent", default="grok", help="Which agent to evaluate")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()

    tasks = load_all_examples()[: args.limit]

    if not tasks:
        print("No benchmark tasks found in examples/. Add some JSON files first.")
        return

    print(f"Running {len(tasks)} benchmark tasks with agent='{args.agent}'...\n")

    results = []
    for task in tasks:
        result = run_benchmark_task(task, agent=args.agent)
        results.append(result)

    # Simple summary
    successes = sum(1 for r in results if r.is_success())
    print("\n" + "=" * 50)
    print(f"Batch complete: {successes}/{len(results)} succeeded")
    print(f"Agent: {args.agent}")
    print("=" * 50)


if __name__ == "__main__":
    main()