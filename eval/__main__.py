"""
DEPRECATED / PROPOSED FOR REMOVAL (SWARM task, 2026-06-13)

This __main__.py is a thin legacy shim enabling `python -m agentforge.eval <subcmd>`.

ANALYSIS (per instruction: analyze old Python code; project fully migrated to Rust):
- eval/ package as a whole is intentionally **KEPT FOR VALUE** (PRM scoring, trajectory logging/capture,
  view --prm, history, insights, suggest, dashboard, exports, reports, tests).
  See: docs/REMAINING_PYTHON_TO_RUST_MIGRATION_2026-06.md (KEEP FOR VALUE, post_process surgically thinned,
  flywheel orchestration excised), PHASE4_FLYWHEEL_REMOVAL_CHECKLIST.md, JULES_PY_REMOVAL_HANDOFF.
- Active runtime: trajectory population via log_trajectory.sh (sourced from grok_runner etc),
  PRM side effects, on-demand analysis. Rust observability + runner flywheel-step now primary for ingestion.
- This specific shim: NOT heavily executed in active non-doc/non-instructional code.
  - Direct submodule calls dominate runtime (python -m agentforge.eval.post_process, .run_tests in CI).
  - "python -m agentforge.eval view ..." references are in instructional strings/prompts (skills/rust-fix.yaml,
    grok_runner.sh comments) and legacy docs.
- cli.py itself defines `if __name__ == "__main__": main()`, so `python -m agentforge.eval.cli ...` works as fallback.
- Per "Мы полностью перешли на Rust": this entrypoint shim qualifies as old/unnecessary Python glue.
  Propose **deletion** of eval/__main__.py (update docs/references separately if needed; no other files touched per strict rule).

This file can be safely removed. If `python -m agentforge.eval` UX must stay, move the if __name__ block from cli.py or register console_script.

(Kept delegation below + warning for non-breaking during transition.)
"""
import sys
import warnings
from .cli import main

if __name__ == "__main__":
    warnings.warn(
        "python -m agentforge.eval (__main__.py) is deprecated legacy. "
        "Proposing removal (old Python shim post Rust migration). "
        "eval/ core (PRM/trajectories) kept for value. Use python -m agentforge.eval.cli or submodules. "
        "See REMAINING_PYTHON_TO_RUST_MIGRATION_2026-06.md",
        DeprecationWarning,
        stacklevel=2,
    )
    print("[DEPRECATED] python -m agentforge.eval is old Python; proposed for removal. Delegating to cli...", file=sys.stderr)
    main()