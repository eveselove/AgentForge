"""
Longitudinal Evaluation History for AgentForge

This module provides simple but effective tracking of benchmark performance over time.
This is one of the key practices that separates good evaluation systems from frontier ones.

History is stored as append-only JSONL per benchmark for simplicity and durability.
"""
import json
import os
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

# Configurable via env for portability, CI, and testing.
# Default: package-local 'history/' directory (much better than hardcoded /home/eveselove/...).
_DEFAULT_HISTORY_DIR = Path(__file__).parent / "history"
HISTORY_DIR = Path(
    os.environ.get("AGENTFORGE_EVAL_HISTORY_DIR", str(_DEFAULT_HISTORY_DIR))
)
HISTORY_DIR.mkdir(parents=True, exist_ok=True)


def _get_history_path(benchmark_id: str) -> Path:
    safe_id = benchmark_id.replace("/", "_").replace("\\", "_")
    return HISTORY_DIR / f"{safe_id}.jsonl"


def record_run(
    benchmark_id: str,
    agent: str,
    outcome: str,
    duration_seconds: float,
    real_task_id: Optional[str] = None,
    mode: str = "simulated",
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """Append a single evaluation run to the history of a benchmark."""
    record = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "benchmark_id": benchmark_id,
        "agent": agent,
        "outcome": outcome,
        "duration_seconds": round(duration_seconds, 1),
        "mode": mode,
        "real_task_id": real_task_id,
    }
    if extra:
        record.update(extra)

    # Phase 1: If PRM data was passed in extra, keep it prominent
    # (runner and export already put prm_* fields into extra when calling record_run)

    path = _get_history_path(benchmark_id)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def load_history(benchmark_id: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """Load recent history for a benchmark (most recent last)."""
    path = _get_history_path(benchmark_id)
    if not path.exists():
        return []

    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except Exception:
                    continue

    if limit:
        records = records[-limit:]

    return records


def get_recent_summary(benchmark_id: str, window: int = 10) -> Dict[str, Any]:
    """Return simple trend statistics for the last N runs.
    Phase 1: also surfaces PRM process quality aggregates when recorded via extra.
    """
    history = load_history(benchmark_id, limit=window)
    if not history:
        return {"runs": 0}

    successes = sum(1 for r in history if r.get("outcome") == "success")
    durations = [r.get("duration_seconds", 0) for r in history if r.get("duration_seconds")]

    # PRM aggregates (if present from runner post-processing)
    prm_scores = [r.get("prm_overall_score") for r in history if r.get("prm_overall_score") is not None]
    avg_prm = round(sum(prm_scores) / len(prm_scores), 3) if prm_scores else None
    low_prm_count = sum(1 for r in history if r.get("prm_overall_score") is not None and r.get("prm_overall_score") < 0.45)

    summary = {
        "runs": len(history),
        "success_rate": round(successes / len(history), 3) if history else 0,
        "avg_duration": round(sum(durations) / len(durations), 1) if durations else None,
        "last_outcome": history[-1].get("outcome") if history else None,
        "trend": _simple_trend([1 if r.get("outcome") == "success" else 0 for r in history]),
    }
    if avg_prm is not None:
        summary["avg_prm_score"] = avg_prm
        summary["low_prm_runs"] = low_prm_count
        summary["prm_trend_hint"] = "low-process" if avg_prm < 0.55 else ("high-process" if avg_prm > 0.72 else "mixed")
    return summary


def _simple_trend(values: List[int]) -> str:
    """Very lightweight trend indicator."""
    if len(values) < 3:
        return "stable"
    recent = sum(values[-3:]) / 3
    older = sum(values[:-3]) / max(len(values) - 3, 1)
    if recent > older + 0.15:
        return "improving"
    if recent < older - 0.15:
        return "declining"
    return "stable"


def get_all_benchmarks_with_history() -> List[str]:
    """Return list of benchmark IDs that have history."""
    return sorted([p.stem for p in HISTORY_DIR.glob("*.jsonl")])