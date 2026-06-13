# -*- coding: utf-8 -*-
"""
DEPRECATED Tier 3 (Jules continuation 2026-06-13, task f29c675b + доделывай).
Superseded by agentforge-runner:
  flywheel-step --real-data --ingest
  continuous --top-n N [--shadow]
  candidate list/promote ...

See docs/JULES_PY_REMOVAL_HANDOFF_f29c675b.md and PHASE4_FLYWHEEL_REMOVAL_CHECKLIST.md.

On import: raises ImportError with migration guidance (non-breaking for guarded paths that catch).
"""

_MESSAGE = (
    f"{__name__} is DEPRECATED Tier 3 per PHASE4. "
    "Use `agentforge-runner flywheel-step --real-data --ingest`, "
    "`continuous --top-n N`, or `candidate list/promote` instead. "
    "Full removal after preconditions (cargo green, 14d pure soak, clean audit, marker)."
)


class _DeprecatedModule:
    def __getattr__(self, name):
        raise ImportError(_MESSAGE)


# On import of the module itself, raise clear guidance (callers that do `import ...` or `from ... import` will see it)
# For guarded code (if is_pure... : ...), they can avoid the import.
raise ImportError(_MESSAGE)

if __name__ == "__main__":
    print(_MESSAGE)
    # task-5af0e350: evaluator no longer drives flywheel, direct if invoked
    import os
    import sys

    runner = (
        os.environ.get("AGENTFORGE_RUST_RUNNER")
        or "/home/eveselove/agentforge/rust/target/release/agentforge-runner"
    )
    if os.path.isfile(runner) and os.access(runner, os.X_OK):
        args = [runner, "--help"] + sys.argv[1:]
        print(f"  Directing evaluator stub to pure runner help: {' '.join(args)}")
        try:
            os.execv(runner, args)
        except Exception:
            pass
    sys.exit(1)

# AGGRESSIVE FINAL DEPRECATION SWEEP (PHASE4_REMOVAL_PLAN.md) - task-5af0e350 pure soak prep
