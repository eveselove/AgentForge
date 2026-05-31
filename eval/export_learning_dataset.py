#!/usr/bin/env python3
"""
Minimal Phase 1 Learning Dataset Exporter for AgentForge.

This is the "light bridge" from Phase 0 (evaluation + observability)
to Phase 1 (trajectory learning, PRM, DPO, SFT, critic training).

It turns our existing rich artifacts into clean, ready-to-use training records:

- EvaluationResult (outcome, duration, error, real_task_id, ...)
- Trajectory events (full reasoning traces when available)
- Mappings (link to real AgentForge tasks)
- Longitudinal history (for context)

Usage:
    # Basic export (most common)
    python -m agentforge.eval.export_learning_dataset

    # Rich export with full trajectories (for PRM / critic training)
    python -m agentforge.eval.export_learning_dataset --include-trajectories --output datasets/full_trajectories.jsonl

    # Only real successful runs, recent ones
    python -m agentforge.eval.export_learning_dataset --only-real --only-success --since-days 30

Output format (JSONL):
    Each line is one training example with rich context for learning.
"""

import argparse
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional

from .prm import ProcessRewardModel
from .trajectory import load_trajectory, find_trajectory_file  # Phase 1 canonical loader

# --- Config (respects the same env vars as the rest of eval) ---

_DEFAULT_BASE = Path(__file__).parent

RESULTS_DIR = Path(
    os.environ.get("AGENTFORGE_EVAL_RESULTS_DIR", str(_DEFAULT_BASE / "results"))
)
TRAJECTORIES_DIR = Path(
    os.environ.get("AGENTFORGE_EVAL_TRAJECTORIES_DIR", str(_DEFAULT_BASE / "trajectories"))
)
MAPPINGS_FILE = Path(
    os.environ.get("AGENTFORGE_EVAL_MAPPINGS_DIR", str(_DEFAULT_BASE / "mappings"))
) / "eval_mappings.json"

LEARNING_DATASETS_DIR = Path(
    os.environ.get("AGENTFORGE_EVAL_LEARNING_DIR", str(_DEFAULT_BASE / "learning_datasets"))
)
LEARNING_DATASETS_DIR.mkdir(parents=True, exist_ok=True)


def load_json_safe(path: Path) -> Optional[Dict[str, Any]]:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return None


