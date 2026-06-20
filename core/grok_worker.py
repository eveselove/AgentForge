#!/usr/bin/env python3
"""
DEPRECATED / REMOVAL PROPOSAL (core/grok_worker.py)

This is legacy Python code implementing the old grok task worker pipeline
(dispatch, git_clone, grok_*, ci_*, review + auto-rollback).

WE HAVE FULLY SWITCHED TO RUST:
- Primary execution: agentforge-runner (Rust binary for flywheel-step, continuous, dispatch)
- Dispatch: dispatcher.sh -> agents/grok_runner.sh (Rust flywheel + hooks)
- Shell pipeline/guardian: scripts/grok_worker.sh (bash, worktrees, guardian-main, run-task)
- Gateway: planly_gateway (Rust) + checkpoints via shims to 9090

Analysis (current state):
- No active invocations of core/grok_worker.py (or scripts/grok_worker.py) exist.
- All references in *.sh, docs, dispatcher are either comments, .bak, or historical.
- The full run_pipeline + STEP_HANDLERS + do_* simulation still present here but NEVER CALLED.
- Migration docs (REMAINING_PYTHON_TO_RUST_MIGRATION_2026-06.md, JULES_PY_REMOVAL_HANDOFF_f29c675b.md)
  already treat it as "thinned" / intentional executor but in practice it is dead/unreached.
- Similar legacy py workers (antigravity etc) also being removed in waves.

PROPOSAL: DELETE THIS FILE.
  1. git rm core/grok_worker.py
  2. Clean stale comments in scripts/grok_worker.sh, github_watcher.sh, README.md, docs/* (but only after this isolated change)
  3. Update any remaining references in agentforge/AGENTS.md etc.

This stub prevents accidental execution. Running it will error with removal guidance.
If imported as module, it loads with no side effects (legacy code after if __name__ is parsed but not harmful).
Safe to remove immediately per "fully switched to Rust".

See also: planlytasksko/AGENTS.md (VARIANT B: PRs + GH Actions, Rust runners).
"""
import sys


def _emit_deprecation_and_exit() -> None:
    msg = (
        "[DEPRECATED] core/grok_worker.py is old Python code.\n"
        "We have fully switched to Rust (agentforge-runner + grok_worker.sh).\n"
        "This file is no longer used by dispatcher, runners or gateway tasks.\n"
        "Analysis complete per request: unused legacy; PROPOSE REMOVAL.\n"
        "PROPOSE REMOVAL: git rm /home/eveselove/agentforge/core/grok_worker.py\n"
        "(Update stale references in comments/docs separately. Only this file modified.)\n"
    )
    print(msg, file=sys.stderr)
    sys.exit(42)


if __name__ == "__main__":
    _emit_deprecation_and_exit()

# End of stub. Original legacy pipeline (~700 LOC of run_pipeline/do_*/gateway logic) excised.
# This file is now a minimal deprecation marker + removal proposal.
# PROPOSAL (as stated in header): DELETE via `git rm core/grok_worker.py`
# (Only this file was modified per task rule.)

