"""
Observability module (Phase 1 production foundation).

Public API (import from agentforge.observability):
- Span / SpanContext / create_span + context helpers (start_as_current_span)
- create_spans_from_trajectory — primary easy entrypoint (load_trajectory + PRM + spans + optional JSON export)
- replay_trajectory / summarize_spans — lower level
- export_spans_to_json / spans_from_json — OTEL-ready JSON (plain array or wrapped)

Tightly integrated with agentforge.eval.{trajectory, prm} for automatic per-step PRM score attachment.
"""

from .spans import (
    Span,
    SpanContext,
    create_span,
    get_current_span,
    set_current_span,
    start_as_current_span,
    export_spans_to_json,
    spans_from_json,
)
from .replay import (
    replay_trajectory,
    summarize_spans,
    create_spans_from_trajectory,
)

__all__ = [
    "Span",
    "SpanContext",
    "create_span",
    "get_current_span",
    "set_current_span",
    "start_as_current_span",
    "export_spans_to_json",
    "spans_from_json",
    "replay_trajectory",
    "summarize_spans",
    "create_spans_from_trajectory",
]
