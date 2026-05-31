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
from .trainer_interface import (
    BaseTrainer,
    TrainingConfig,
    TrainingRun,
    DPOTrainer,
    KTOTrainer,
    SFTTrainer,
    get_trainer,
)
from .skill_improver import (
    SkillImprover,
    ProposedSkill,
    ImprovementProposal,
    propose_skill_improvement,
)
from .evaluator import (
    LearningEvaluator,
    ABResult,
    ArmResult,
    ABTestConfig,
    run_ab_test,
)
from .pending_candidates import (
    PENDING_DIR,
    ingest_flywheel_artifacts,
    list_pending_candidates,
    print_pending_summary,
    promote_candidate,
    get_pending_dir,
)

__all__ = [
    # Dataset
    "TrajectoryDataset",
    "TrajectoryRecord",
    "DatasetVersion",
    "TrajectoryExample",
    # Trainers
    "BaseTrainer",
    "TrainingConfig",
    "TrainingRun",
    "DPOTrainer",
    "KTOTrainer",
    "SFTTrainer",
    "get_trainer",
    # Skill improvement
    "SkillImprover",
    "ProposedSkill",
    "ImprovementProposal",
    "propose_skill_improvement",
    # A/B Evaluation
    "LearningEvaluator",
    "ABResult",
    "ArmResult",
    "ABTestConfig",
    "run_ab_test",
    # Pending candidate central storage (production flywheel track)
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
