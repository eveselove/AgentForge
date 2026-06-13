"""
Learning module (Rust Flywheel Migration Complete).
The Python orchestration layer has been successfully removed in Phase 4.

Primary exports:
- TrajectoryDataset (used for eval and backward compatibility)
"""

from .trajectory_dataset import (
    TrajectoryDataset,
    TrajectoryRecord,
    DatasetVersion,
    TrajectoryExample,  # legacy alias
)

# All orchestration paths now use agentforge-runner.

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
