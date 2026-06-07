# AgentForge Observability (Phase 1)

Production-ready foundation for tracing agent trajectories with automatic PRM (Process Reward Model) scoring.

## What you get

- **Span** dataclass + context propagation (future OTEL compatible)
- **`create_spans_from_trajectory`** — the single recommended entry point for reports, CLI, post-processing, and analysis
- Automatic **per-step PRM score attachment** (score + reasons + confidence) aligned to `load_trajectory` events
- Rich JSON export (plain + minimal OTEL `resourceSpans` wrapper)
- `start_as_current_span` context manager for live instrumentation
- Aggregates via `summarize_spans` that include PRM metrics

Tightly coupled to the canonical `agentforge.eval.trajectory.load_trajectory` + `ProcessRewardModel`.

## Primary Usage (reports / CLI / post-processing)

```python
from agentforge.observability import (
    create_spans_from_trajectory,
    summarize_spans,
    export_spans_to_json,
)

# One-liner: load + PRM + spans (easiest from anywhere)
spans = create_spans_from_trajectory("f12a11c0")                 # partial task id
# or
spans = create_spans_from_trajectory("/path/to/trajectory.jsonl", include_prm=True)

summary = summarize_spans(spans)
print(summary)
# {'total_spans': 47, 'avg_prm': 0.612, 'prm_span_coverage': 47, 'llm_calls': 12, ...}

# Immediate OTEL-ready export (for archiving, future collectors, dashboards)
export_spans_to_json(
    spans,
    "/tmp/trace_f12a11c0.json",
    include_otel_wrapper=True
)
```

## Lower-level (when you already have a loaded trajectory)

```python
from agentforge.eval.trajectory import load_trajectory
from agentforge.observability import replay_trajectory, summarize_spans

traj = load_trajectory("adaptive_throttle_tuning", include_prm=True)
spans = replay_trajectory(traj, prm_result=traj.get("prm_result"))
```

## Live instrumentation (inside running code)

```python
from agentforge.observability import start_as_current_span

with start_as_current_span("agent.skill.execute"):
    span = get_current_span()  # or just use the yielded one
    span.set_attribute("skill", "rust-refactor")
    # ... your work ...
# automatically ended + status set (error path also handled)
```

## Export formats (future OTEL compatibility)

`export_spans_to_json(..., include_otel_wrapper=True)` produces:

```json
{
  "resourceSpans": [{
    "resource": { "attributes": [{"key":"service.name", "value":{"stringValue":"agentforge"}}] },
    "scopeSpans": [{
      "scope": {"name": "agentforge.observability"},
      "spans": [ { "name": "...", "trace_id": "...", "attributes": {"prm_score": 0.78, ...}, ... } ]
    }]
  }]
}
```

Roundtrippable with `spans_from_json()`.

## Running the tests

```bash
cd /home/eveselove
PYTHONPATH=. python -m pytest agentforge/eval/tests/test_observability.py -q
# or plain unittest
PYTHONPATH=. python -m agentforge.eval.tests.test_observability
```

See also: `agentforge/eval/tests/test_observability.py`, `eval/post_process.py`, `eval/trajectory.py`, `eval/prm.py`.

## Next (post Phase 1)

- Wire automatic span creation inside the runner / skills
- Push spans to Langfuse / Jaeger / Prometheus
- Use PRM-augmented spans as direct training data for SFT + RL

This turns raw logs into queryable, scored, exportable causal traces — ready for the learning flywheel.
