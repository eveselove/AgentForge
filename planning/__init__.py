"""
Phase 3: Long Horizon Planning foundations.

Public API:
    from agentforge.planning import (
        HierarchicalPlanner, ExecutionEngine, Plan, Subtask,
        DependencyGraph, PlanCheckpoint,
    )

Pragmatic hierarchical planning + dep graph + parallel-capable execution + first-class checkpoint/resume.
Integrates cleanly with long_horizon.LongTaskManager, task_queue checkpoints, and eval benchmarks.
"""

from .planner import (
    HierarchicalPlanner,
    ExecutionEngine,
    Plan,
    Subtask,
    DependencyGraph,
    PlanCheckpoint,
)

__all__ = [
    "HierarchicalPlanner",
    "ExecutionEngine",
    "Plan",
    "Subtask",
    "DependencyGraph",
    "PlanCheckpoint",
]
