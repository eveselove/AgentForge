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
