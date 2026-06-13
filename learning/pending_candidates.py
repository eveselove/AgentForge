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
import sys as _sys

_MESSAGE = (
    f"{__name__ or pending_candidates} is DEPRECATED Tier 3 per PHASE4. "
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
    _sys.exit(0)
