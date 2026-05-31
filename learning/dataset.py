"""
!!! AGGRESSIVE FINAL DEPRECATION SWEEP (RUST_FULL_MIGRATION_PLAN.md + PHASE4_REMOVAL_PLAN.md) !!!
!!! PHASE 4 DELETION TARGET — PYTHON FLYWHEEL ORCHESTRATION LEGACY SHIM !!!
learning/dataset.py — Legacy compatibility shim (re-exports TrajectoryDataset).
Tied to deprecated flywheel paths in trajectory_dataset.py (flywheel export/ingest glue).

DEPRECATED per RUST_FULL_MIGRATION_PLAN.md + PHASE4_REMOVAL_PLAN.md + learning/utils.py
MIGRATE IMMEDIATELY TO: from agentforge.learning import TrajectoryDataset (rich version; eval-safe)
  - Flywheel orchestration callers: cut over to agentforge-runner flywheel-step / continuous / candidate ...
  - Non-flywheel eval/trajectory use: may survive longer (out of Phase 4 scope).
Guard EXCLUSIVELY via central (no local copies):
  from agentforge.learning.utils import is_pure_rust_flywheel
  if is_pure_rust_flywheel():
      # short-circuit / warn / delegate to binary
      ...
Python paths execute ONLY for !is_pure_rust_flywheel() (non-breaking during transition).

Full exhaustive targets + safe removal tiers + risks + multi-layer rollback (env/dotfile/git/service):
  See learning/utils.py (THE source of truth, Phase 4 hardened)
  See PHASE4_REMOVAL_PLAN.md (definitive blueprint)
  See PHASE4_REMOVAL_CHECKLIST.md (tactical execution)

This file is Tier 1/2 supporting shim — low risk for early removal post parity/soak.
All banners + guards added in final aggressive sweep 2026-05-31.
"""

from .trajectory_dataset import (
    TrajectoryDataset as _ModernTrajectoryDataset,
    TrajectoryRecord as TrajectoryExample,
    TrajectoryDataset,
)

# Re-export the old names exactly as they were for zero-breakage
__all__ = ["TrajectoryDataset", "TrajectoryExample"]

# Note: the modern TrajectoryDataset is dramatically more powerful (versioning, full PRM,
# multi-format exports, etc.) while remaining API-compatible for the basic methods that existed.
