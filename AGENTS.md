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
| `bin/launch-jules-parallel` | Launch many Jules sessions using both keys | Maximum throughput on coding tasks |
| `bin/jules-watch.sh` | Automatically detect finished Jules sessions and create acceptance tasks | Always running in background |
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
- Work on short-lived branches.
- Open a PR before merging to `main`.
- Always link the PR to the originating task(s).

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

## Philosophy

The goal is not just to use agents — it is to make the **development process itself** agent-native and self-improving.

This document is part of that effort.
