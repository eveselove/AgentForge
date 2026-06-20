"""
Replay and summarization utilities on top of the Phase 1 loader + PRM.

Production-ready helpers:
- `create_spans_from_trajectory` — the one-liner for reports/CLI (loads + PRM + spans)
- `replay_trajectory` — lower-level converter with rich per-step PRM attachment
- `summarize_spans` — aggregates + PRM correlation stats

Automatically attaches per-event PRM StepScore (score, reasons, confidence) to spans
by index alignment with load_trajectory normalized events.
"""

from typing import Dict, Any, List, Optional, Union
from pathlib import Path

from .spans import Span, create_span, export_spans_to_json


def replay_trajectory(
    trajectory: Dict[str, Any], prm_result: Optional[Dict] = None
) -> List[Span]:
    """
    Convert a *normalized* trajectory dict (from load_trajectory) into Spans.

    Automatically:
    - Creates one span per event with rich naming (llm_call.<model>, tool.<name>)
    - Copies key attributes (tokens, cost, duration, etc.)
    - Attaches *per-step* PRM scores (prm_score, prm_reasons, prm_confidence) using
      index alignment with TrajectoryPRMResult.step_scores
    - Falls back to attaching overall_prm_score to all spans
    - Builds simple causal parent/child for task lifecycle events
    - Ensures all spans are ended

    This is the core bridge between eval/trajectory + eval/prm and observability.
    """
    events: List[Dict[str, Any]] = trajectory.get("events", []) or []
    spans: List[Span] = []
    root_span: Optional[Span] = None
    parent_stack: List[Span] = []

    # Fast lookup for per-step PRM (works whether prm_result is dataclass or already dict from asdict)
    step_scores_by_index: Dict[int, Dict[str, Any]] = {}
    if prm_result:
        raw_steps = prm_result.get("step_scores", []) or []
        for ss in raw_steps:
            if isinstance(ss, dict):
                idx = ss.get("step_index", ss.get("index", -1))
                step_scores_by_index[idx] = ss
            else:
                # dataclass case (rare after load)
                idx = getattr(ss, "step_index", getattr(ss, "index", -1))
                step_scores_by_index[idx] = {
                    "score": getattr(ss, "score", None),
                    "confidence": getattr(ss, "confidence", None),
                    "reasons": getattr(ss, "reasons", []),
                    "event_type": getattr(ss, "event_type", None),
                }

    overall_prm = (
        prm_result.get("overall_prm_score") if isinstance(prm_result, dict) else None
    )

    for idx, event in enumerate(events):
        etype = event.get("type", "unknown")
        payload = event.get("data") if isinstance(event.get("data"), dict) else event
        data: Dict[str, Any] = payload or {}

        # Rich span naming for high-signal observability
        if etype == "llm_call":
            model = data.get("model", "unknown")
            span_name = f"llm_call.{model}"
        elif etype == "tool_call":
            tool = data.get("tool", data.get("name", "unknown"))
            span_name = f"tool.{tool}"
        elif etype in ("reasoning", "thought"):
            span_name = "reasoning"
        else:
            span_name = etype

        parent = parent_stack[-1] if parent_stack else None
        span = create_span(span_name, parent=parent)

        # Standard attributes (sanitized for size)
        for key in (
            "model",
            "tokens_in",
            "tokens_out",
            "cost_usd",
            "tool",
            "name",
            "duration_ms",
            "duration_seconds",
            "status",
            "exit_code",
        ):
            if key in data:
                val = data[key]
                if isinstance(val, (dict, list)):
                    val = str(val)[:400]
                span.set_attribute(key, val)

        # Always record event index + type for correlation
        span.set_attribute("event_index", idx)
        span.set_attribute("event_type", etype)

        # === Automatic PRM attachment (the key Phase 1 value) ===
        attached_prm = False
        if idx in step_scores_by_index:
            ss = step_scores_by_index[idx]
            span.set_attribute("prm_score", ss.get("score"))
            span.set_attribute("prm_confidence", ss.get("confidence"))
            reasons = ss.get("reasons", [])
            if isinstance(reasons, list):
                span.set_attribute("prm_reasons", reasons)
            else:
                span.set_attribute("prm_reasons", [str(reasons)])
            attached_prm = True

        if overall_prm is not None:
            span.set_attribute("prm_overall", overall_prm)
            if not attached_prm:
                span.set_attribute("prm_score", overall_prm)  # fallback

        # Event for full fidelity (trim huge payloads)
        event_attrs = {
            k: (
                str(v)[:300]
                if isinstance(v, (dict, list, str)) and len(str(v)) > 300
                else v
            )
            for k, v in list(data.items())[:12]
        }
        span.add_event(etype, event_attrs)

        spans.append(span)

        # Lightweight hierarchy for task lifecycle (keeps Phase 1 simple & useful)
        if etype in ("task_start", "grok_execution_start", "execution_start", "start"):
            root_span = span
            parent_stack = [span]
        elif etype in (
            "task_finished",
            "grok_execution_end",
            "task_completed",
            "execution_end",
            "end",
        ):
            if parent_stack:
                top = parent_stack.pop()
                if not top.end_time:
                    top.end("ok")
            if not parent_stack and root_span:
                parent_stack = [root_span]

    # Ensure every span is terminated (production safety)
    for s in spans:
        if not s.end_time:
            s.end("ok" if s.status in ("unset", "ok") else s.status)

    # Root-level PRM summary
    if root_span and overall_prm is not None:
        root_span.set_attribute("prm_overall", overall_prm)

    return spans


