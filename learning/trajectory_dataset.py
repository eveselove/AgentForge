"""
!!! AGGRESSIVE FINAL DEPRECATION SWEEP (RUST_FULL_MIGRATION_PLAN.md + PHASE4_REMOVAL_PLAN.md) !!!
trajectory_dataset.py — Python-side data layer for Learning Flywheel orchestration (Phase 2).

!!! AGGRESSIVE FINAL DEPRECATION SWEEP (RUST_FULL_MIGRATION_PLAN.md + PHASE4_REMOVAL_PLAN.md) !!!
DEPRECATED (flywheel orchestration paths). Python flywheel fully deprecated — Phase 4 target.
MIGRATE TO: agentforge-runner flywheel-step (uses native Rust trajectory + export)

Python TrajectoryDataset only for non-flywheel eval + parity during transition.
Guard with Phase 4 hardened:
  from agentforge.learning.utils import is_pure_rust_flywheel

See learning/utils.py + PHASE4_REMOVAL_PLAN.md
All new flywheel data flows go through Rust.

See PHASE4_REMOVAL_PLAN.md (Tier 2 conditional removal, risks, rollback) + PHASE4_REMOVAL_CHECKLIST.md — this file is medium-risk for Phase 4 (may be kept for eval-only or fully removed if Rust covers all).

Production-grade, versioned dataset builder for trajectories + PRM + outcomes.

Pulls from:
- Existing eval results (schemas.EvaluationResult + JSONs)
- Rich trajectories via canonical load_trajectory (with normalized events)
- PRM scores (heuristic or LLM-judge via ProcessRewardModel)
- Longitudinal history
- Exported learning datasets (for incremental builds)

Features:
- Strong filtering (quality, agent, task_type, outcome, prm thresholds, date, real-only)
- Versioning + manifests (reproducible datasets)
- Multiple export formats ready for training:
  * DPO / preference pairs (chosen vs rejected per benchmark)
  * KTO (knowledge-to-outcome style with labels)
  * SFT (supervised fine-tuning jsonl — success trajectories as conversations or completions)
  * PRM step-level labels (for training critics / process reward heads)
  * Flat records (for analysis / ORM)

Pragmatic & fast: reuses eval/ infrastructure heavily. No heavy deps unless you opt-in.

Usage (example):
    from agentforge.learning.trajectory_dataset import TrajectoryDataset, DatasetVersion

    ds = TrajectoryDataset(name="phase2_v1")
    ds.load_from_eval_results(
        min_prm=0.55,
        only_real=True,
        only_success=False,
        agents=["grok"],
    )
    ds = ds.filter_by_quality(min_overall_prm=0.6, min_high_quality_steps=3)

    pairs = ds.export_preference_pairs()
    ds.export_sft_jsonl("/tmp/sft_success.jsonl")
    version = ds.save_versioned(Path("learning_datasets/v1/"))
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable, Literal, Union

# --- Reuse the battle-tested eval stack (Phase 1 foundation) ---
try:
    from agentforge.eval.trajectory import load_trajectory, find_trajectory_file
    from agentforge.eval.prm import ProcessRewardModel, TrajectoryPRMResult
    from agentforge.eval.export_learning_dataset import (
        build_learning_record,
        generate_preference_pairs as _legacy_generate_pairs,
        LEARNING_DATASETS_DIR as EVAL_LEARNING_DIR,
    )
    from agentforge.eval.schemas import EvaluationResult
    from agentforge.eval.history import load_history  # for extra context
except ImportError as e:
    # Allow standalone testing / partial envs
    print(f"[learning] Warning: could not import full eval stack: {e}")
    load_trajectory = None
    ProcessRewardModel = None  # type: ignore

# Config (same env philosophy as eval/)
_DEFAULT_LEARNING_DIR = Path(
    os.environ.get(
        "AGENTFORGE_LEARNING_DIR",
        str(Path(__file__).parent.parent / "eval" / "learning_datasets"),
    )
)
_DEFAULT_LEARNING_DIR.mkdir(parents=True, exist_ok=True)

EVAL_RESULTS_DIR = Path(
    os.environ.get(
        "AGENTFORGE_EVAL_RESULTS_DIR",
        str(Path(__file__).parent.parent / "eval" / "results"),
    )
)
EVAL_TRAJECTORIES_DIR = Path(
    os.environ.get(
        "AGENTFORGE_EVAL_TRAJECTORIES_DIR",
        str(Path(__file__).parent.parent / "eval" / "trajectories"),
    )
)


# --- Unified Outcome normalization (wire core::Outcome into Python bridge) ---
# When loading *real* data (eval results, trajectories, exports, sidecars), we normalize
# to the Rust canonical strings produced by serde for agentforge_core::Outcome
# (Success / Failure / PartialSuccess / Timeout / Cancelled). This guarantees perfect
# roundtrip interop with the unified Rust side (binary exports, flywheel-export, runner).
# Lenient on input (old lowercase "success"/"failed", Rust Display lowercase, typos etc).
# Unknowns fall back to Failure (matches Rust From<&str> lenient behavior).
RUST_CANONICAL_OUTCOMES = ("Success", "Failure", "PartialSuccess", "Timeout", "Cancelled")
_RUST_OUTCOME_MAP = {
    "success": "Success", "succeeded": "Success", "ok": "Success",
    "failure": "Failure", "failed": "Failure", "fail": "Failure",
    "partial": "PartialSuccess", "partial_success": "PartialSuccess", "partialsuccess": "PartialSuccess",
    "timeout": "Timeout", "timed_out": "Timeout",
    "cancelled": "Cancelled", "canceled": "Cancelled", "cancel": "Cancelled",
}

def normalize_outcome_to_rust_canonical(val: Any) -> str:
    """Normalize outcome value to Rust canonical string for unified core::Outcome interop."""
    if val is None:
        return "Failure"
    s = str(val).strip()
    if not s:
        return "Failure"
    key = s.lower().replace(" ", "_").replace("-", "_")
    return _RUST_OUTCOME_MAP.get(key, "Failure")


@dataclass
class TrajectoryRecord:
    """Canonical rich record for learning. One trajectory + rich labels."""
    task_id: str
    benchmark_id: str
    agent: str
    outcome: str  # Success / Failure / PartialSuccess etc (normalized to Rust canonical on creation)
    real_task_id: Optional[str] = None

    # Core signals (Phase 1+)
    prm_overall: Optional[float] = None
    prm_high_quality_steps: Optional[int] = None
    prm_low_quality_steps: Optional[int] = None
    prm_step_labels: Optional[List[Dict[str, Any]]] = None  # [{index, type, score, reasons, ...}]
    prm_suggestions: Optional[List[str]] = None

    # Execution metadata
    duration_seconds: float = 0.0
    steps_taken: int = 0
    tool_calls: int = 0
    cost_usd: float = 0.0
    error_message: Optional[str] = None

    # Rich content
    events: List[Dict[str, Any]] = field(default_factory=list)  # normalized canonical shape
    judge_notes: Optional[str] = None
    quality_score: Optional[float] = None

    # Derived / provenance
    learning_value_score: float = 0.0
    trajectory_path: Optional[str] = None
    evaluated_at: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        # Wire unified: normalize on every construction (real loads, exports, manual, Rust bridge results)
        object.__setattr__(self, "outcome", normalize_outcome_to_rust_canonical(self.outcome))

    def is_high_quality(self, min_prm: float = 0.65) -> bool:
        if self.prm_overall is None:
            return self.outcome == "Success"
        return self.prm_overall >= min_prm and self.outcome == "Success"

    def to_summary(self) -> Dict[str, Any]:
        """Compact version for prompts / few-shot construction."""
        return {
            "task_id": self.task_id,
            "outcome": self.outcome,
            "prm": self.prm_overall,
            "duration": self.duration_seconds,
            "steps": self.steps_taken,
            "cost": self.cost_usd,
            "error": (self.error_message or "")[:200] if self.error_message else None,
            "key_suggestions": (self.prm_suggestions or [])[:2],
        }


@dataclass
class DatasetVersion:
    """Manifest for a saved, reproducible dataset version."""
    name: str
    version: str
    created_at: str
    filters: Dict[str, Any]
    record_count: int
    stats: Dict[str, Any]  # success_rate, avg_prm, by_agent, etc.
    source_hashes: Dict[str, str]  # sha of inputs for reproducibility
    path: str


class TrajectoryDataset:
    """
    High-quality, filterable, versioned collection of TrajectoryRecords.

    The heart of the learning flywheel. Designed to feed DPO, KTO, SFT,
    PRM training, and SkillImprover directly.
    """

    def __init__(self, name: str = "default"):
        self.name = name
        self.records: List[TrajectoryRecord] = []
        self._version_history: List[DatasetVersion] = []
        self.created_at = datetime.utcnow().isoformat() + "Z"

    # ------------------------------------------------------------------
    # INGESTION (the real power — pulls from everything we already have)
    # ------------------------------------------------------------------
    def load_from_eval_results(
        self,
        results_dir: Optional[Path] = None,
        min_prm: Optional[float] = None,
        only_real: bool = False,
        only_success: bool = False,
        only_failed: bool = False,
        agents: Optional[List[str]] = None,
        since_days: Optional[int] = None,
        include_full_trajectories: bool = True,
        max_events: int = 400,
        attach_prm: bool = True,
    ) -> "TrajectoryDataset":
        """
        Bulk load from eval/results/*.json (the canonical source of truth for outcomes).
        Automatically attaches trajectories + PRM via the Phase 1 loaders.
        """
        results_dir = results_dir or EVAL_RESULTS_DIR
        if not results_dir.exists():
            print(f"[TrajectoryDataset] No results dir at {results_dir}")
            return self

        # --- Rust fast path for large sets when AGENTFORGE_USE_RUST=1 ---
        if os.environ.get("AGENTFORGE_USE_RUST") == "1":
            try:
                tmp = load_eval_results_via_rust(results_dir)
                if tmp:
                    before = len(self.records)
                    self.load_from_export_file(tmp, include_events=False)
                    added = len(self.records) - before
                    # apply requested filters post-load (cheap in-mem)
                    if only_real or only_success or only_failed or agents or since_days or min_prm is not None:
                        cutoff = datetime.utcnow() - timedelta(days=since_days) if since_days else None
                        kept = []
                        for r in self.records[before:]:
                            if only_real and not getattr(r, "real_task_id", None): continue
                            norm_o = normalize_outcome_to_rust_canonical(getattr(r, "outcome", ""))
                            if only_success and norm_o != "Success": continue
                            if only_failed and norm_o != "Failure": continue
                            if agents and getattr(r, "agent", None) not in agents: continue
                            if cutoff and getattr(r, "evaluated_at", None):
                                try:
                                    ts = datetime.fromisoformat(getattr(r, "evaluated_at").replace("Z", "+00:00"))
                                    if ts < cutoff: continue
                                except Exception:
                                    pass
                            if min_prm is not None and (getattr(r, "prm_overall", 0) or 0) < min_prm: continue
                            kept.append(r)
                        self.records = self.records[:before] + kept
                    print(f"[TrajectoryDataset] load_from_eval_results used Rust fast path ({len(self.records)-before} records)")
                    return self
            except Exception as e:
                print(f"[TrajectoryDataset] Rust load fast-path error (falling to Python): {e}")
        # --- end Rust fast path ---

        prm = ProcessRewardModel() if (attach_prm and ProcessRewardModel) else None
        cutoff = None
        if since_days:
            cutoff = datetime.utcnow() - timedelta(days=since_days)

        for f in sorted(results_dir.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue

            if only_real and not data.get("real_task_id"):
                continue
            norm_o = normalize_outcome_to_rust_canonical(data.get("outcome"))
            if only_success and norm_o != "Success":
                continue
            if only_failed and norm_o != "Failure":
                continue
            if agents and data.get("agent") not in agents:
                continue
            if cutoff:
                ts = data.get("evaluated_at")
                if ts:
                    try:
                        if datetime.fromisoformat(ts.replace("Z", "+00:00")) < cutoff:
                            continue
                    except Exception:
                        pass

            rec = self._result_to_record(data, include_full_trajectories, max_events, prm)
            if min_prm is not None and (rec.prm_overall or 0) < min_prm:
                continue
            self.records.append(rec)

        print(f"[TrajectoryDataset] Loaded {len(self.records)} records from eval results")
        return self

    def load_from_export_file(
        self, path: Union[str, Path], include_events: bool = True
    ) -> "TrajectoryDataset":
        """Ingest from a previous export_learning_dataset JSONL (flat or pairs) OR rich binary flywheel-export JSON bundle.

        Robustness: handles the richer stats from `agentforge-runner flywheel-export` (per_record_learning_values,
        with Rust-canonical outcomes, durations, learning_values etc from binary).
        """
        p = Path(path)
        if not p.exists():
            print(f"[TrajectoryDataset] Export file not found: {p}")
            return self

        content = p.read_text(encoding="utf-8")
        # Rich bundle JSON (from Rust flywheel-export --format json) ?
        if p.suffix.lower() == ".json" and not content.lstrip().startswith("{"):
            pass  # will treat as jsonl below? no
        try:
            data = json.loads(content)
            if isinstance(data, dict) and "per_record_learning_values" in data:
                # Richer stats from binary export: ingest the per-record for full interop
                for entry in data.get("per_record_learning_values", []):
                    rec_data = entry.get("data", entry) if isinstance(entry, dict) else {}
                    rec = TrajectoryRecord(
                        task_id=rec_data.get("task_id") or rec_data.get("benchmark_id", "unknown"),
                        benchmark_id=rec_data.get("benchmark_id") or rec_data.get("task_id", "unknown"),
                        agent=rec_data.get("agent", "unknown"),
                        outcome=rec_data.get("outcome", "unknown"),
                        prm_overall=rec_data.get("prm_overall"),
                        learning_value=rec_data.get("learning_value"),
                        duration_seconds=rec_data.get("duration_seconds", 0),
                        steps_taken=rec_data.get("steps_taken", 0),
                        metadata={"source": "rust_rich_flywheel_export", "path": str(p)},
                    )
                    self.records.append(rec)
                print(f"[TrajectoryDataset] Ingested richer stats from Rust flywheel-export bundle: +{len(data.get('per_record_learning_values', []))} records")
                # also try pairs if present for compat
                for pair in data.get("preference_pairs", []):
                    for side_key in ("chosen", "rejected"):
                        if side_key in pair:
                            sd = pair[side_key]
                            self.records.append(TrajectoryRecord(
                                task_id=pair.get("benchmark_id", "pair"),
                                benchmark_id=pair.get("benchmark_id", "pair"),
                                agent="unknown",
                                outcome=sd.get("outcome", "unknown"),
                            ))
                return self
        except Exception:
            pass  # fall to jsonl parsing

        for line in content.splitlines():
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except Exception:
                continue

            # Handle both flat records and pair records
            if "chosen" in item and "rejected" in item:
                # Pairs file — add both sides (they will be deduped by task_id later if needed)
                for side, label in [("chosen", "Success"), ("rejected", "Failure")]:
                    side_data = item[side]
                    rec = TrajectoryRecord(
                        task_id=item.get("benchmark_id", "unknown"),
                        benchmark_id=item.get("benchmark_id", "unknown"),
                        agent="unknown",
                        outcome=label,
                        trajectory_path=side_data.get("trajectory_path"),
                        learning_value_score=side_data.get("learning_value_score", 0),
                    )
                    self.records.append(rec)
            else:
                # Flat record
                rec = TrajectoryRecord(
                    task_id=item.get("benchmark_id") or item.get("task_id", "unknown"),
                    benchmark_id=item.get("benchmark_id") or item.get("task_id", "unknown"),
                    agent=item.get("agent", "unknown"),
                    outcome=item.get("outcome", "unknown"),
                    prm_overall=item.get("prm_overall_score"),
                    prm_high_quality_steps=item.get("prm_high_quality_steps"),
                    prm_low_quality_steps=item.get("prm_low_quality_steps"),
                    prm_step_labels=item.get("prm_step_labels"),
                    duration_seconds=item.get("duration_seconds", 0),
                    steps_taken=item.get("steps_taken", 0),
                    cost_usd=item.get("cost_usd", 0),
                    error_message=item.get("error_message"),
                    trajectory_path=item.get("trajectory_path"),
                    evaluated_at=item.get("evaluated_at"),
                    learning_value_score=item.get("learning_value_score", 0),
                    events=item.get("trajectory_events", []) if include_events else [],
                    metadata={"source": "export", "path": str(p)},
                )
                self.records.append(rec)

        print(f"[TrajectoryDataset] Ingested from export: now {len(self.records)} total records")
        return self

    def load_from_trajectories_dir(
        self,
        traj_dir: Optional[Path] = None,
        limit: int = 100,
        attach_sidecar_prm: bool = True,
        only_with_prm: bool = False,
    ) -> "TrajectoryDataset":
        """
        Load directly from eval/trajectories/*.jsonl + *.json , attaching real .prm.json sidecars
        when present (the richest signal for the flywheel: PRM scores + suggestions from farm runs).
        This complements load_from_eval_results (which focuses on result JSONs).
        """
        traj_dir = traj_dir or EVAL_TRAJECTORIES_DIR
        if not traj_dir.exists():
            print(f"[TrajectoryDataset] No trajectories dir: {traj_dir}")
            return self

        # Collect candidate trajectory files (prefer jsonl, recent first)
        cands = []
        for ext in ("*.jsonl", "*.json"):
            cands.extend(traj_dir.glob(ext))
        cands = sorted(cands, key=lambda p: p.stat().st_mtime, reverse=True)[:limit * 2]

        loaded = 0
        for p in cands:
            if loaded >= limit:
                break
            try:
                # Use canonical loader when available (gives normalized events)
                if load_trajectory:
                    raw = load_trajectory(p, include_prm=False)
                else:
                    raw = json.loads(p.read_text(encoding="utf-8", errors="replace"))
                    if isinstance(raw, list):
                        # jsonl as list of events? take first as representative or skip
                        continue
                    raw.setdefault("events", [])

                task_id = raw.get("task_id") or p.stem.split("_")[0]
                agent = raw.get("agent", "unknown")
                outcome = raw.get("outcome", "unknown")

                # Attach sidecar .prm.json if exists (strip repeated suffixes for matching)
                prm_overall = raw.get("prm_overall_score") or raw.get("prm_result", {}).get("overall_prm_score")
                prm_high = None
                prm_low = None
                prm_sugs = None
                prm_steps = None

                if attach_sidecar_prm:
                    base = p.with_suffix("")
                    # Handle foo.prm.prm... cases and foo_grok.jsonl -> foo_grok.prm.json
                    prm_cand = p.with_suffix(".prm.json")
                    if not prm_cand.exists():
                        # try stripping .prm suffixes from stem
                        stem = p.stem
                        while stem.endswith(".prm"):
                            stem = stem[:-4]
                        prm_cand = p.parent / f"{stem}.prm.json"
                    if prm_cand.exists():
                        try:
                            prm_data = json.loads(prm_cand.read_text(encoding="utf-8", errors="replace"))
                            pr = prm_data.get("prm_result", prm_data)
                            prm_overall = pr.get("overall_prm_score", prm_overall)
                            prm_high = pr.get("prm_high_quality_steps") or pr.get("num_high_quality_steps")
                            prm_low = pr.get("prm_low_quality_steps") or pr.get("num_low_quality_steps")
                            prm_sugs = pr.get("prm_suggestions") or pr.get("suggestions_for_improvement")
                            if pr.get("step_scores"):
                                prm_steps = [
                                    {"index": s.get("step_index", i), "type": s.get("event_type", s.get("type", "unknown")),
                                     "score": s.get("score", 0.0), "reasons": s.get("reasons", [])}
                                    for i, s in enumerate(pr.get("step_scores", []))
                                ]
                        except Exception:
                            pass

                if only_with_prm and prm_overall is None:
                    continue

                rec = TrajectoryRecord(
                    task_id=str(task_id),
                    benchmark_id=str(raw.get("benchmark_id", task_id)),
                    agent=agent,
                    outcome=outcome,
                    prm_overall=prm_overall,
                    prm_high_quality_steps=prm_high,
                    prm_low_quality_steps=prm_low,
                    prm_step_labels=prm_steps,
                    prm_suggestions=prm_sugs,
                    duration_seconds=raw.get("duration_seconds", 0.0),
                    steps_taken=raw.get("steps_taken", len(raw.get("events", []))),
                    tool_calls=raw.get("tool_calls", 0),
                    cost_usd=raw.get("cost_usd", 0.0),
                    error_message=raw.get("error_message"),
                    events=raw.get("events", [])[:300],
                    trajectory_path=str(p),
                    evaluated_at=raw.get("evaluated_at"),
                    learning_value_score=0.0,
                    metadata={"source": "trajectories_dir", "prm_sidecar_used": bool(prm_overall)},
                )
                # Compute a quick learning value
                dur = max(rec.duration_seconds or 1.0, 1.0)
                fail_boost = 1.6 if rec.outcome != "Success" else 1.0
                err_boost = 1.4 if rec.error_message else 1.0
                prm_b = (rec.prm_overall or 0.5) - 0.3
                rec.learning_value_score = round(max(0.05, (fail_boost * err_boost * (0.6 + prm_b)) / (dur / 120 + 1) ), 3)

                self.records.append(rec)
                loaded += 1
            except Exception as e:
                # Skip unreadable files silently in production loader
                continue

        print(f"[TrajectoryDataset] Loaded {loaded} records from trajectories dir (with sidecar PRM where available)")
        return self

    def add_trajectory(
        self,
        source: Union[str, Path, Dict[str, Any]],
        outcome: str = "unknown",
        benchmark_id: Optional[str] = None,
        extra: Optional[Dict] = None,
        compute_prm: bool = True,
    ) -> TrajectoryRecord:
        """Add a single trajectory (path, partial id, or already-loaded dict)."""
        if load_trajectory is None:
            raise RuntimeError("eval.trajectory not available")

        traj = load_trajectory(source, include_prm=compute_prm)
        events = traj.get("events", [])

        prm_res = traj.get("prm_result") or {}
        prm_step_labels = None
        if prm_res and "step_scores" in prm_res:
            prm_step_labels = [
                {
                    "index": getattr(s, "step_index", i),
                    "type": getattr(s, "event_type", "unknown"),
                    "score": getattr(s, "score", 0.0),
                    "reasons": getattr(s, "reasons", []),
                    "confidence": getattr(s, "confidence", 0.5),
                }
                for i, s in enumerate(prm_res.get("step_scores", []))
            ]

        rec = TrajectoryRecord(
            task_id=traj.get("task_id", "unknown"),
            benchmark_id=benchmark_id or traj.get("task_id", "unknown"),
            agent=traj.get("agent", "unknown"),
            outcome=outcome,
            prm_overall=prm_res.get("overall_prm_score"),
            prm_high_quality_steps=prm_res.get("num_high_quality_steps"),
            prm_low_quality_steps=prm_res.get("num_low_quality_steps"),
            prm_step_labels=prm_step_labels,
            prm_suggestions=prm_res.get("suggestions_for_improvement"),
            duration_seconds=traj.get("duration_seconds", 0.0),
            events=events,
            trajectory_path=str(traj.get("source", "")) if traj.get("source") else None,
            metadata=extra or {},
        )
        self.records.append(rec)
        return rec

    # ------------------------------------------------------------------
    # FILTERING (rich, chainable, production quality)
    # ------------------------------------------------------------------
    def filter(
        self,
        min_prm: Optional[float] = None,
        max_prm: Optional[float] = None,
        outcome: Optional[str] = None,
        agent: Optional[str] = None,
        benchmark_id: Optional[str] = None,
        only_real: bool = False,
        min_steps: Optional[int] = None,
        max_cost: Optional[float] = None,
        min_learning_value: Optional[float] = None,
        custom: Optional[Callable[[TrajectoryRecord], bool]] = None,
    ) -> "TrajectoryDataset":
        """Return a new filtered dataset (non-destructive)."""
        new_ds = TrajectoryDataset(name=f"{self.name}_filtered")
        for r in self.records:
            if min_prm is not None and (r.prm_overall or 0) < min_prm:
                continue
            if max_prm is not None and (r.prm_overall or 1) > max_prm:
                continue
            if outcome and r.outcome != normalize_outcome_to_rust_canonical(outcome):
                continue
            if agent and r.agent != agent:
                continue
            if benchmark_id and r.benchmark_id != benchmark_id:
                continue
            if only_real and not r.real_task_id:
                continue
            if min_steps is not None and r.steps_taken < min_steps:
                continue
            if max_cost is not None and r.cost_usd > max_cost:
                continue
            if min_learning_value is not None and r.learning_value_score < min_learning_value:
                continue
            if custom and not custom(r):
                continue
            new_ds.records.append(r)
        return new_ds

    def filter_by_quality(
        self,
        min_overall_prm: float = 0.6,
        min_high_quality_steps: int = 2,
        require_success: bool = True,
    ) -> "TrajectoryDataset":
        """Opinionated high-signal filter for training data."""
        def q(r: TrajectoryRecord) -> bool:
            if require_success and r.outcome != "Success":
                return False
            if r.prm_overall is not None and r.prm_overall < min_overall_prm:
                return False
            if r.prm_high_quality_steps is not None and r.prm_high_quality_steps < min_high_quality_steps:
                return False
            return True

        new_ds = TrajectoryDataset(name=f"{self.name}_high_quality")
        new_ds.records = [r for r in self.records if q(r)]
        return new_ds

    def split_by_outcome(self) -> Dict[str, "TrajectoryDataset"]:
        """Convenience split for preference methods."""
        successes = self.filter(outcome="Success")
        failures = self.filter(outcome="Failure")
        return {"success": successes, "failed": failures}  # keep legacy keys for compat; records use Rust canonical

    # ------------------------------------------------------------------
    # EXPORTS — ready for real training loops (DPO / KTO / SFT / PRM)
    # ------------------------------------------------------------------
    def export_preference_pairs(
        self,
        min_pair_quality: float = 5.0,
        prefer_high_prm: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Generate (chosen, rejected) pairs grouped by benchmark_id.
        This is the gold for DPO, KTO (via chosen/rejected), ORPO, SimPO, etc.
        When AGENTFORGE_USE_RUST=1, automatically tries the Rust binary first (graceful fallback).
        """
        if os.environ.get("AGENTFORGE_USE_RUST") == "1":
            try:
                pairs = export_preference_pairs_via_rust(input_dir=EVAL_RESULTS_DIR)
                if pairs:
                    print("[TrajectoryDataset] export_preference_pairs used Rust fast path")
                    return pairs
            except Exception as e:
                print(f"[TrajectoryDataset] Rust export_preference_pairs fallback: {e}")

        by_bench: Dict[str, List[TrajectoryRecord]] = {}
        for r in self.records:
            by_bench.setdefault(r.benchmark_id, []).append(r)

        pairs = []
        for bid, recs in by_bench.items():
            successes = [r for r in recs if r.outcome == "Success"]
            failures = [r for r in recs if r.outcome != "Success"]

            if not successes or not failures:
                continue

            # Choose best success and worst failure (by PRM or learning value)
            if prefer_high_prm:
                best = max(successes, key=lambda x: (x.prm_overall or 0, x.learning_value_score))
                worst = min(failures, key=lambda x: (x.prm_overall or 1.0, -x.learning_value_score))
            else:
                best = max(successes, key=lambda x: x.learning_value_score)
                worst = max(failures, key=lambda x: x.learning_value_score)

            pair_quality = round((best.learning_value_score + worst.learning_value_score) / 2, 2)
            if pair_quality < min_pair_quality:
                continue

            pairs.append({
                "benchmark_id": bid,
                "chosen": {
                    "outcome": "Success",
                    "prm_overall": best.prm_overall,
                    "events": best.events[-150:],  # bounded for training
                    "summary": best.to_summary(),
                    "trajectory_path": best.trajectory_path,
                    "real_task_id": best.real_task_id,
                },
                "rejected": {
                    "outcome": worst.outcome,
                    "prm_overall": worst.prm_overall,
                    "events": worst.events[-150:],
                    "summary": worst.to_summary(),
                    "error_message": worst.error_message,
                    "trajectory_path": worst.trajectory_path,
                },
                "pair_quality": pair_quality,
                "dataset": self.name,
            })

        pairs.sort(key=lambda x: x["pair_quality"], reverse=True)
        return pairs

    def export_kto_format(self) -> List[Dict[str, Any]]:
        """KTO-style: completion + label (desired/undesired) + optional prompt context."""
        kto = []
        for r in self.records:
            kto.append({
                "task_id": r.task_id,
                "benchmark_id": r.benchmark_id,
                "completion": self._events_to_text(r.events),
                "label": "desired" if r.outcome == "Success" else "undesired",
                "prm": r.prm_overall,
                "metadata": r.to_summary(),
            })
        return kto

    def export_sft_jsonl(self, path: Optional[Path] = None, only_success: bool = True) -> Path:
        """Supervised fine-tuning format. Success trajectories as instruction + response."""
        records = [r for r in self.records if (not only_success or r.outcome == "Success")]

        out_path = path or (_DEFAULT_LEARNING_DIR / f"sft_{self.name}_{datetime.utcnow().strftime('%Y%m%d_%H%M')}.jsonl")
        out_path.parent.mkdir(parents=True, exist_ok=True)

        with open(out_path, "w", encoding="utf-8") as f:
            for r in records:
                ex = {
                    "instruction": f"Complete the following agent task successfully: {r.benchmark_id}",
                    "input": "",
                    "output": self._events_to_text(r.events),
                    "metadata": {
                        "task_id": r.task_id,
                        "prm": r.prm_overall,
                        "agent": r.agent,
                        "duration": r.duration_seconds,
                    },
                }
                f.write(json.dumps(ex, ensure_ascii=False) + "\n")

        print(f"[TrajectoryDataset] Wrote SFT jsonl → {out_path} ({len(records)} examples)")
        return out_path

    def export_prm_training_data(self, path: Optional[Path] = None) -> Path:
        """Clean step-level PRM labels for training a process reward model / critic."""
        out_path = path or (_DEFAULT_LEARNING_DIR / f"prm_labels_{self.name}_{datetime.utcnow().strftime('%Y%m%d_%H%M')}.jsonl")
        out_path.parent.mkdir(parents=True, exist_ok=True)

        count = 0
        with open(out_path, "w", encoding="utf-8") as f:
            for r in self.records:
                if not r.prm_step_labels:
                    continue
                ex = {
                    "benchmark_id": r.benchmark_id,
                    "task_id": r.task_id,
                    "outcome": r.outcome,
                    "overall_prm": r.prm_overall,
                    "steps": r.prm_step_labels,
                }
                f.write(json.dumps(ex, ensure_ascii=False) + "\n")
                count += 1

        print(f"[TrajectoryDataset] Wrote PRM step labels → {out_path} ({count} trajectories)")
        return out_path

    def to_hf_dataset_dict(self) -> Dict[str, List[Dict]]:
        """Return dicts ready for datasets.Dataset.from_list (if HF datasets installed)."""
        return {
            "all": [asdict(r) for r in self.records],
            "preference_pairs": self.export_preference_pairs(),
            "kto": self.export_kto_format(),
        }

    # ------------------------------------------------------------------
    # VERSIONING & PERSISTENCE
    # ------------------------------------------------------------------
    def save_versioned(self, base_dir: Optional[Path] = None) -> DatasetVersion:
        """Save full dataset + rich manifest for reproducibility."""
        base_dir = base_dir or _DEFAULT_LEARNING_DIR
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        version = f"{self.name}_{ts}"
        out_dir = base_dir / version
        out_dir.mkdir(parents=True, exist_ok=True)

        # Save records
        records_path = out_dir / "records.jsonl"
        with open(records_path, "w", encoding="utf-8") as f:
            for r in self.records:
                f.write(json.dumps(asdict(r), ensure_ascii=False, default=str) + "\n")

        # Compute stats
        stats = self._compute_stats()

        # Reproducibility hashes (best effort)
        source_hashes = {}
        for d in (EVAL_RESULTS_DIR, EVAL_TRAJECTORIES_DIR):
            if d.exists():
                h = hashlib.sha256()
                for fp in sorted(d.glob("*"))[:50]:
                    if fp.is_file():
                        h.update(fp.name.encode())
                        h.update(str(fp.stat().st_mtime).encode())
                source_hashes[str(d)] = h.hexdigest()[:16]

        manifest = DatasetVersion(
            name=self.name,
            version=version,
            created_at=datetime.utcnow().isoformat() + "Z",
            filters={"record_count_at_save": len(self.records)},
            record_count=len(self.records),
            stats=stats,
            source_hashes=source_hashes,
            path=str(out_dir),
        )

        (out_dir / "manifest.json").write_text(
            json.dumps(asdict(manifest), indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )

        self._version_history.append(manifest)
        print(f"[TrajectoryDataset] Versioned dataset saved → {out_dir}")
        return manifest

    @classmethod
    def load_versioned(cls, path: Path) -> "TrajectoryDataset":
        """Load a previously versioned dataset."""
        p = Path(path)
        ds = cls(name=p.parent.name if p.is_dir() else "loaded")
        records_file = p / "records.jsonl" if p.is_dir() else p
        if records_file.suffix == ".jsonl":
            for line in records_file.read_text().splitlines():
                if line.strip():
                    data = json.loads(line)
                    ds.records.append(TrajectoryRecord(**data))
        else:
            # fallback single file
            data = json.loads(records_file.read_text())
            for item in data:
                ds.records.append(TrajectoryRecord(**item))
        return ds

    # ------------------------------------------------------------------
    # INTERNALS
    # ------------------------------------------------------------------
    def _result_to_record(
        self,
        result: Dict[str, Any],
        include_traj: bool,
        max_events: int,
        prm_model: Optional[Any],
    ) -> TrajectoryRecord:
        """Convert EvaluationResult-ish dict into rich TrajectoryRecord."""
        rec = TrajectoryRecord(
            task_id=result.get("task_id", "unknown"),
            benchmark_id=result.get("task_id", "unknown"),
            agent=result.get("agent", "unknown"),
            outcome=result.get("outcome", "unknown"),
            real_task_id=result.get("real_task_id"),
            duration_seconds=result.get("duration_seconds", 0.0),
            steps_taken=result.get("steps_taken", 0),
            cost_usd=result.get("cost_usd", 0.0),
            error_message=result.get("error_message"),
            judge_notes=result.get("judge_notes"),
            quality_score=result.get("quality_score"),
            trajectory_path=result.get("trajectory_path"),
            evaluated_at=result.get("evaluated_at"),
            prm_overall=result.get("prm_overall_score"),
            prm_high_quality_steps=result.get("prm_high_quality_steps"),
            prm_low_quality_steps=result.get("prm_low_quality_steps"),
            prm_suggestions=result.get("prm_suggestions"),
            learning_value_score=result.get("learning_value_score", 0.0),
            metadata={"source_result": result.get("_source_file")},
        )

        # Attach full trajectory + step PRM if requested
        traj_path = rec.trajectory_path
        if not traj_path and rec.real_task_id:
            p = find_trajectory_file(rec.real_task_id) if find_trajectory_file else None
            if p:
                traj_path = str(p)

        if include_traj and traj_path and Path(traj_path).exists() and load_trajectory:
            try:
                loaded = load_trajectory(traj_path, include_prm=bool(prm_model))
                rec.events = loaded.get("events", [])[:max_events]
                pr = loaded.get("prm_result") or {}
                if pr:
                    rec.prm_overall = pr.get("overall_prm_score", rec.prm_overall)
                    rec.prm_high_quality_steps = pr.get("num_high_quality_steps")
                    rec.prm_low_quality_steps = pr.get("num_low_quality_steps")
                    rec.prm_suggestions = pr.get("suggestions_for_improvement")
                    if pr.get("step_scores"):
                        rec.prm_step_labels = [
                            {
                                "index": getattr(s, "step_index", i),
                                "type": getattr(s, "event_type", getattr(s, "type", "unknown")),
                                "score": getattr(s, "score", 0.0),
                                "reasons": getattr(s, "reasons", []),
                            }
                            for i, s in enumerate(pr.get("step_scores", []))
                        ]
            except Exception:
                pass

        # Compute learning value if missing (reuse logic style from exporter)
        if rec.learning_value_score == 0.0:
            dur = rec.duration_seconds or 1
            err = 1.8 if rec.error_message else 1.0
            fail = 2.2 if rec.outcome != "Success" else 1.0
            rec.learning_value_score = round(dur * err * fail / 12, 2)

        return rec

    def _events_to_text(self, events: List[Dict[str, Any]], max_chars: int = 8000) -> str:
        """Turn normalized events into a readable trace for SFT / context."""
        parts = []
        for ev in events:
            et = ev.get("type", "step")
            data = ev.get("data", ev)
            preview = ""
            if et == "llm_call":
                preview = f"LLM: {data.get('response_preview', '')[:180]}"
            elif et == "tool_call":
                preview = f"Tool {data.get('tool')}: {str(data.get('result_preview', ''))[:120]}"
            elif et == "reasoning":
                preview = f"Thought: {data.get('thought', '')[:160]}"
            else:
                preview = str(data)[:100]
            parts.append(f"[{et}] {preview}")
        text = "\n".join(parts)
        return text[:max_chars]

    def _compute_stats(self) -> Dict[str, Any]:
        if not self.records:
            return {}
        succ = sum(1 for r in self.records if r.outcome == "Success")
        prms = [r.prm_overall for r in self.records if r.prm_overall is not None]
        return {
            "total": len(self.records),
            "success_rate": round(succ / len(self.records), 4),
            "avg_prm": round(sum(prms) / len(prms), 3) if prms else None,
            "by_agent": {},
            "by_outcome": {},
        }

    def __len__(self) -> int:
        return len(self.records)

    def __repr__(self) -> str:
        return f"<TrajectoryDataset name={self.name} n={len(self.records)}>"

    def compute_learning_value(self) -> None:
        """Compute (or recompute) learning_value_score on all records using the established heuristic."""
        for r in self.records:
            dur = max(getattr(r, "duration_seconds", 1.0) or 1.0, 1.0)
            fail_boost = 1.8 if getattr(r, "outcome", "") != "Success" else 1.0
            err_boost = 1.5 if getattr(r, "error_message", None) else 1.0
            prm_contrib = max(0.0, (getattr(r, "prm_overall", 0.5) or 0.5) - 0.35) * 0.9
            base = (fail_boost * err_boost * (0.6 + prm_contrib)) / (dur / 110.0 + 1.0)
            r.learning_value_score = round(max(0.05, base), 3)


# Backwards-compat alias for the old skeleton
TrajectoryExample = TrajectoryRecord


# =============================================================================
# Rust Bridge (Phase 2/3 turbo integration)
# =============================================================================
"""
Optional Rust acceleration for heavy learning operations.

When the compiled Rust binary is available (built with `cargo build -p agentforge-runner` or --release),
set the environment variable:

    export AGENTFORGE_RUST_RUNNER=/home/agx/agentforge/rust/target/release/agentforge-runner

or let the code auto-discover it (prefers release for production, falls back to debug).

Then (or simply with env):

    export AGENTFORGE_USE_RUST=1
    ds = TrajectoryDataset(name="phase2_rust")
    ds.load_from_eval_results(...)          # auto Rust for large sets (graceful py fallback)
    pairs = ds.export_preference_pairs()    # auto Rust fast path

Heavy methods (load_from_eval_results, export_preference_pairs, etc) now auto-try Rust binary first.
Falls back cleanly. Also callable via export_*_via_rust or the _rust suffixed methods.

This is the concrete "1" integration step after the full Rust port of all 3 phases.
"""

import os
import subprocess
from pathlib import Path
from typing import Optional, List, Dict, Any


def find_rust_runner() -> Optional[Path]:
    """Locate the agentforge-runner binary.

    Production polish: prefers release binary (target/release/agentforge-runner) if present
    for optimal perf/size; falls back to debug. Respects AGENTFORGE_RUST_RUNNER env.
    This is the single source of truth finder (used by bridge, step, enable, post_process, workers).
    """
    env_path = os.environ.get("AGENTFORGE_RUST_RUNNER")
    if env_path:
        p = Path(env_path)
        if p.exists():
            return p

    # Production: prefer release (smaller, faster exec), then debug dev
    candidates = [
        Path("/home/agx/agentforge/rust/target/release/agentforge-runner"),
        Path(__file__).parent.parent / "rust" / "target" / "release" / "agentforge-runner",
        Path.cwd() / "rust" / "target" / "release" / "agentforge-runner",
        Path("/home/agx/agentforge/rust/target/debug/agentforge-runner"),
        Path(__file__).parent.parent / "rust" / "target" / "debug" / "agentforge-runner",
        Path.cwd() / "rust" / "target" / "debug" / "agentforge-runner",
    ]
    for c in candidates:
        try:
            if c.exists():
                return c
        except Exception:
            pass
    return None


def export_preference_pairs_via_rust(
    input_dir: Optional[Path] = None,
    output: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """
    Call the Rust binary to produce DPO-style preference pairs.
    Prefers the *rich* flywheel-export (with learning_value, prm sidecars, outcomes, rich v2 pairs)
    when binary present — this is the production path for canonical rust_flywheel_step.
    Falls back gracefully to corrected basic export-pairs, then pure Python.
    """
    runner = find_rust_runner()
    if not runner:
        print("[learning.rust_bridge] Rust runner not found — using pure Python path")
        return []

    # Prefer rich flywheel-export (supports trajectories + prm sidecars + richer fields)
    traj_dir = Path(
        os.environ.get(
            "AGENTFORGE_EVAL_TRAJECTORIES_DIR",
            str(Path(__file__).parent.parent / "eval" / "trajectories"),
        )
    )
    prm_dir = traj_dir
    results_dir = input_dir or EVAL_RESULTS_DIR
    out_path = Path(output) if output else (Path("/tmp") / f"rust_flywheel_rich_pairs_{os.getpid()}.json")

    # Rich command: always produces richer pairs (learning_value etc) + full bundle
    rich_cmd = [
        str(runner), "flywheel-export",
        "--trajectories", str(traj_dir),
        "--prm-dir", str(prm_dir),
        "--results", str(results_dir),
        "--output", str(out_path),
        "--format", "pairs",
        "--json",
    ]
    rich_success = False
    rich_err = None
    try:
        proc = subprocess.run(rich_cmd, capture_output=True, text=True, timeout=300)
        if out_path.exists() and out_path.stat().st_size > 0:
            # output file is full rich bundle JSON (or jsonl in some cases)
            try:
                bundle = json.loads(out_path.read_text(encoding="utf-8"))
                pairs = bundle.get("preference_pairs") or bundle.get("pairs") or []
                if isinstance(pairs, list) and pairs:
                    print(f"[learning.rust_bridge] Got {len(pairs)} RICH pairs from flywheel-export (learning_value + sidecars)")
                    rich_success = True
                    return pairs
                # fallback: if it was jsonl flattened
                if not pairs:
                    pairs = []
                    for line in out_path.read_text().splitlines():
                        if line.strip():
                            obj = json.loads(line)
                            if "chosen" in obj or "preference_pairs" in obj:
                                pairs.extend(obj.get("preference_pairs", [obj]))
                    if pairs:
                        print(f"[learning.rust_bridge] Parsed {len(pairs)} rich pairs from flywheel jsonl output")
                        rich_success = True
                        return pairs
            except Exception as parse_e:
                print(f"[learning.rust_bridge] Rich bundle parse issue ({parse_e}), trying direct jsonl...")
                # try parse as jsonl of pairs
                pairs = []
                for line in out_path.read_text().splitlines():
                    if line.strip():
                        try:
                            obj = json.loads(line)
                            if isinstance(obj, dict) and ("chosen" in obj or "benchmark_id" in obj):
                                pairs.append(obj)
                        except Exception:
                            pass
                if pairs:
                    print(f"[learning.rust_bridge] Got {len(pairs)} pairs from rich jsonl fallback")
                    rich_success = True
                    return pairs
        # If no pairs in rich or empty, but command succeeded, still note rich was attempted
        if proc.returncode == 0:
            print("[learning.rust_bridge] Rich flywheel-export ran (may have 0 contrast pairs on this batch); will try basic or py")
            rich_success = True  # command success counts for health (healthy rich export run)
    except Exception as e:
        rich_err = str(e)
        print(f"[learning.rust_bridge] Rich flywheel-export failed ({e}); falling back to basic export-pairs")
    finally:
        # SAFEGUARD: always update rich export health (observability + auto-disable triggers in watchdog/continuous)
        try:
            update_rich_export_health(rich_success, rich_err)
        except Exception:
            pass  # never impact export path

    # Fallback: basic export-pairs (with *corrected modern flags*)
    out_path2 = Path(output) if output else (Path("/tmp") / f"rust_dpo_pairs_{os.getpid()}.jsonl")
    basic_cmd = [str(runner), "export-pairs", "--input", str(results_dir), "--output", str(out_path2)]
    try:
        subprocess.run(basic_cmd, check=True, capture_output=True, text=True, timeout=180)
        if out_path2.exists():
            pairs = []
            for line in out_path2.read_text().splitlines():
                if line.strip():
                    pairs.append(json.loads(line))
            if pairs:
                print(f"[learning.rust_bridge] Got {len(pairs)} pairs from basic export-pairs (fallback)")
                return pairs
    except Exception as e:
        print(f"[learning.rust_bridge] Basic export-pairs also failed: {e} — falling to Python")

    return []


def load_eval_results_via_rust(
    results_dir: Optional[Path] = None,
    timeout: int = 300,
) -> Optional[Path]:
    """
    Use Rust to parse/eval results dir into a temp records jsonl (fast for large sets).
    Returns the temp path if successful (caller can load_from_export_file it), else None.
    """
    runner = find_rust_runner()
    if not runner:
        return None
    d = results_dir or EVAL_RESULTS_DIR
    if not d.exists():
        return None
    out_path = Path("/tmp") / f"rust_eval_records_{os.getpid()}_{int(__import__('time').time())}.jsonl"
    cmd = [str(runner), "export-records", "--from", str(d), "--out", str(out_path)]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=timeout)
        if out_path.exists() and out_path.stat().st_size > 10:
            return out_path
    except Exception as e:
        print(f"[learning.rust_bridge] Rust load-records failed: {e}")
    return None


# Monkey-patch style convenience on the class (opt-in)
def _maybe_use_rust_export(self, use_rust: bool = False) -> List[Dict[str, Any]]:
    force_rust = use_rust or (os.environ.get("AGENTFORGE_USE_RUST") == "1")
    if not force_rust:
        return self.export_preference_pairs() if hasattr(self, "export_preference_pairs") else []

    pairs = export_preference_pairs_via_rust(input_dir=EVAL_RESULTS_DIR)
    if pairs:
        return pairs
    # graceful fallback to pure Python
    return self.export_preference_pairs() if hasattr(self, "export_preference_pairs") else []


# Attach as method if people want ds.export_preference_pairs(use_rust=True)
# (kept non-breaking — the original method remains)
TrajectoryDataset.export_preference_pairs_rust = _maybe_use_rust_export

print("[learning] Rust bridge loaded (set AGENTFORGE_RUST_RUNNER or let auto-discovery work)")


# =============================================================================
# SAFEGUARDS & MONITORING: Production-grade health for Rust Flywheel rich exports
# (makes default-on for Antigravity safe via observability + graceful degradation)
# =============================================================================

FLYWHEEL_STATE_DIR = Path("/tmp/agentforge_rust_flywheel")
FLYWHEEL_HEALTH_FILE = FLYWHEEL_STATE_DIR / "flywheel_health.json"

def get_flywheel_health() -> Dict[str, Any]:
    """Read current flywheel health snapshot (rich exports + continuous + timer). Non-fatal."""
    try:
        FLYWHEEL_STATE_DIR.mkdir(parents=True, exist_ok=True)
        if FLYWHEEL_HEALTH_FILE.exists():
            return json.loads(FLYWHEEL_HEALTH_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}

def update_rich_export_health(success: bool, error_msg: Optional[str] = None) -> Dict[str, Any]:
    """
    Core monitoring helper for safeguards.
    Tracks success rate of rich flywheel-exports (the agentforge-runner flywheel-export path).
    Persists to shared JSON used by watchdog.py, healthcheck.sh, show_agent_stats.py, continuous timer.
    Sets 'degraded' flag on too many consec fails or stale (no success >6h after initial activity).
    Called automatically from rich export bridge.
    """
    try:
        FLYWHEEL_STATE_DIR.mkdir(parents=True, exist_ok=True)
        health: Dict[str, Any] = {}
        if FLYWHEEL_HEALTH_FILE.exists():
            try:
                health = json.loads(FLYWHEEL_HEALTH_FILE.read_text(encoding="utf-8"))
            except Exception:
                health = {}
        rich: Dict[str, Any] = health.get("rich_exports") or {}
        now = time.time()
        total = int(rich.get("total_attempts", 0)) + 1
        succ = int(rich.get("successes", 0))
        fails = int(rich.get("failures", 0))
        consec = int(rich.get("consecutive_failures", 0))
        last_succ = rich.get("last_success_unix")
        last_err = rich.get("last_error")

        if success:
            succ += 1
            consec = 0
            last_succ = now
        else:
            fails += 1
            consec += 1
            if error_msg:
                last_err = str(error_msg)[:300]

        sr = round(succ / max(1, total), 4) if total > 0 else 0.0
        rich.update({
            "total_attempts": total,
            "successes": succ,
            "failures": fails,
            "success_rate": sr,
            "error_rate": round(fails / max(1, total), 4) if total > 0 else 0.0,
            "last_success_unix": last_succ,
            "last_success_iso": datetime.utcfromtimestamp(last_succ).isoformat() + "Z" if last_succ else None,
            "last_error": last_err,
            "consecutive_failures": consec,
            "last_attempt_unix": now,
            "last_attempt_iso": datetime.utcnow().isoformat() + "Z",
        })
        health["rich_exports"] = rich
        health["timestamp"] = datetime.utcnow().isoformat() + "Z"

        # Simple auto-degrade detection (observability for graceful degradation)
        stale = bool(last_succ and (now - last_succ > 6 * 3600) and total > 2)
        high_consec = consec >= 5
        degraded = high_consec or stale
        health["degraded"] = degraded
        if degraded:
            health["degraded_reason"] = "consecutive_rich_export_failures" if high_consec else ("no_rich_exports_for_hours" if stale else "unknown")
            health["degraded_since_unix"] = health.get("degraded_since_unix") or now
        else:
            health.pop("degraded_reason", None)
            health.pop("degraded_since_unix", None)

        FLYWHEEL_HEALTH_FILE.write_text(json.dumps(health, indent=2), encoding="utf-8")
        return {"success_rate": sr, "consecutive_failures": consec, "degraded": degraded}
    except Exception as e:
        # Never break callers
        return {"error": str(e)[:120]}

# Convenience: lightweight reader for rich stats only
def get_rich_export_stats() -> Dict[str, Any]:
    h = get_flywheel_health()
    return h.get("rich_exports", {}) or {}
