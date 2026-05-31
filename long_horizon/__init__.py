"""
Phase 3: Long Horizon foundations.

Production skeleton for tasks that run for hours → weeks:
- LongTaskManager with heartbeats, pause/resume, progress, persistence
- Deep integration with planning (HierarchicalPlanner + ExecutionEngine + checkpoints)
- Safety gates on every subtask via ActionApprovalLayer
- Survives restarts / multi-day gaps via ~/.agentforge/long_horizon/*.json

Primary entrypoint:
    from agentforge.long_horizon import LongTaskManager, LongTask, Progress
"""

from .task_manager import LongTaskManager, LongTask, Progress

__all__ = ["LongTaskManager", "LongTask", "Progress"]