def load_jsonl_safe(path: Path, max_events: Optional[int] = None) -> List[Dict[str, Any]]:
    events = []
    if not path.exists():
        return events
    try:
        with open(path, "r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                if max_events and i >= max_events:
                    break
                line = line.strip()
                if line:
                    events.append(json.loads(line))
    except Exception:
        pass
    return events


def load_all_results() -> List[Dict[str, Any]]:
    results = []
    for f in sorted(RESULTS_DIR.glob("*.json")):
        data = load_json_safe(f)
        if data:
            data["_source_file"] = str(f)
            results.append(data)
    return results


def get_trajectory_path_for_result(result: Dict[str, Any]) -> Optional[Path]:
    # Preferred: explicit field
    tp = result.get("trajectory_path")
    if tp:
        p = Path(tp)
        if p.exists():
            return p

    # Fallback using the canonical robust helper (supports partial ids + both extensions)
    task_id = result.get("real_task_id") or result.get("task_id", "")
    if task_id:
        p = find_trajectory_file(task_id, TRAJECTORIES_DIR)
        if p:
            return p
    return None


def build_learning_record(result: Dict[str, Any], include_trajectories: bool = False, max_events: int = 200) -> Dict[str, Any]:
    """Turn one EvaluationResult + related artifacts into a learning-ready record."""
    rec = {
        "benchmark_id": result.get("task_id"),
        "agent": result.get("agent"),
        "outcome": result.get("outcome"),
        "duration_seconds": result.get("duration_seconds"),
        "real_task_id": result.get("real_task_id"),
        "evaluated_at": result.get("evaluated_at"),
        "error_message": result.get("error_message"),
        "steps_taken": result.get("steps_taken", 0),
        "cost_usd": result.get("cost_usd", 0.0),
        "quality_score": result.get("quality_score"),
        "judge_notes": result.get("judge_notes"),
        "source_result_file": result.get("_source_file"),
    }

    # Link to trajectory
    traj_path = get_trajectory_path_for_result(result)
    rec["trajectory_path"] = str(traj_path) if traj_path else None

    if include_trajectories and traj_path:
        try:
            # Prefer the canonical robust loader (handles real malformed .jsonl + normalizes)
            loaded = load_trajectory(traj_path, include_prm=False)
            events = loaded.get("events", [])[:max_events]
            rec["trajectory_events"] = events
            rec["trajectory_event_count"] = len(events)
            rec["trajectory_normalized"] = True
        except Exception:
            events = load_jsonl_safe(traj_path, max_events=max_events)
            rec["trajectory_events"] = events
            rec["trajectory_event_count"] = len(events)
    else:
        rec["trajectory_event_count"] = 0

    # Enrich with mapping info if available
    if rec["benchmark_id"] and MAPPINGS_FILE.exists():
        try:
            mappings = json.loads(MAPPINGS_FILE.read_text())
            m = mappings.get(rec["benchmark_id"])
            if m:
                rec["mapping_status"] = m.get("status")
                rec["dispatched_at"] = m.get("dispatched_at")
        except Exception:
            pass

    # Simple derived features useful for learning
    rec["is_success"] = (rec["outcome"] == "success")
    rec["had_error"] = bool(rec.get("error_message"))
    rec["was_real_run"] = bool(rec.get("real_task_id"))

    # Learning value heuristic (higher = more useful for training critics / fixing)
    duration = rec.get("duration_seconds") or 0
    error_bonus = 1.5 if rec["had_error"] else 1.0
    failure_bonus = 2.0 if not rec["is_success"] else 1.0
    rec["learning_value_score"] = round(duration * error_bonus * failure_bonus / 10, 2)

    # Basic signal for future preference learning (success > failed)
    rec["preference_signal"] = "preferred" if rec["is_success"] else "rejected"

    return rec


def export_dataset(
    output_path: Optional[Path] = None,
    include_trajectories: bool = False,
    only_real: bool = False,
    only_success: bool = False,
    only_failed: bool = False,
    since_days: Optional[int] = None,
    max_events_per_traj: int = 200,
    generate_pairs: bool = False,
    with_prm: bool = False,
) -> Dict[str, Any]:
    """Main export function. Returns stats dict."""
    results = load_all_results()

    # Filters
    filtered = []
    cutoff = None
    if since_days:
        cutoff = datetime.utcnow() - timedelta(days=since_days)

    for r in results:
        if only_real and not r.get("real_task_id"):
            continue
        if only_success and r.get("outcome") != "success":
            continue
        if only_failed and r.get("outcome") != "failed":
            continue
        if cutoff:
            ts = r.get("evaluated_at")
            if ts:
                try:
                    if datetime.fromisoformat(ts.replace("Z", "+00:00")) < cutoff:
                        continue
                except Exception:
                    pass
        filtered.append(r)

    # Build records
    records = [
        build_learning_record(r, include_trajectories=include_trajectories, max_events=max_events_per_traj)
        for r in filtered
    ]

    # Optional Process Reward Model scoring (Phase 1) — now powered by robust loader inside PRM
    if with_prm:
        for rec in records:
            traj_path = rec.get("trajectory_path")
            if traj_path and Path(traj_path).exists():
                try:
                    prm_res = ProcessRewardModel().score_trajectory(traj_path)  # str path → robust loader
                    rec["prm_overall_score"] = prm_res.overall_prm_score
                    rec["prm_high_quality_steps"] = prm_res.num_high_quality_steps
                    rec["prm_low_quality_steps"] = prm_res.num_low_quality_steps
                    rec["prm_suggestions"] = prm_res.suggestions_for_improvement

                    # New: emit clean step-level PRM labels (first-class format for training PRMs)
                    if include_trajectories and "trajectory_events" in rec and hasattr(prm_res, "step_scores"):
                        step_labels = []
                        for i, ev in enumerate(rec.get("trajectory_events", [])):
                            step_score = next((s for s in (prm_res.step_scores or []) if getattr(s, "step_index", None) == i), None)
                            if step_score:
                                step_labels.append({
                                    "index": i,
                                    "type": ev.get("type"),
                                    "score": getattr(step_score, "score", None),
                                    "reasons": getattr(step_score, "reasons", []),
                                    "confidence": getattr(step_score, "confidence", None),
                                })
                        if step_labels:
                            rec["prm_step_labels"] = step_labels
                            rec["prm_step_label_count"] = len(step_labels)
                except Exception:
                    pass

    # Output path logic
    if not output_path:
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        suffix = "_pairs" if generate_pairs else ""
        output_path = LEARNING_DATASETS_DIR / f"learning_dataset{suffix}_{ts}.jsonl"

    output_path.parent.mkdir(parents=True, exist_ok=True)

    if generate_pairs:
        pairs = generate_preference_pairs(records)
        with open(output_path, "w", encoding="utf-8") as f:
            for p in pairs:
                f.write(json.dumps(p, ensure_ascii=False) + "\n")

        meta = {
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "total_pairs": len(pairs),
            "note": "Each pair contains 'chosen' (success) and 'rejected' (failure) for DPO-style training",
            "source_records_used": len(records),
            "output": str(output_path),
        }
        meta_path = output_path.with_suffix(".meta.json")
        meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

        print(f"Exported {len(pairs)} preference pairs → {output_path}")
        print(f"Metadata → {meta_path}")
        return {"output": str(output_path), "meta": str(meta_path), "count": len(pairs), "pairs": pairs}

    # Normal flat records export
    with open(output_path, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    meta = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "total_records": len(records),
        "filters": {
            "only_real": only_real,
            "only_success": only_success,
            "only_failed": only_failed,
            "since_days": since_days,
            "include_trajectories": include_trajectories,
        },
        "source_dirs": {
            "results": str(RESULTS_DIR),
            "trajectories": str(TRAJECTORIES_DIR),
        },
        "output": str(output_path),
    }

    meta_path = output_path.with_suffix(".meta.json")
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Exported {len(records)} learning records → {output_path}")
    print(f"Metadata → {meta_path}")

    # Convenience: if user asked for PRM step labels only, also emit a super-clean training file
    if with_prm:
        prm_only_path = output_path.with_name(output_path.stem + "_prm_steps.jsonl")
        prm_records = [r for r in records if r.get("prm_step_labels")]
        if prm_records:
            with open(prm_only_path, "w", encoding="utf-8") as f:
                for r in prm_records:
                    f.write(json.dumps({
                        "benchmark_id": r.get("benchmark_id"),
                        "outcome": r.get("outcome"),
                        "prm_overall": r.get("prm_overall_score"),
                        "steps": r.get("prm_step_labels")
                    }, ensure_ascii=False) + "\n")
            print(f"Also wrote clean PRM step-label training file → {prm_only_path}")

    return {
        "output": str(output_path),
        "meta": str(meta_path),
        "count": len(records),
        "records": records,
    }


def generate_preference_pairs(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Group records by benchmark and create (chosen, rejected) preference pairs.
    This is the core artifact needed for DPO / KTO / preference tuning.

    Only creates pairs for benchmarks that have at least one success and one failure.
    Prioritizes higher learning_value_score examples.
    """
    from collections import defaultdict

    by_benchmark: Dict[str, List[Dict]] = defaultdict(list)
    for r in records:
        bid = r.get("benchmark_id")
        if bid:
            by_benchmark[bid].append(r)

    pairs = []
    for bid, items in by_benchmark.items():
        successes = [r for r in items if r.get("is_success")]
        failures = [r for r in items if not r.get("is_success")]

        if not successes or not failures:
            continue  # Need both sides for a useful preference pair

        # Pick the "best" success and "worst" failure by learning value
        best_success = max(successes, key=lambda x: x.get("learning_value_score", 0))
        worst_failure = max(failures, key=lambda x: x.get("learning_value_score", 0))

        pair = {
            "benchmark_id": bid,
            "chosen": {
                "outcome": "success",
                "trajectory_path": best_success.get("trajectory_path"),
                "duration_seconds": best_success.get("duration_seconds"),
                "learning_value_score": best_success.get("learning_value_score"),
                "real_task_id": best_success.get("real_task_id"),
            },
            "rejected": {
                "outcome": "failed",
                "trajectory_path": worst_failure.get("trajectory_path"),
                "duration_seconds": worst_failure.get("duration_seconds"),
                "learning_value_score": worst_failure.get("learning_value_score"),
                "error_message": worst_failure.get("error_message"),
                "real_task_id": worst_failure.get("real_task_id"),
            },
            "pair_quality": round(
                (best_success.get("learning_value_score", 0) + worst_failure.get("learning_value_score", 0)) / 2, 2
            ),
        }
        pairs.append(pair)

    # Sort by pair quality descending (most valuable first)
    pairs.sort(key=lambda x: x.get("pair_quality", 0), reverse=True)
    return pairs


def main():
    parser = argparse.ArgumentParser(description="Export AgentForge evaluation data for trajectory learning / PRM / DPO")
    parser.add_argument("--output", type=Path, help="Output JSONL path (default: learning_datasets/<timestamp>.jsonl)")
    parser.add_argument("--include-trajectories", action="store_true",
                        help="Inline full trajectory events (can be large; good for PRM/critic training)")
    parser.add_argument("--max-events", type=int, default=200,
                        help="Max events per trajectory when --include-trajectories (default 200)")
    parser.add_argument("--only-real", action="store_true", help="Export only real (non-simulated) runs")
    parser.add_argument("--only-success", action="store_true", help="Export only successful runs")
    parser.add_argument("--only-failed", action="store_true", help="Export only failed runs")
    parser.add_argument("--since-days", type=int, help="Only include runs from the last N days")
    parser.add_argument("--generate-pairs", action="store_true",
                        help="Export preference pairs (chosen success vs rejected failure) for DPO/KTO training")
    parser.add_argument("--with-prm", action="store_true",
                        help="Compute Process Reward Model scores for trajectories (Phase 1)")

    args = parser.parse_args()

    export_dataset(
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


if __name__ == "__main__":
    main()