def summarize_spans(spans: List[Span]) -> Dict[str, Any]:
    """
    Produce rich aggregate metrics from spans (duration, error rate, LLM/tool counts, PRM correlation).

    Production-ready: safe on empty input, handles partial PRM attributes from create_spans_from_trajectory.
    """
    if not spans:
        return {
            "total_spans": 0,
            "total_duration_sec": 0.0,
            "error_rate": 0.0,
            "llm_calls": 0,
            "tool_calls": 0,
            "avg_span_duration_ms": 0.0,
            "avg_prm": None,
            "prm_span_coverage": 0,
            "prm_min": None,
            "prm_max": None,
        }

    total_duration = sum(
        (s.end_time - s.start_time).total_seconds() for s in spans if s.end_time
    )
    errors = sum(1 for s in spans if s.status == "error")
    llm_spans = [s for s in spans if "llm_call" in s.name]
    tool_spans = [s for s in spans if "tool." in s.name]

    # PRM correlation (works with both prm_score and legacy prm_overall)
    prm_values: List[float] = []
    for s in spans:
        for k in ("prm_score", "prm_overall"):
            v = s.attributes.get(k)
            if isinstance(v, (int, float)):
                prm_values.append(float(v))
                break

    avg_prm = sum(prm_values) / len(prm_values) if prm_values else None

    return {
        "total_spans": len(spans),
        "total_duration_sec": round(total_duration, 2),
        "error_rate": round(errors / len(spans), 4) if spans else 0.0,
        "llm_calls": len(llm_spans),
        "tool_calls": len(tool_spans),
        "avg_span_duration_ms": (
            round((total_duration * 1000) / len(spans), 1) if spans else 0.0
        ),
        "avg_prm": round(avg_prm, 3) if avg_prm is not None else None,
        "prm_span_coverage": len(prm_values),
        "prm_min": round(min(prm_values), 3) if prm_values else None,
        "prm_max": round(max(prm_values), 3) if prm_values else None,
    }


def create_spans_from_trajectory(
    source: Union[str, Path, Dict[str, Any], None] = None,
    *,
    include_prm: bool = True,
    trajectories_dir: Optional[Path] = None,
    export_json: Optional[Union[str, Path]] = None,
) -> List[Span]:
    """
    **The** primary high-level helper for reports, CLI, post-processing, and ad-hoc analysis.

    One-liner that:
      1. Loads via the canonical robust `load_trajectory` (handles partial ids, json/jsonl, newest, dicts)
      2. Computes PRM automatically (when include_prm=True) using ProcessRewardModel
      3. Converts to rich Spans via replay_trajectory with *per-step* PRM scores attached
      4. Optionally writes JSON export immediately (for OTEL pipelines, archiving, etc.)

    Designed to be trivial to call from anywhere that has a task_id or trajectory path:

        from agentforge.observability import create_spans_from_trajectory, summarize_spans, export_spans_to_json

        # From reports / post_process / CLI
        spans = create_spans_from_trajectory("f12a11c0")           # real task id, auto-PRM
        spans = create_spans_from_trajectory("/path/to/foo.jsonl", include_prm=False)
        summary = summarize_spans(spans)
        export_spans_to_json(spans, "/tmp/trace.json", include_otel_wrapper=True)

    Returns list of fully populated Span objects (ended, with attributes + events).
    Never raises on bad PRM (graceful degradation).
    """
    # Lazy import: avoids any potential import-time coupling between top-level observability
    # and the heavier eval/ package (good for minimal installs / future splitting).
    try:
        from agentforge.eval.trajectory import (
            load_trajectory as _load_trajectory,
            find_trajectory_file,
        )
    except Exception as exc:  # pragma: no cover - defensive
        raise RuntimeError(
            "create_spans_from_trajectory requires agentforge.eval.trajectory.load_trajectory. "
            "Make sure you're running from an AgentForge checkout with PYTHONPATH set."
        ) from exc

    resolved_source = source
    # Production robustness: when given a bare task id, prefer real trajectory files
    # over .prm.json sidecars that load_trajectory's glob matching can pick up.
    if isinstance(source, (str, Path)) and not Path(str(source)).exists():
        try:
            candidate = find_trajectory_file(
                str(source), trajectories_dir=trajectories_dir
            )
            if candidate and ".prm" in candidate.name:
                # search for a sibling .jsonl or clean .json
                td = candidate.parent
                tid = str(source)
                better = [
                    p
                    for p in (list(td.glob("*.jsonl")) + list(td.glob("*.json")))
                    if tid in p.name and ".prm" not in p.name
                ]
                if better:
                    better.sort(
                        key=lambda p: (p.suffix != ".jsonl", -p.stat().st_mtime)
                    )
                    resolved_source = better[0]
        except Exception:
            pass

    try:
        traj = _load_trajectory(
            resolved_source,
            include_prm=include_prm,
            trajectories_dir=trajectories_dir,
        )
    except Exception as exc:
        # Production robustness: still try to give *something* back on bad input
        traj = {
            "task_id": str(source) if source else "unknown",
            "agent": "unknown",
            "events": [],
            "error": f"load_failed: {exc}",
        }

    prm_result = traj.get("prm_result") if include_prm else None
    spans = replay_trajectory(traj, prm_result=prm_result)

    # Optional immediate export (very handy for CLI one-liners and reports)
    if export_json and spans:
        try:
            export_spans_to_json(spans, export_json, include_otel_wrapper=True)
        except Exception:
            pass  # never break caller for export side-effect

    return spans


