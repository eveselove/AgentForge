# Contributing to AgentForge

AgentForge is developed using its own agent system. This document describes how we work.

## Philosophy

We practice **dogfooding**:
- Most changes go through the internal task system.
- Significant work is done by agents (Grok, Jules, Gemini, etc.).
- Human developers act as coordinators, reviewers, and high-leverage decision makers.
- The three hard gates (pre-commit, full traceability, mandatory independent agent-review with recorded handoff) are how we keep the self-improving system reliable and auditable. Every agent (including this one) must follow them on every task.

## Local Development Environment

**MANDATORY setup on every clone / worktree / branch (before first commit):**

```bash
# 1. Hard quality + traceability gate (REQUIRED — the hook will block non-compliant commits)
./bin/install-pre-commit

# 2. (Recommended) Start grok_worker if not running (polls 9090 for tasks):
# nohup bash ~/agentforge/grok_worker.sh > /dev/null 2>&1 &
#    tail -f ~/agentforge/logs/grok_worker.log

# 3. For safe parallel agent work (recommended / mandatory for waves):
./bin/agent-worktree create cm-p2-docs-14c220fc
```

See `AGENTS.md` → "Automation Tools (`bin/`)" and the new "Mandatory Post-Work Agent-Review Step" section for the full non-negotiable rules. `pre-commit` is **not optional** — it is the local hard gate.

## Source of Truth & Mirrors (Phase 1 closure)

**Single source of truth**: https://github.com/eveselove/AgentForge (public)

All official development, CI, releases, and history live here.

- Optional read-only mirrors or git bundles may be maintained for disaster recovery / air-gapped farms in the future (see Phase 4).
- Never treat a fork or local clone as the canonical source for PRs or releases.
- This decision was recorded during the "да зыкываем все фазы" closure wave (P1 B1, Antigravity policy).

For the full branching + traceability rules see `docs/BRANCHING_STRATEGY.md`.

## Development Workflow

**This is a hard, enforced process.** All three pillars (pre-commit, traceability, agent-review) are **mandatory** — not recommendations. Violations are blocked locally by the hook or rejected at PR/merge time.

1. **Tasks first**
   - Most work starts as a task in the internal task queue (`task_queue.py` / port 8080).
   - Tasks have `preferred_agent`, priority, and tags. Reference the Task ID in every commit and PR.

2. **Agent execution**
   - Use `agent-team` (or `at`) to launch parallel Grok agents in tmux.
   - Use `bin/agent-worktree` when you need many isolated checkouts in parallel (primary now).
   - (Jules farm launchers + jules-watch removed 2026-06; tasks now mainly via gateway + grok_worker.sh or agentforge-runner.)

3. **Review & Acceptance (HARD GATES)**
   - All changes to `main` **require** a Pull Request. Never push directly.
   - **Pre-commit hook (hard gate)**: Must be installed and must have passed on every commit in the branch. It enforces formatting, linting, no secrets, size limits.
   - **commit-msg hook (hard gate for traceability)**: Enforces Task ID (or legacy Jules) via `bin/validate-commit-msg`. (Moved here in post-bypass cleanup/MICRO-05 fix so that `git commit -m "task <id> ..."` and worktree cases see the msg; pre-commit phase ran too early.) PR template also requires it. (Jules farm removed but ID format supported.)
   - **Mandatory agent-review (hard, non-negotiable final step)**: After *any* work is complete (including documentation updates), **BEFORE** you may consider the task done or open a PR, you **MUST**:
     - Invoke the `agent-review` skill (or `/agent-review --to-jules` / `grok --agent jules`).
     - Obtain an independent review from the Jules reviewer persona (or another Grok) running in a separate context.
     - Record the handoff package (`~/.grok/handoffs/<id>/`) + a summary record (see `docs/*_AGENT_REVIEW_HANDOFF.md` examples).
     - Only after the review is received and recorded may you finalize commits for PR and update the task.
     - *Note*: If a task was created via the API or `agentforge-runner` with `requires_agent_review: true`, a follow-up review task will be automatically generated upon completion.
   - Link PRs to task IDs (and/or legacy Jules session IDs). The "Related (MANDATORY)" section and checklist items for pre-commit + agent-review are required.
   - Use the Pull Request template.

4. **Branching** (see full details in [docs/BRANCHING_STRATEGY.md](docs/BRANCHING_STRATEGY.md), v1.0 from task 62a84821 [CM-03])
   - Prefer short-lived branches from latest `main`.
   - Naming convention (canonical for agent/CM work): `agent/cm-xxx-description` (e.g. `agent/cm-03-branching-strategy-62a84821`) or `agent/<slug>`.
   - Alternative good forms: `task/<id>-slug`, `jules/<session-id>` (legacy).
   - Use `./bin/agent-worktree create <slug>` for parallel isolated work (creates `agent/` branches automatically).
   - **Install hooks immediately** in the worktree/branch: `./bin/install-pre-commit` (installs pre-commit + commit-msg for traceability; now robust for worktrees).

5. **Commit style (enforced)**
   - Every commit **must** reference at least one Task ID (or legacy Jules session):
     - `feat: add JsonFileTaskStore (task 14c220fc)`
     - `docs: strengthen mandatory gates (task 14c220fc)`
     - `fix: ... (task 1870c84c)`
   - The commit-msg hook will reject commits missing the reference (unless emergency bypass env var `PRECOMMIT_BYPASS_TRACE=1` is used). (pre-commit no longer performs the msg check.)

## Running Agents Locally

```bash
# Launch multiple agents (Grok primary + Antigravity/Gemini)
agent-team grok "task 1" "task 2"

# High volume: use worktrees + grok_worker (polls queue) or agentforge-runner
# (Jules farm launch-parallel + watch removed)

# Monitor
ta                    # attach to agents tmux session
tail -f ~/agentforge/logs/grok_worker.log
curl -s http://localhost:9090/api/tasks | jq '.[0:5]'
./bin/agent-worktree list
```

## Code Style (Hard Gates)

- **Hooks installation is mandatory** (not "once" — on every environment/branch/worktree): `./bin/install-pre-commit`
- The `bin/pre-commit` hook **runs automatically and hard-blocks** `git commit` on quality violations:
  - Secrets or files > ~800KB
  - **Rust**: `cargo fmt -- --check` + `cargo clippy --workspace -D warnings` (warnings = fail)
  - **Python**: `ruff check --fix` + `black --check`
- The `bin/commit-msg` hook **hard-blocks** on missing traceability:
  - **Traceability**: Task ID (or legacy Jules session) required in the commit message (see `bin/validate-commit-msg` + `bin/commit-msg`). Enforced at correct git phase.
- Run formatters manually during dev, but the gate is the hook.
- Keep agent-related code (especially docs/AGENTS.md, CONTRIBUTING.md, runners) well documented — future agents and the self-improving system will read and enforce them.
- After any style or content change to process docs: the full mandatory agent-review step still applies (see AGENTS.md).

## Questions?

Open a task in the queue (preferred) or ping the current coordinator. All process questions should themselves follow the workflow (traceable task + agent-review on changes).

**Summary of hard requirements (non-negotiable)**:
- `./bin/install-pre-commit` before any work on a checkout/branch/worktree (installs pre+commit-msg hooks).
- Traceability in **every** commit message (enforced by commit-msg hook locally + in PRs).
- `agent-review` skill invocation + recorded independent review **after completing work and before PR** (mandatory for agent changes; see full details + examples in AGENTS.md).

This process itself is part of the Code Management Professionalization effort (dogfooding). Violations are caught by tooling.
