# AgentForge Rust Migration — Speed Mode / Unblock Development

**Activated:** 2026-05-31 (following request for maximum speed because development is blocked)

## Goal
Finish the parts of the Rust migration that are **actively blocking real development work** as fast as possible.

## Current Critical Path (What is blocking development the most)

1. **Task Management Layer (Biggest Blocker)**
   - Currently lives in Python: `task_queue.py` + `mcp_server.py` + creation scripts.
   - All agent work (Jules, Grok, etc.) flows through this.
   - Until there is a solid Rust-native way to create, queue, and dispatch tasks, development cannot fully move to the new system.

2. **Reliable way for agents to receive and report work**
   - Related to the above. The conveyor must work without heavy Python dependency.

3. **Core CLI surface for everyday operations**
   - `agentforge-runner` must be able to handle the main flows that developers and agents use daily.

Everything else (banners, small cleanups, docs polish, peripheral scripts) is secondary until the above are unblocked.

## Speed Strategy (Different from Pure Maximum Parallelism)

- **Focus, not flood**: Prioritize a small number of high-impact work packages over hundreds of tiny tasks.
- **Bigger parallel chunks**: Create fewer but meatier tasks that can still run in parallel (e.g., "Design Rust Task API", "Prototype basic task storage", "Migrate task creation scripts", etc.).
- **Orchestrator + Executors**: Current session acts as orchestrator + does high-leverage direct work. Agents (Jules + subagents) take well-scoped parallel pieces.
- **Fast feedback loops**: Prioritize things that can show visible progress toward unblocking development quickly.

## Current Priority Order (Speed Mode)

**P0 (Unblock Development) - Active**
- Design and start prototyping a minimal viable Rust Task Service / API  ✅ Started
  - Basic Task model + InMemoryTaskStore implemented in `agentforge-core`
  - First real Rust code for task management written (2026-05-31)
- Define the minimal Task model + operations needed ✅ In progress
- Make it possible to create and dispatch tasks without Python

**P1 (Make the new system usable)**
- Solid `agentforge-runner` support for task-related operations (prototype CLI commands)
- Migration path for existing task creation flows

**P2 (Hygiene & Completeness)**
- Banners, script cleanups, docs, full Python removal (can run in background)

## How We Execute Now

1. Heavy focus on P0 items.
2. Create 4–8 high-value parallel tasks around the Task layer and critical CLI.
3. Direct work on architecture + initial Rust code for the Task Service.
4. Use agents for supporting work (docs, analysis, small cleanups) but not as the main driver for the blocker.
5. Regular short status on what is actually unblocked.

This mode stays active until the main development-blocking pieces are in a usable state.

Last updated: 2026-05-31
