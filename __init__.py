"""
AgentForge — Production-grade multi-agent software engineering system.

Current development status (as of massive Phase 2/3 turbo push):

- Phase 0 + Phase 1 (Evaluation + Observability + PRM): 100% complete
- Phase 2 (Learning Flywheel) foundations: actively being built
- Phase 3 (Long Horizon + Safety) foundations: **strong practical skeletons delivered**

!!! AGGRESSIVE PHASE 3/4 FINAL DEPRECATION SWEEP (RUST_FULL_MIGRATION_PLAN.md + PHASE4_REMOVAL_PLAN.md) !!!
PYTHON FLYWHEEL ORCHESTRATION LAYER (proposal gen via SkillImprover, candidate ingest/promote/AB via pending_candidates + evaluator, continuous loop, step glue etc.) IS AGGRESSIVELY DEPRECATED.
Phase 4 removal target after Rust agentforge-runner (flywheel-step/continuous/candidate) + agentforge-learning crates proven sole canonical engine.
ALL remaining Python flywheel orchestration files carry loud banners + delegate exclusively to central is_pure_rust_flywheel() guard in learning/utils.py (Phase 4 hardened).
See PHASE4_REMOVAL_PLAN.md (exhaustive marked targets, 4-tier safe removal order, risks per file, multi-layer rollback via .disable_pure_rust_flywheel + env + git + services) + PHASE4_REMOVAL_CHECKLIST.md + learning/utils.py
Non-flywheel cores (planning/, safety/, long_horizon/, observability/, core eval/) are EXEMPT and remain.
MIGRATE ALL FLYWHEEL USAGE TO: agentforge-runner flywheel-step --real-data --ingest ; agentforge-runner continuous ; agentforge-runner candidate ...

Key modules:
- eval/          → World-class evaluation, PRM, trajectory viewer (flywheel glue only is deprecated)
- learning/      → Trajectory datasets, trainers, automatic improvement (orchestration parts deprecated Phase 4)
- planning/      → Hierarchical planning + dep graphs + parallel execution + checkpoint/resume (Phase 3) — EXEMPT
- safety/        → PolicyEngine + Sandbox stubs + ActionApprovalLayer with risk scoring + HITL hooks (Phase 3) — EXEMPT
- long_horizon/  → LongTaskManager (heartbeats, pause/resume, progress, multi-day survival + planning+safety integration) — EXEMPT
- observability/ → Spans, replay, traces — EXEMPT
"""

__version__ = "0.3.0-phase3-foundations"

# Phase 3 foundations (now live)
from .planning import (
    HierarchicalPlanner,
    ExecutionEngine,
    Plan,
    Subtask,
    DependencyGraph,
    PlanCheckpoint,
)
from .safety import (
    PolicyEngine,
    ActionDecision,
    Decision,
    ActionApprovalLayer,
    create_default_approval_layer,
    FileSystemSandbox,
    CommandSandbox,
)
from .long_horizon import LongTaskManager, LongTask, Progress

# Commented until Phase 2 is further along
# from .learning import TrajectoryDataset

__all__ = [
    "HierarchicalPlanner",
    "ExecutionEngine",
    "Plan",
    "Subtask",
    "DependencyGraph",
    "PlanCheckpoint",
    "PolicyEngine",
    "ActionDecision",
    "Decision",
    "ActionApprovalLayer",
    "create_default_approval_layer",
    "FileSystemSandbox",
    "CommandSandbox",
    "LongTaskManager",
    "LongTask",
    "Progress",
]
