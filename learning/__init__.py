"""
!!! AGGRESSIVE FINAL DEPRECATION SWEEP (RUST_FULL_MIGRATION_PLAN.md + PHASE4_REMOVAL_PLAN.md) !!!
Phase 2: Learning Flywheel (Foundation) — PYTHON ORCHESTRATION LAYER DEPRECATED

PHASE 4 DELETION TARGET for all flywheel orchestration (SkillImprover, pending_candidates,
evaluator flywheel paths, run_*, continuous, step glue, etc. + legacy dataset.py shim).
# NOTE: long line above for deprecation banner (E501 tolerated in docs per migration wave)

MIGRATE TO: agentforge-runner flywheel-step / continuous / candidate ...

Guard with Phase 4 EVEN STRONGER central ONLY:
    from agentforge.learning.utils import is_pure_rust_flywheel, is_rust_flywheel_disabled

Primary exports (non-orchestration parts may survive longer for eval):
- TrajectoryDataset (eval use + parity)
- Trainers (standalone)
etc.

See learning/utils.py (hardened guards + exhaustive list of remaining Python flywheel files)
See PHASE4_REMOVAL_PLAN.md
(Non-breaking: !pure keeps full legacy Python.)

See PHASE4_REMOVAL_CHECKLIST.md for the full list of files/dirs in this package targeted for Phase 4 deletion.
Non-breaking shims remain only for !pure_rust paths.
"""

from .trajectory_dataset import (
    TrajectoryDataset,
    TrajectoryRecord,
    DatasetVersion,
    TrajectoryExample,  # legacy alias
)

# trainer_interface + dataset.py shim DELETED (Jules wave).
# Tier3 flywheel orchestration (below) stubbed with clear ImportError; reexports wrapped for non-breaking guarded paths.
# Full removal after preconditions (see JULES_PY_REMOVAL_HANDOFF + PHASE4 Tier 3).

# Tier3 flywheel orchestration (skill_improver, evaluator, pending_candidates) DELETED 2026-06-13
# (20 Grok + 3 Agy terminals wave, task-2cec828e + task-5af0e350).
# All paths now use agentforge-runner. Non-breaking: old imports would have raised anyway.
# Dataset survives for eval value.

__all__ = [
    # Dataset (core, survives for eval/trajectories)
    "TrajectoryDataset",
    "TrajectoryRecord",
    "DatasetVersion",
    "TrajectoryExample",
]


# Convenience: full flywheel one-liner access
def create_learning_flywheel(name: str = "flywheel") -> TrajectoryDataset:
    """Quick entry point for the most common starting point."""
    return TrajectoryDataset(name=name)
