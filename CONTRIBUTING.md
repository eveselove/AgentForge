# Contributing to AgentForge

AgentForge is developed using its own agent system. This document describes how we work.

## Philosophy

We practice **dogfooding**:
- Most changes go through the internal task system.
- Significant work is done by agents (Grok, Jules, Gemini, etc.).
- Human developers act as coordinators, reviewers, and high-leverage decision makers.

## Local Development Environment

Set up the automation tools once:

```bash
# Quality gates on every commit (strongly recommended)
./bin/install-pre-commit

# Optional but powerful: run Jules session watcher in background
# (creates "Accept Jules work" tasks automatically when sessions finish)
nohup ./bin/jules-watch.sh --loop >/dev/null 2>&1 &
# or: tail -f ~/.config/jules/jules-watch.log

# For extreme parallel agent work without checkout conflicts:
./bin/agent-worktree create my-parallel-task
```

See `AGENTS.md` → "Automation Tools (`bin/`)" for full details on `jules-watch.sh`, `launch-jules-parallel`, `pre-commit`, and `agent-worktree`.

## Source of Truth & Mirrors (Phase 1 closure)

**MIRROR_STRATEGY** (official): see the dedicated section in `docs/BRANCHING_STRATEGY.md` (v1.3).

**Single source of truth**: https://github.com/eveselove/AgentForge (public)

All official development, CI, releases, and history live exclusively here.

- Optional read-only mirrors or git bundles may be maintained for disaster recovery / air-gapped farms in the future (see Phase 4 / B2).
- Never treat a fork or local clone as the canonical source for PRs or releases.
- This decision (P1 B1) was recorded during the "да зыкываем все фазы" closure wave (Antigravity policy, tasks d68486fc / 5f018f81).

For full branching + traceability rules see `docs/BRANCHING_STRATEGY.md`.

## Development Workflow

1. **Tasks first**
   - Most work starts as a task in the internal task queue (`task_queue.py` / port 8080).
   - Tasks have `preferred_agent`, priority, and tags.

2. **Agent execution**
   - Use `agent-team` (or `at`) to launch parallel agents in tmux.
   - Use `bin/launch-jules-parallel` for high-volume / maximum-speed Jules work (uses both keys).
   - Use `bin/agent-worktree` when you need many isolated checkouts in parallel.
   - Jules sessions are tracked and automatically turned into acceptance tasks by `bin/jules-watch.sh` (run it in `--loop` mode for full autonomy).

3. **Review & Acceptance**
   - All changes to `main` require a Pull Request.
   - Link PRs to task IDs and/or Jules session IDs (use the PR template).
   - **Mandatory agent review** (via `agent-review` skill or equivalent) for agent-authored changes before merge (see Branching Strategy).
   - Use the Pull Request template.

4. **Branching** (see full details in [docs/BRANCHING_STRATEGY.md](docs/BRANCHING_STRATEGY.md), v1.0 from task 62a84821 [CM-03])
   - Prefer short-lived branches from latest `main`.
   - Naming convention (canonical for agent/CM work): `agent/cm-xxx-description` (e.g. `agent/cm-03-branching-strategy-62a84821`) or `agent/<slug>`.
   - Alternative good forms: `task/<id>-slug`, `jules/<session-id>`.
   - Use `./bin/agent-worktree create <slug>` for parallel isolated work (creates `agent/` branches automatically).
   - Install pre-commit hook in the worktree: `./bin/install-pre-commit`.

5. **Commit style**
   - Reference tasks and Jules sessions when possible:
     - `feat: add JsonFileTaskStore (Jules 12237721410778183159)`
     - `fix: ... (task 1870c84c)`

## Running Agents Locally

```bash
# Launch multiple agents (Grok / Jules / Gemini)
agent-team grok "task 1" "task 2"
agent-team jules "implement feature X"

# Launch many Jules sessions in true parallel (both keys)
./bin/launch-jules-parallel "task A" "task B" --count 6 --parallel 2

# Monitor everything
ta                    # attach to agents tmux
tail -f ~/.config/jules/jules-watch.log
./bin/agent-worktree list
```

## Code Style

- Install the hook once: `./bin/install-pre-commit`
- The `bin/pre-commit` hook (runs automatically on `git commit`) enforces:
  - No secrets or huge files
  - **Rust**: `cargo fmt -- --check` + `cargo clippy --workspace -D warnings`
  - **Python**: `ruff check --fix` + `black --check`
- You can (and should) still run the formatters manually during development.
- Keep agent-related code well documented — future agents will read it.

## Questions?

Open a task in the queue or ping the current coordinator.

This process itself is part of the Code Management Professionalization effort.
