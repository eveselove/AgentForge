"""
DEPRECATED — SCHEDULED FOR REMOVAL (old Python code).

eval/mappings.py: Analysis of legacy Python code after full switch to Rust.

We have fully transitioned to Rust (gateway 9090, agentforge-runner, agentforge-learning,
agentforge-observability etc. per RUST_FULL_MIGRATION_PLAN.md, PHASE4_REMOVAL_PLAN.md,
REMAINING_PYTHON_TO_RUST_MIGRATION_2026-06.md dated 2026-06-13).

ORIGINAL PURPOSE:
  Mappings between Evaluation Benchmark Tasks and real AgentForge tasks.
  Tracked dispatch/status in eval_mappings.json (simple sidecar).

ANALYSIS (lightning audit):
- Data file contains ONLY 1 stale entry: "adaptive-throttle-tuning-001" → "f12a11c0" (2026-05-31).
- No evidence of active benchmark dispatch (save_mapping never called on recent runs; recent
  activity 2026-06-13 is general task-*.jsonl trajectories + post_process).
- All direct references are INTERNAL to eval/ only (cli.py status/report, runner.py,
  generate_evaluation_report.py, post_process.py lazy, export_learning_dataset.py direct json).
- No external callers from current active paths (phase2_3_integration.py and learning/ are
  themselves deprecated flywheel glue per aggressive deprecation headers).
- Rust learning crate uses benchmark_id in records but loads directly from eval results/
  trajectories/ + prm sidecars. NO reference to eval_mappings.json or this module.
- update_status in post_process (still called from grok_runner.sh / log_trajectory.sh for
  general tasks) is no-op for non-mapped keys anyway.
- Dupe loader logic exists in export_learning_dataset.py.
- Per migration docs: eval/ kept temporarily "for value" (PRM/trajectories/analysis), but
  this narrow mappings tracking for "Eval Benchmark Tasks" is obsolete.

CONCLUSION: This code is no longer used in any material way.
PROPOSAL: DELETE THE FILE eval/mappings.py + its data dir entry.

(Per strict SWARM rule only this file was modified; imports in sibling eval/*.py and
any docs referencing it must be cleaned in follow-up.)

During transition all public functions are no-op stubs + deprecation warnings.
"""
import warnings
from typing import Optional, Dict, Any

_DEPRECATED_MSG = (
    "[DEPRECATED] eval/mappings.py is legacy Python after full Rust migration "
    "(2026-06) and scheduled for removal. Benchmark/real_task linking and status "
    "tracking now via Rust datasets or obsolete. See PHASE4."
)

def _warn():
    warnings.warn(_DEPRECATED_MSG, DeprecationWarning, stacklevel=2)


def _load_mappings() -> Dict[str, Dict[str, Any]]:
    _warn()
    return {}


def _save_mappings(data: Dict[str, Dict[str, Any]]):
    _warn()
    pass


def save_mapping(
    benchmark_id: str,
    real_task_id: str,
    agent: str,
    status: str = "dispatched",
) -> None:
    """Record the link between a benchmark and a real AgentForge task. (DEPRECATED stub — no-op)."""
    _warn()
    print(f"[Mappings DEPRECATED] Ignored save: {benchmark_id} → {real_task_id}")


def update_status(benchmark_id: str, status: str, extra: Optional[Dict] = None) -> None:
    """Update the status of an existing mapping. (DEPRECATED stub — no-op)."""
    _warn()
    pass


def get_mapping(benchmark_id: str) -> Optional[Dict[str, Any]]:
    """Get the mapping for a specific benchmark. (DEPRECATED stub)."""
    _warn()
    return None


def get_all_mappings() -> Dict[str, Dict[str, Any]]:
    _warn()
    return {}


def get_real_task_id(benchmark_id: str) -> Optional[str]:
    _warn()
    return None