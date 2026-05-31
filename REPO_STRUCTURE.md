# AgentForge Repository Structure

**Status**: Official  
**Last updated**: 2026-05-31  
**Purpose**: This document provides a clear map of the AgentForge codebase for both humans and agents.

## Top-Level Layout

```
/home/agx/agentforge/
├── AGENTFORGE_CODE_MANAGEMENT_PLAN.md   # The main plan for professionalizing code management
├── CONTRIBUTING.md                      # Contribution guidelines (agent-first workflow)
├── AGENTS.md                            # Detailed guide for AI agents
├── README.md                            # Project overview
├── REPO_STRUCTURE.md                    # This file
│
├── bin/                                 # Automation and helper scripts
│   ├── jules-watch.sh                   # Monitors completed Jules sessions and creates acceptance tasks
│   ├── launch-jules-parallel            # Launches many Jules sessions in parallel using multiple accounts
│   ├── agent-worktree                   # Git worktree helper for safe parallel agent work
│   ├── pre-commit                       # Local quality gates
│   └── install-pre-commit               # One-command installer for the hook
│
├── agents/                              # Agent runner scripts
│   ├── grok_runner.sh
│   ├── jules_runner.sh
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
- **Task Queue** (`task_queue.py` + `tasks.db`): Central system for creating, routing, and tracking work for agents. Tasks support `preferred_agent`.
- **Jules Automation**:
  - `bin/launch-jules-parallel` — Primary tool for high-volume parallel Jules work using two accounts.
  - `bin/jules-watch.sh` — Background watcher that turns completed Jules sessions into review/acceptance tasks.
- **Local Agents**:
  - `agent-team` (or `at`) — Tool for launching parallel Grok/Jules/Gemini agents in tmux.

### Rust Core
The majority of the production logic lives in the Rust workspace under `rust/`.

### Documentation
All major process documents live at the root:
- `CONTRIBUTING.md`
- `AGENTS.md`
- `docs/BRANCHING_STRATEGY.md`

## Development & Agent Workflow

Most real work in this repository happens through one of these paths:

1. **Internal Task Queue** → Agent picks up task (via `preferred_agent`) → Works in short-lived branch → PR → Review → Merge
2. **Jules sessions** → Work happens in the cloud → `jules-watch.sh` creates an acceptance task → Review + apply
3. **Direct human work** (rare during active agent waves)

See `AGENTS.md` and `CONTRIBUTING.md` for detailed workflows.

---

*This document completes the last item of Phase 0 — Immediate Stabilization.*
