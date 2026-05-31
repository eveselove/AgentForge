# AgentForge Rust-Only Migration — Maximum Parallelism Tracks

**Mode:** Maximum Parallelism (activated 2026-05-31)
**Goal:** Keep as many agents as possible working simultaneously on independent pieces.

## Current Parallel Workstreams

### Track A: Deprecation & Cleanup (High volume, low complexity)
- Adding DEPRECATED banners to remaining Python files
- Cleaning Python calls from shell scripts and services
- Removing legacy assumptions

**Suitable agents:** grok, jules

### Track B: Rust Foundation (Medium complexity, high value)
- Designing Task structs and basic operations
- Improving `agentforge-runner` candidate / task CLI surface
- Creating small Rust modules for future ports

**Suitable agents:** grok (local + subagents)

### Track C: Documentation & Communication
- Updating all JULES_*.md files
- Refreshing README, checklists, roadmaps
- Creating migration status / progress artifacts

**Suitable agents:** jules, grok

### Track D: Analysis & Planning
- Inventories of Python surface
- Gap analysis per component
- Designing replacement architectures (especially Task Service)

**Suitable agents:** grok, auto

### Track E: Bridge Reduction (Strategic)
- Moving logic from Python post-process hooks into Rust
- Reducing dependency on `eval/post_process.py` and similar
- Replacing Python one-liners in operational paths with Rust or jq

**Suitable agents:** grok

## How to Work in This Mode

1. Pick a task with `[Rust-Only][Parallel]` tag.
2. Work on it in isolation.
3. When done, mark as complete (or hand off).
4. The orchestrator (current Grok session) will keep feeding new independent tasks.

This structure allows true concurrent progress across multiple agents and humans.

Last updated: 2026-05-31 (Maximum Parallelism activation)
