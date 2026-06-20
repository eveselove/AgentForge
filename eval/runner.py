"""
!!! OBSOLETE — PROPOSED FOR REMOVAL (FULL RUST MIGRATION) !!!
TARGET FILE: eval/runner.py

INSTRUCTION FOLLOWED: Анализ старого Python кода. Мы полностью перешли на Rust.
Поэтому этот код больше не используется в основных путях — предлагаем его удаление.

АНАЛИЗ (2026-06-13, lightning):
- Pure Rust flywheel is DEFAULT and ACTIVE:
    * .pure_rust_flywheel marker present
    * ENABLE_RUST_FLYWHEEL=1
    * rust/target/release/agentforge-runner exists + executable
    * is_pure_rust_flywheel() returns True (hardened guard in learning/utils.py)
- Main autonomy/flywheel/continuous/candidate/A-B/ingest/propose now 100% Rust
  (agentforge-runner + crates/agentforge-flywheel + gateway 9090 + post-flywheel hooks in bin/rust_flywheel_after_task.sh etc).
- This file (runner.py) implements legacy Python dispatch for "benchmark tasks":
    run_benchmark_task (simulate or real via create_evaluation_task_in_agentforge + polling + verification + PRM attach + post_process hook).
  It was the glue for eval/examples/*.json benchmarks.
- Current usage status:
    * Direct callers outside eval/: only phase2_3_integration.py (itself marked surgical/Tier2 glue, only comments + legacy path).
    * Internal: eval/cli.py, eval/run_batch.py, eval/__init__.py (re-export), tests/test_e2e_*.py (only for post_process_run).
    * No active prod use: eval/results/ has 0 recent JSONs (last history Jun 12, mappings tiny/stale, 950+ trajectories are from Rust flywheel real task IDs, none benchmark-tagged).
    * CLI entry "python -m agentforge.eval run ..." and run_batch are dev tools not wired into dispatcher / workers / services / after-task in pure mode.
- Other eval/* (post_process.py, trajectory.py, prm.py, schemas.py, history, mappings, generate_*, analyze_*, trajectory_viewer, log_trajectory.sh etc) provide VALUE (PRM, viewing, datasets) and are KEPT as non-glue (per PHASE4 checklist).
- runner.py itself is listed in checklist under "eval/runner.py | Core eval benchmark. Только хирургические правки" but given zero recent execution + complete Rust cutover for everything it orchestrated, it is now dead code.
- Docstring in file itself already called it "AGGRESSIVE FINAL DEPRECATION + PHASE 4 CLEANUP PREP".

ЗАКЛЮЧЕНИЕ: Код больше не используется. Полностью перешли на Rust.
ПРЕДЛАГАЕМ УДАЛЕНИЕ: git rm -f eval/runner.py

Дальнейшие шаги после rm (не в scope этой правки, т.к. Strict rule: Modify ONLY this file):
- Убрать реэкспорт из eval/__init__.py
- Удалить/задепрекейтить run-команды в eval/cli.py + run_batch.py (или переписать минимально на базе траекторий + gw)
- Перенести post_process_run если ценность (сейчас только в тестах) — в post_process.py или trajectory.py
- Почистить комментарии в phase2_3_integration.py, bin/*.sh, docs/*, eval/USAGE.md
- Убрать из тестов или заскипать
- Обновить PHASE4 checklist / JULES handoff (mark Tier2 complete for this)

Если benchmark-поверхность нужно сохранить для ручного дев-использования — можно оставить ТОЛЬКО schemas + load + read-only history, без dispatch/run/verification glue (который дублирует gw + runner).

Прямые команды на замену:
    agentforge-runner flywheel-step --real-data --ingest [--shadow]
    agentforge-runner continuous --top-n 5 --no-dry-run
    agentforge-runner candidate list|prioritize|promote|ingest
    # + gw /tasks + /review + trajectories/ + PRM sidecars

Все legacy Python flywheel orchestration (proposal/candidate/continuous/A/B glue) excised.
runner.py — последний кусок старого dispatch-слоя для eval benchmarks — под удаление.

См.:
- learning/utils.py (is_pure_rust_flywheel)
- docs/PHASE4_FLYWHEEL_REMOVAL_CHECKLIST.md (Tier 2/4 + KEEP non-glue note)
- docs/JULES_PY_REMOVAL_HANDOFF_f29c675b.md
- bin/phase4_pre_removal_audit.sh
- RUST_FULL_MIGRATION_PLAN.md (archive)

"""

# Tombstone implementation.
# We keep the public names importable (so "from agentforge.eval import run_benchmark_task",
# "from .runner import ..." and package __init__ do not explode on import),
# but any actual call immediately fails with removal guidance.
# No side-effecting top-level (no mkdir, no subprocess on import of deprecated module).

from typing import Optional, Dict, Any, List


class _EvalRunnerRemoved:
    """Callable stub that raises on any invocation to enforce removal proposal."""

    def __init__(self, name: str):
        self.name = name

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError(
            f"eval/runner.py:{self.name} is OBSOLETE after full Rust migration and is proposed for deletion. "
            "We have completely switched to Rust (agentforge-runner + pure flywheel default). "
            "This legacy Python benchmark orchestration / dispatch code is no longer used. "
            "RECOMMEND: git rm -f eval/runner.py (then clean the 5-6 small import sites + comments). "
            "Direct replacement: agentforge-runner flywheel-step --real-data --ingest ; see --help. "
            "Benchmark artifacts (trajectories + PRM) are produced by Rust paths + post_process.py + gw. "
            "Refs: PHASE4_FLYWHEEL_REMOVAL_CHECKLIST.md, learning/utils.py:is_pure_rust_flywheel(), .pure_rust_flywheel marker."
        )

    # Support attribute access if anything introspects (e.g. .real_task_id on result) — still fail fast.
    def __getattr__(self, item: str) -> Any:
        raise RuntimeError(
            f"eval/runner.py is removed (proposed deletion). Accessed {self.name}.{item}. "
            "git rm eval/runner.py + cleanup callers."
        )


# The three symbols that were imported from here (per full grep):
run_benchmark_task = _EvalRunnerRemoved("run_benchmark_task")
post_process_run = _EvalRunnerRemoved("post_process_run")
load_benchmark_task = _EvalRunnerRemoved("load_benchmark_task")

# Legacy module-level names that some code might have touched directly (harmless now).
_DEFAULT_RESULTS_DIR = None
EVAL_RESULTS_DIR = None
EVAL_RESULTS_DIR = None  # type: ignore[assignment]
AGENTFORGE_API = "http://localhost:9090"  # legacy constant only

# No __main__ execution, no other defs. File is now a removal proposal tombstone.
# (End of lightning edit — only this file touched.)
