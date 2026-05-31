# Contributing to AgentForge

AgentForge is developed using its own agent system. This document describes how we work.

## Philosophy

We practice **dogfooding**:
- Most changes go through the internal task system.
- Significant work is done by agents (Grok, Jules, Gemini, etc.).
- Human developers act as coordinators, reviewers, and high-leverage decision makers.

## Development Workflow

1. **Tasks first**
   - Most work starts as a task in the internal task queue (`task_queue.py` / port 8080).
   - Tasks have `preferred_agent`, priority, and tags.

2. **Agent execution**
   - Use `agent-team` (or `at`) to launch parallel agents.
   - Use `bin/launch-jules-parallel` for high-volume Jules work.
   - Jules sessions are tracked and automatically turned into acceptance tasks by `bin/jules-watch.sh`.

3. **Review & Acceptance**
   - All changes to `main` require a Pull Request.
   - Link PRs to task IDs and/or Jules session IDs.
   - Use the Pull Request template.

4. **Branching**
   - Prefer short-lived branches from `main`.
   - Naming convention (recommended): `agent/<short-description>` or `task/<task-id>`.

5. **Commit style**
   - Reference tasks and Jules sessions when possible:
     - `feat: add JsonFileTaskStore (Jules 12237721410778183159)`
     - `fix: ... (task 1870c84c)`

## Running Agents Locally

```bash
# Launch multiple agents
agent-team grok "task 1" "task 2"

# Launch parallel Jules using both accounts
./bin/launch-jules-parallel "task A" "task B" --count 4 --parallel 3

# Monitor Jules automation
tail -f ~/.config/jules/jules-watch.log
```

## Code Style

- **Rust**: `cargo fmt`, `cargo clippy -D warnings`
- **Python**: `ruff` + `black`
- Keep agent-related code well documented — future agents will read it.

## Questions?

Open a task in the queue or ping the current coordinator.

This process itself is part of the Code Management Professionalization effort.
