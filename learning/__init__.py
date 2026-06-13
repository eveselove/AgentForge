"""
!!! AGGRESSIVE FINAL DEPRECATION SWEEP (RUST_FULL_MIGRATION_PLAN.md + PHASE4_REMOVAL_PLAN.md) !!!
Phase 2: Learning Flywheel (Foundation) — PYTHON ORCHESTRATION LAYER DEPRECATED

PHASE 4 DELETION TARGET for all flywheel orchestration (SkillImprover, pending_candidates,
evaluator flywheel paths, run_*, continuous, step glue, etc. + legacy dataset.py shim).

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

try:
    from .skill_improver import (
        SkillImprover,
        ProposedSkill,
        ImprovementProposal,
        propose_skill_improvement,
    )
except ImportError as _e:
    SkillImprover = ProposedSkill = ImprovementProposal = propose_skill_improvement = None  # type: ignore
    _tier3_import_error = _e

try:
    from .evaluator import (
        LearningEvaluator,
        ABResult,
        ArmResult,
        ABTestConfig,
        run_ab_test,
    )
except ImportError as _e:
    LearningEvaluator = ABResult = ArmResult = ABTestConfig = run_ab_test = None  # type: ignore
    _tier3_import_error = _e

try:
    from .pending_candidates import (
        PENDING_DIR,
        ingest_flywheel_artifacts,
        list_pending_candidates,
        print_pending_summary,
        promote_candidate,
        get_pending_dir,
    )
except ImportError as _e:
    PENDING_DIR = ingest_flywheel_artifacts = list_pending_candidates = print_pending_summary = promote_candidate = get_pending_dir = None  # type: ignore
    _tier3_import_error = _e

__all__ = [
    # Dataset (core, survives)
    "TrajectoryDataset",
    "TrajectoryRecord",
    "DatasetVersion",
    "TrajectoryExample",
    # Skill improvement / A/B / Pending (Tier3 stubs - may be None if pure; import raises clear guidance)
    "SkillImprover",
    "ProposedSkill",
    "ImprovementProposal",
    "propose_skill_improvement",
    "LearningEvaluator",
    "ABResult",
    "ArmResult",
    "ABTestConfig",
    "run_ab_test",
    "PENDING_DIR",
    "ingest_flywheel_artifacts",
    "list_pending_candidates",
    "print_pending_summary",
    "promote_candidate",
    "get_pending_dir",
]


# Convenience: full flywheel one-liner access
def create_learning_flywheel(name: str = "flywheel") -> TrajectoryDataset:
    """Quick entry point for the most common starting point."""
    return TrajectoryDataset(name=name)
