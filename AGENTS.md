# Agent Development Guide for AgentForge

This document describes how agents (Grok, Jules, Gemini, etc.) are expected to work inside the AgentForge project.

## Core Principles

- **Dogfooding first**: We improve AgentForge using AgentForge.
- **Task-driven**: Almost all non-trivial work starts as a task in the queue.
- **Traceability**: Every change should reference a task ID and/or Jules session when possible.
- **Parallelism**: We use multiple agents and multiple Jules accounts aggressively.

## Available Tools for Agents

| Tool | Purpose | When to use |
|------|---------|-------------|
| `agent-team` (or `at`) | Launch parallel Grok/Jules/Gemini agents in tmux | High-volume parallel work |
| `bin/launch-jules-parallel` | Launch many Jules sessions in parallel using both account keys (--count/--parallel) | Maximum throughput on coding tasks |
| `bin/jules-watch.sh` | Poll for finished Jules sessions and auto-create high-priority acceptance tasks in queue | Always running in background (--loop mode) |
| `bin/pre-commit` + `bin/install-pre-commit` | Quality gates before commit (secrets, size, fmt/clippy/ruff/black) | Before any commit (install once) |
| `bin/agent-worktree` | Isolated git worktrees for conflict-free parallel agent work | High-parallelism local agent runs |
| Task Queue (localhost:8080) | Central source of work | Primary coordination mechanism |
| `jules remote list --session` | Inspect current Jules work | Reviewing what agents have done |

## Recommended Patterns

### Starting Work
```bash
# Check current tasks
curl -s http://localhost:8080/tasks | jq '.[] | select(.status == "pending")'

# Launch several agents on related tasks
./bin/launch-jules-parallel "task description" --count 3 --parallel 4
```

### Accepting Jules Work
When `jules-watch.sh` creates an "Accept Jules session" task:
1. Review the session in the Jules web UI (look for "Publish release").
2. Pull changes: `jules remote pull --session <ID> --apply`
3. Review the diff.
4. Run tests / `cargo check` / `cargo clippy`.
5. Commit with clear attribution:
   ```
   feat: implement JsonFileTaskStore (Jules 12237721410778183159)
   ```

### Code Changes
- **Follow the full Branching Strategy** — see [docs/BRANCHING_STRATEGY.md](docs/BRANCHING_STRATEGY.md) (v1.0, task 62a84821 [CM-03]).
  - Canonical naming for agent/CM work: `agent/cm-xxx-description` (e.g. `agent/cm-03-branching-strategy-62a84821`) or `agent/<slug>`.
  - `bin/agent-worktree create <slug>` is the recommended way to get an isolated `agent/` branch + worktree.
- Install the pre-commit hook in every fresh clone / worktree: `./bin/install-pre-commit`.
- **Mandatory agent-review** for agent-generated changes before merge to `main` (run the `agent-review` skill on the diff and record the result).
- Open a PR (from the short-lived branch) before merging to `main`. Never push directly.
- Always link commits + PR to originating task ID(s) and/or Jules session (see traceability rules in the strategy doc).

## Multi-Account Strategy

We maintain two Jules accounts (keys provided by owner) to increase parallel capacity and reduce rate limiting.

Use `bin/launch-jules-parallel` when you need high concurrency.

## Monitoring

```bash
# Active agents
ta                    # attach to agents tmux session

# Jules automation logs
tail -f ~/.config/jules/jules-watch.log

# Current Jules sessions
jules remote list --session
```

## Automation Tools (`bin/`)

The `bin/` directory contains the core automation that makes the agent development loop fast and reliable:

- **`bin/install-pre-commit`** — Installs the quality gate hook in one command:
  ```bash
  ./bin/install-pre-commit
  ```
  This activates `bin/pre-commit`, which:
  - Blocks accidental secrets (AWS keys, xAI tokens, Jules keys, etc.)
  - Rejects huge files (>500KB)
  - For Rust changes: runs `cargo fmt -- --check` + `cargo clippy --workspace -D warnings`
  - For Python changes: runs `ruff check --fix` + `black --check`

- **`bin/jules-watch.sh`** — The "auto-accept" engine. Continuously watches for Jules sessions in Completed / Awaiting User state and creates ready-to-claim tasks in the local Task Queue (tagged `jules,auto-accept`). Designed for `--loop` or daemon use (systemd units exist in the repo).
  ```bash
  ./bin/jules-watch.sh --loop                 # poll every 20s (default)
  ./bin/jules-watch.sh --loop --daemon        # or run under nohup/tmux/systemd
  # Logs: ~/.config/jules/jules-watch.log
  # Env: JULES_WATCH_INTERVAL, JULES_WATCH_AUTO_APPLY, JULES_WATCH_TASK_QUEUE
  ```

- **`bin/launch-jules-parallel`** — Maximum-velocity Jules launcher using both provided account keys. Supports `--count`, `--parallel`, `--repo`.
  ```bash
  ./bin/launch-jules-parallel "implement X" "implement Y" --count 6 --parallel 3
  # Then jules-watch.sh will turn finished sessions into tasks automatically.
  ```

- **`bin/agent-worktree`** — Isolated git worktrees so dozens of agents can edit in parallel with zero conflicts on your main checkout.
  ```bash
  ./bin/agent-worktree create cm-phase2-precommit
  # ... cd into the worktree, do work, commit ...
  ./bin/agent-worktree cleanup cm-phase2-precommit
  ```

Install the pre-commit hook early. Run jules-watch.sh in a persistent tmux or via the provided systemd units for full autonomy.

## Philosophy

The goal is not just to use agents — it is to make the **development process itself** agent-native and self-improving.

This document is part of that effort.
