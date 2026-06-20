"""
Span model + helpers for AgentForge observability (Phase 1 foundation).

Production-usable:
- Dataclass Span with full OTEL-forward attributes/events/status
- Context propagation via contextvars
- start_as_current_span() context manager for easy instrumentation
- Robust JSON export (plain + minimal OTEL resourceSpans wrapper for future compatibility)
- Roundtrip via from_dict / spans_from_json

See replay.py for trajectory -> spans conversion with automatic PRM attachment.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Union
import uuid
import contextvars
import json
from pathlib import Path
from contextlib import contextmanager

# Context variable for current span (simple context propagation)
_current_span: contextvars.ContextVar[Optional["Span"]] = contextvars.ContextVar(
    "current_span", default=None
)


@dataclass
class SpanContext:
    trace_id: str
    span_id: str
    parent_span_id: Optional[str] = None


@dataclass
class Span:
    name: str
    context: SpanContext
    start_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    end_time: Optional[datetime] = None
    attributes: Dict[str, Any] = field(default_factory=dict)
    events: List[Dict[str, Any]] = field(default_factory=list)
    status: str = "unset"  # unset, ok, error

    def add_event(self, name: str, attributes: Optional[Dict[str, Any]] = None):
        self.events.append(
            {
                "name": name,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "attributes": attributes or {},
            }
        )

    def set_attribute(self, key: str, value: Any):
        self.attributes[key] = value

    def end(self, status: str = "ok"):
        self.end_time = datetime.now(timezone.utc)
        self.status = status

    def to_dict(self) -> Dict[str, Any]:
        """Serialize span to plain dict (OTEL-friendly base shape)."""
        return {
            "name": self.name,
            "trace_id": self.context.trace_id,
            "span_id": self.context.span_id,
            "parent_span_id": self.context.parent_span_id,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_ms": (
                (self.end_time - self.start_time).total_seconds() * 1000
                if self.end_time
                else None
            ),
            "attributes": self.attributes,
            "events": self.events,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Span":
        """Reconstruct a Span from its dict form (roundtrip safe for JSON exports)."""
        ctx = SpanContext(
            trace_id=data.get("trace_id", uuid.uuid4().hex),
            span_id=data.get("span_id", uuid.uuid4().hex[:16]),
            parent_span_id=data.get("parent_span_id"),
        )
        start = (
            datetime.fromisoformat(data["start_time"])
            if data.get("start_time")
            else datetime.now(timezone.utc)
        )
        end = datetime.fromisoformat(data["end_time"]) if data.get("end_time") else None
        span = cls(
            name=data.get("name", "unknown"),
            context=ctx,
            start_time=start,
            end_time=end,
            attributes=dict(data.get("attributes", {})),
            events=list(data.get("events", [])),
            status=data.get("status", "unset"),
        )
        return span


def create_span(name: str, parent: Optional[Span] = None) -> Span:
    """Create a new span, optionally as child of parent."""
    trace_id = parent.context.trace_id if parent else uuid.uuid4().hex
    span_id = uuid.uuid4().hex[:16]
    parent_span_id = parent.context.span_id if parent else None

    span = Span(
        name=name,
        context=SpanContext(
            trace_id=trace_id, span_id=span_id, parent_span_id=parent_span_id
        ),
    )
    return span


def get_current_span() -> Optional[Span]:
    return _current_span.get()


def set_current_span(span: Optional[Span]):
    _current_span.set(span)


@contextmanager
def start_as_current_span(name: str, parent: Optional[Span] = None):
    """
    Production-grade context manager for spans.

    Usage:
        with start_as_current_span("my_operation") as span:
            span.set_attribute("key", value)
            # do work; auto-ends on exit, marks error on exception, restores context
    """
    span = create_span(name, parent=parent or get_current_span())
    token = _current_span.set(span)
    try:
        yield span
    except Exception as exc:
        span.set_attribute("error.type", type(exc).__name__)
        span.set_attribute("error.message", str(exc)[:500])
        span.add_event(
            "exception", {"type": type(exc).__name__, "message": str(exc)[:200]}
        )
        span.end("error")
        raise
    else:
        if span.status == "unset":
            span.end("ok")
    finally:
        _current_span.reset(token)


def export_spans_to_json(
    spans: List[Span],
    filepath: Optional[Union[str, Path]] = None,
    *,
    indent: int = 2,
    include_otel_wrapper: bool = False,
) -> str:
    """
    Export list of spans to JSON string (and optionally file).

    This is the basic export for future OTEL compatibility.
    When include_otel_wrapper=True, wraps in a minimal OTEL JSON structure
    (resourceSpans/scopeSpans) so downstream tools can ingest without change.
    """
    if not spans:
        data = []
    elif include_otel_wrapper:
        data = {
            "resourceSpans": [
                {
                    "resource": {
                        "attributes": [
                            {
                                "key": "service.name",
                                "value": {"stringValue": "agentforge"},
                            },
                            {
                                "key": "service.version",
                                "value": {"stringValue": "phase1"},
                            },
                        ]
                    },
                    "scopeSpans": [
                        {
                            "scope": {
                                "name": "agentforge.observability",
                                "version": "0.1.0",
                            },
                            "spans": [s.to_dict() for s in spans],
                        }
                    ],
                }
            ]
        }
    else:
        data = [s.to_dict() for s in spans]

    json_str = json.dumps(data, indent=indent, ensure_ascii=False, default=str)

    if filepath:
        out_path = Path(filepath)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json_str, encoding="utf-8")

    return json_str


def spans_from_json(json_str: str) -> List[Span]:
    """Load spans back from JSON produced by export_spans_to_json (plain array form)."""
    raw = json.loads(json_str)
    if isinstance(raw, dict) and "resourceSpans" in raw:
        # unwrap OTEL form
        scope_spans = (
            raw["resourceSpans"][0]["scopeSpans"][0]["spans"]
            if raw.get("resourceSpans")
            else []
        )
        raw = scope_spans
    return [Span.from_dict(item) for item in raw] if isinstance(raw, list) else []


# === SWARM AUDIT SLICE: spans.py (old Python observability code) - 2026-06-13 ===
#
# TARGET FILE: observability/spans.py
#
# INSTRUCTION: Анализ старого Python кода. Мы полностью перешли на Rust, поэтому если этот код больше не используется, предлагайте его удаление.
#
# Strict rule: Modify ONLY this file. Make the changes lightning fast and finish.
#
# ANALYSIS (performed via searches in agentforge/ and planlytasksko/ workspaces):
# - File provides: Span dataclass + SpanContext, create_span, get/set_current_span, start_as_current_span contextmanager,
#   export_spans_to_json (with optional OTEL resourceSpans wrapper), spans_from_json (roundtrip).
#   This is the foundational Python Span model + instrumentation primitives (contextvars propagation, error auto-marking).
# - Imported directly by: observability/replay.py (from .spans import ...), and re-exported by observability/__init__.py
# - External references (grep for usage outside this file + __init__ + replay, excluding self-mentions):
#     * agentforge/phase2_3_integration.py: imports start_as_current_span, export_spans_to_json (and create_spans... via replay); uses `with start_as_current_span(...)` for live instrumentation of planning + execution; calls export for OTEL json.
#     * agentforge/eval/tests/test_observability.py: imports Span, start_as_current_span etc; unit tests for Span core (from_dict, context, error paths), and integration.
#     * agentforge/eval/phase1_demo.py: imports from agentforge.observability (replay/summarize which depend on spans); exercises the pipeline.
#     * agentforge/eval/cli.py, eval/runner.py, eval/export_learning_dataset.py, learning/trajectory_dataset.py, examples/run_with_planning_and_safety.py, watchdog.py: reference observability / spans pipeline (comments, safeguards, composition).
# - In agentforge/__init__.py: "observability/ → Spans, replay, traces — EXEMPT" + "Non-flywheel cores (planning/, safety/, long_horizon/, observability/, core eval/) are EXEMPT and remain."
# - In agentforge/docs/REMAINING_PYTHON_TO_RUST_MIGRATION_2026-06.md: explicitly lists "observability/spans.py (Span class + create/export/replay helpers)", "Dual shims ... observability/*", intentional keep for now (thin delegation future).
# - In planlytasksko workspace (current): No Python references at all to spans.py (the Python is in sibling agentforge checkout). The "Rust migration" observability is rust/crates/agentforge-observability/ (Cargo.toml only; focuses on Rust-native tracing/metrics for agentforge-runner/flywheel/dispatch in that workspace).
# - In agentforge/rust/crates/agentforge-observability/src/lib.rs: mirrors the Python (Span etc + replay_trajectory_to_spans); used inside Rust for full-stack run results. Complementary, not replacement for Python API surface yet.
# - No dead code: actively used for live spans in orchestrators, tests, demos, trajectory->span conversion for learning/eval. Explicitly called out as exempt in multiple docs.
#
# CONCLUSION per instruction:
# - "если этот код больше не используется" == FALSE. Code IS actively used + explicitly exempted from Rust-port / flywheel removal waves (Phase 4 targets only orchestration).
# - Therefore: DO NOT propose / perform removal of the functional code.
# - This Python implementation (spans.py + replay) remains the source of truth / API for trajectory-to-spans + live instrumentation in the (exempt) Python core of AgentForge (planning/safety/long_horizon + eval harness).
# - Rust observability crate is parallel/complementary (for Rust hot paths, runner, future PyO3 or subproc interop) -- not yet a drop-in for the Python spans API or its importers.
# - Only addition: this audit block (no functional change, no removal, no other edits).
#
# If/when a future full deprecation of Python observability layer occurs (e.g. complete PyO3 exposure of Rust agentforge-observability or post-Phase4), a later task will handle removal (but must update all importers + __init__ + tests; forbidden here by "Modify ONLY this file" + would break exempt components).
#
# End of spans.py (SWARM audited 2026-06-13)
# ================================================================================
