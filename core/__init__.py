"""
DEPRECATED / REMOVAL PROPOSAL (core/__init__.py)

AgentForge Core (package marker) — old Python orchestration platform.

Listed (now obsolete) modules:
  - task_checkpoints: Crash recovery, RAG/FTS5, shared memory, blackboard (still has body in sibling .py; used via flat sys.path shim + gw primary)
  - task_queue: Dynamic team orchestration, hierarchical delegation (long gone; no such file)
  - grok_worker: Autonomous task execution with Git auto-rollback (stubbed to deprecation exit in core/grok_worker.py)
  - agentforge_watchdog: Agent monitoring, loop detection, auto-recovery (duplicate of active root watchdog.py; thinned)
  - agentforge_create_task: CLI for agent-driven subtask creation (file deleted; now Rust MCP tool + mcp_server.py)

WE HAVE FULLY SWITCHED TO RUST (see REMAINING_PYTHON_TO_RUST_MIGRATION_2026-06.md, JULES_PY_REMOVAL_HANDOFF, PHASE4_FLYWHEEL_REMOVAL_CHECKLIST.md):
- Primary: agentforge-runner (Rust binary) for flywheel-step/continuous/candidates/dispatch
- Shims + exec: grok_worker.sh (bash), agents/grok_runner.sh
- Central state/API: Rust gateway (planly_gateway @ http://127.0.0.1:9090) — tasks, knowledge, blackboard, checkpoints via /api/*
- Create task / delegation: implemented in Rust (rust/crates/agentforge-mcp)
- No Python package imports of "core" used anywhere.

Analysis (full grep across /home/eveselove/agentforge + planlytasksko):
- ZERO occurrences of `import core`, `from core import`, `from core.xxx`, `python -m core.*`
- core/ files loaded (if ever) via:
    * sys.path.insert(..., "/.../core"); from task_checkpoints import ...  (flat names)
    * direct script exec (rare; services use root watchdog.py + grok_worker.sh)
    * historical logs / docs / .bak only
- __init__.py provides NO value: no re-exports, no __all__, no side-effect init, no version consumers.
- "task_queue" and "agentforge_create_task" entries in prior docstring were already invalid (no such modules).
- The core/ package as a whole is vestigial after Rust cutover + pure flywheel default + 14d soak complete.

PROPOSAL: DELETE THE ENTIRE core/ PACKAGE/DIR (or at minimum this __init__.py):
  git rm -r core/
  # (or just: git rm core/__init__.py ; the marker is not required for the flat-import shims in task_checkpoints.py etc.)
  Then clean stale mentions in:
    - scripts/grok_worker.sh (CHECKPOINT_PY comment)
    - README.md, docs/* (historical references)
    - any .md audit logs

This change: ONLY edited core/__init__.py (strict rule). Lightning edit. Removal proposed here for follow-up (separate task/PR per VARIANT B in planlytasksko/AGENTS.md).

If this __init__.py (or core/) is ever imported as package it is now inert + documents its own obsolescence.

See also: planlytasksko/AGENTS.md (Grok is local operator in AgentForge; changes via PRs to main, deploys via GH Actions).
"""

# No __version__ (deprecated). No other symbols.
# Passive marker only — safe, zero impact if imported.
