# AgentForge Repository Structure

This document describes the layout of the AgentForge project.

## Top Level

- `AGENTFORGE_CODE_MANAGEMENT_PLAN.md` — The plan for professionalizing code management (this effort)
- `CONTRIBUTING.md` — How to contribute (agent-first workflow)
- `AGENTS.md` — Detailed guide for AI agents working on the project
- `README.md` — High-level overview
- `bin/` — Automation and helper scripts (jules-watch, launch-jules-parallel, agent-worktree, etc.)
- `agents/` — Runner scripts for different agent types (grok_runner.sh, jules_runner.sh, ...)
- `rust/` — The Rust workspace (8 crates)
  - Main crates: agentforge-runner, agentforge-learning, agentforge-candidates, etc.
- `learning/` — Python learning / flywheel / parity harness code
- `eval/` — Evaluation trajectories, harnesses, and fixtures
- `tasks.db` + `task_queue.py` — Internal task system for agent orchestration
- `pending_candidates/` — Output of the autonomous improvement flywheel
- `services/` and systemd units — Production deployment configuration
- `.github/` — GitHub workflows, templates, and CODEOWNERS

## Key Automation

- `bin/jules-watch.sh` — Continuously monitors Jules sessions and creates acceptance tasks
- `bin/launch-jules-parallel` — Launches many Jules sessions in parallel using multiple accounts
- `agent-team` (or `at`) — Primary tool for launching parallel Grok/Jules/Gemini agents

## Development Model

Most real work happens through:
1. Tasks in the internal queue (preferred_agent routing)
2. Jules sessions (asynchronous coding agent)
3. Local Grok agents via `agent-team`

See `AGENTS.md` and `CONTRIBUTING.md` for details.

---

*This document was created as part of Phase 0 of the Code Management Professionalization effort.*
