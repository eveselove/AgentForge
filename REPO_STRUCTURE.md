# AgentForge Repository Structure

**Status**: Official  
**Last updated**: 2026-05-31  
**Purpose**: This document provides a clear map of the AgentForge codebase for both humans and agents.

## Top-Level Layout

```
/home/eveselove/agentforge/
├── AGENTFORGE_CODE_MANAGEMENT_PLAN.md   # The main plan for professionalizing code management
├── CONTRIBUTING.md                      # Contribution guidelines (agent-first workflow)
├── AGENTS.md                            # Detailed guide for AI agents
├── README.md                            # Project overview
├── REPO_STRUCTURE.md                    # This file
│
├── bin/                                 # Automation and helper scripts
│   ├── agent-worktree                   # Git worktree helper for safe parallel agent work (MANDATORY for waves)
│   ├── pre-commit                       # Local quality gates (secrets/size/fmt/clippy/ruff etc)
│   ├── commit-msg                       # Traceability gate (Task/Jules ID; see validate-commit-msg)
│   ├── install-pre-commit               # One-command installer for pre-commit + commit-msg (worktree-safe post-bypass)
│   ├── validate-commit-msg              # Reusable validator (used by commit-msg hook)
│   └── ... (grok focused + rust flywheel tools)
│
├── agents/                              # Agent runner scripts (current: grok + agy + gemini; jules farm removed)
│   ├── grok_runner.sh
│   ├── agy_runner.sh
│   ├── gemini_runner.sh
│   └── ...
│
├── .github/
│   ├── workflows/                       # CI/CD
│   ├── CODEOWNERS
│   └── PULL_REQUEST_TEMPLATE.md
│
├── rust/                                # Rust workspace (core of the system)
│   └── crates/                          # agentforge-runner, agentforge-learning, agentforge-candidates, etc.
│
├── learning/                            # Python learning/flywheel/parity code
├── eval/                                # Evaluation trajectories and harnesses
│
├── task_queue.py + tasks.db             # Internal task queue for agent orchestration
├── pending_candidates/                  # Output of the autonomous improvement flywheel
│
└── docs/                                # Additional documentation
    └── BRANCHING_STRATEGY.md
```

## Key Components

### Agent Orchestration
- **Task Queue / Gateway** (localhost:9090, agentforge-runner + grok_worker.sh): Central system for creating, routing (preferred_agent: grok|antigravity|auto), and tracking work. Jules farm/launchers removed (2026-06 cleanup).
- **Current workers**: grok_worker.sh (polls for grok/auto, worktrees, dynamic model, Rust flywheel post-task).
- **Parallel local**: `agent-team` (tmux), `bin/agent-worktree` for isolated agent branches.

### Rust Core
The majority of the production logic lives in the Rust workspace under `rust/`.

### Documentation
All major process documents live at the root:
- `CONTRIBUTING.md`
- `AGENTS.md`
- `docs/BRANCHING_STRATEGY.md`

## Development & Agent Workflow

Most real work in this repository happens through one of these paths:

1. **Internal Task Queue (Gateway 9090 + agentforge-runner)** → grok_worker or dispatched agents pick task (preferred grok/antigravity/auto) → worktree/branch → PR → mandatory agent-review (Jules persona reviewer) + handoff → Merge
2. **Local parallel agents** via agent-team / tmux agents session + bin/agent-worktree (Grok focused post Jules farm removal)
3. **Direct / human** (rare during waves)

Jules sessions / jules-watch / launch-jules-parallel removed (JULES CLEANUP wave 2026-06-13). Traceability still supports legacy "Jules <id>" for history.

See `AGENTS.md` and `CONTRIBUTING.md` for detailed (updated) workflows.

---

*This document completes the last item of Phase 0 — Immediate Stabilization.*
