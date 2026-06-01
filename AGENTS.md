# Agent Development Guide for AgentForge

This document describes how agents (Grok, Jules, Gemini, etc.) are expected to work inside the AgentForge project.

## Core Principles

- **Dogfooding first**: We improve AgentForge using AgentForge.
- **Task-driven**: Almost all non-trivial work starts as a task in the queue.
- **Traceability (enforced)**: Every commit/PR **must** reference a Task ID (e.g. task 90fcbf89) or Jules session. Enforced by `bin/pre-commit` (hard gate) + `bin/validate-commit-msg` + `.gitmessage` template. CI will also check soon. See docs/BRANCHING_STRATEGY.md.
- **Parallelism**: We use multiple agents and multiple Jules accounts aggressively.

## Available Tools for Agents

| Tool | Purpose | When to use |
|------|---------|-------------|
| `agent-team` (or `at`) | Launch parallel Grok/Jules/Gemini agents in tmux | High-volume parallel work |
| `bin/launch-jules-parallel` | Launch many Jules sessions in parallel using both account keys (--count/--parallel) | Maximum throughput on coding tasks |
| `bin/jules-watch.sh` | Poll for finished Jules sessions and auto-create high-priority acceptance tasks in queue | Always running in background (--loop mode) |
| `bin/pre-commit` + `bin/install-pre-commit` | **Hard mandatory** quality + traceability gates before every commit (secrets, size, Rust fmt+clippy -D warnings, Python ruff+black, Task/Jules ID via validate-commit-msg). Blocks bad commits. | **Mandatory install** in every clone/worktree/branch before first commit: `./bin/install-pre-commit` |
| `bin/agent-worktree` | Isolated git worktrees for conflict-free parallel agent work (MANDATORY for extreme waves) | High-parallelism local agent runs |
| `bin/validate-commit-msg` + `.gitmessage` | Enforce Task ID / Jules session on every commit (hard gate in pre-commit) | Always |
| `agent-review` skill (or `/agent-review --to-jules`) | Mandatory independent cross-agent code review + handoff packaging after any work, before PR (hard requirement, produces auditable `~/.grok/handoffs/` record) | After EVERY completed task / change set (see dedicated section below) |
| `bin/consume-handoff-reviews.py` | **Post-100% Hardening (c48c5f56)**: Scans `~/.grok/handoffs/` for completed reviews (`jules-review-*.md`), bulk-approves via conservative heuristics, PATCHes originating task (from metadata) to `done` with full traceable notes + links. Idempotent, --dry-run safe by default, --stats/--list. | After review waves; manual or automated to clear "review" / post-handoff backlog |
| Task Queue (localhost:8080) | Central source of work | Primary coordination mechanism |
| `docs/PHASE{1,2,3}_TASK_BREAKDOWN.md` | Current parallel attack surface for closing Code Mgmt Plan (pick tasks here) | During all-phases closure waves |
| `docs/REVIEW_CHECKLIST.md` | Mandatory self-check + external agent-review steps before every PR (P2 B5) | Always for agent changes |
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
3. Review the diff + run local validation (`cargo test`, `cargo clippy`, etc.).
4. **MANDATORY**: Perform the full agent-review step (see "Mandatory Post-Work Agent-Review Step" section above) — invoke `agent-review` skill / `/agent-review --to-jules`, record handoff + result.
5. Only after independent review is obtained and recorded: commit with clear attribution + task/Jules reference:
   ```
   feat: implement JsonFileTaskStore (Jules 12237721410778183159, task 14c220fc)
   ```
   Then open PR (never direct to main).

### Code Changes
- **Follow the full Branching Strategy** — see [docs/BRANCHING_STRATEGY.md](docs/BRANCHING_STRATEGY.md) (v1.0, task 62a84821 [CM-03]).
  - Canonical naming for agent/CM work: `agent/cm-xxx-description` (e.g. `agent/cm-03-branching-strategy-62a84821`) or `agent/<slug>`.
  - `bin/agent-worktree create <slug>` is the recommended way to get an isolated `agent/` branch + worktree.
- **Pre-commit hook is MANDATORY (hard gate)**: Install in every fresh clone / worktree / branch before first commit: `./bin/install-pre-commit`. The hook blocks commits that fail secrets/size checks, Rust fmt+clippy (`-D warnings`), Python ruff+black, or **traceability**. Shellcheck on .sh files is advisory unless `PRECOMMIT_STRICT=1` (then becomes hard gate). Never bypass except in documented emergencies (see Bypass Policy below).
- Always link commits + PR to originating task ID(s) and/or Jules session (see traceability rules in the strategy doc). This is **hard-enforced** by `bin/pre-commit` + `bin/validate-commit-msg` (pattern: `task <short-id>` or `Jules <full-session-id>`).
- Open a PR (from the short-lived branch) before merging to `main`. Never push directly. All PRs must reference task/Jules ID (see PR template).

**Bypass Policy (pre-commit)**:
  - Bypasses exist **only** for true emergencies (e.g. recovering a broken main that prevents any commit, or one-off env where a tool is missing in a critical hotfix path).
  - Preferred (granular):
    - `PRECOMMIT_BYPASS_TRACE=1 git commit ...` — only skips the task/Jules ID check.
    - `PRECOMMIT_STRICT=0 git commit ...` — run shellcheck (and future strict checks) in advisory mode.
    - `PRECOMMIT_BYPASS_SHELLCHECK=1 ...` or `PRECOMMIT_BYPASS=1 ...` — skip shellcheck enforcement under STRICT.
  - Ultimate hammer: `git commit --no-verify` (git-native, bypasses the entire hook).
  - **Rule**: Every bypass **must** be followed by:
    1. Immediate creation of a high-priority "post-bypass cleanup / investigation" task in the queue.
    2. A short note in the commit body explaining the emergency.
    3. Post-commit run of the skipped checks + fix in a follow-up commit (no --no-verify on the fix).
  - Routine use of bypass (to "save time") is a policy violation and will be caught in agent-review.

### Mandatory Post-Work Agent-Review Step (HARD REQUIREMENT, non-negotiable)
**After completing ANY work** (code, docs, scripts, tasks — including this one), you **MUST** perform the agent-review step **before** marking the task ready, committing final changes for PR, or opening a PR:

1. Ensure all local changes are complete and tests/lints pass locally. Run the full self-check from `docs/REVIEW_CHECKLIST.md` (P2 B5 deliverable, derived from 2026-05-31 wave defects).
2. **OBLIGATORY invocation** (exact per task spec and AGENTS.md):
   - Call the skill: `agent-review` (or `/agent-review --to-jules`, `/agent-review --agent jules`, or equivalent via the `agent-review` skill in `~/.grok/skills/agent-review/`).
   - This packages the diff + full context into a portable handoff under `~/.grok/handoffs/<id>/` (with `diff.patch`, `context.md`, `metadata.json`, `REVIEW_INSTRUCTIONS.md`).
   - It launches (or prepares for) an **independent** reviewer (Jules recommended, or another named Grok) running in a separate session/context with its own memory and the strict reviewer persona.
3. Obtain the independent review. The reviewer produces a structured report (Summary + Issues: bugs/suggestions/nits with File:line).
4. **Record the result** (fixed auditable artifact):
   - Create or append to a handoff record (e.g. `docs/<SLUG>_AGENT_REVIEW_HANDOFF.md` modeled on `docs/A2_BRANCH_PROTECTION_AGENT_REVIEW_HANDOFF.md` and `docs/A7_BRANCH_PROTECTION_AGENT_REVIEW_HANDOFF.md`).
   - Include: handoff ID + absolute path, reviewer identity, key findings (counts + excerpts), how issues were addressed (or why non-blocking), links to task/Jules.
   - Reference this record + handoff dir in the commit message, PR description, and task result.
5. **Consume reviewed handoffs (Post-100% Hardening automation)**:
   - After independent reviews land as `jules-review-*.md` inside `~/.grok/handoffs/<id>/`, run the consumer (safe first):
     ```bash
     python3 bin/consume-handoff-reviews.py --stats --list
     python3 bin/consume-handoff-reviews.py --dry-run --verbose --limit 20
     python3 bin/consume-handoff-reviews.py --apply --handoff-id <id1>,<id2>   # or without filter for bulk clear approved ones
     ```
   - The script (c48c5f56) is the long-term mechanical closer for the review backlog. It only advances on explicit APPROVE heuristics (or --all-reviewed after vetting), writes .consumed markers, and injects rich result notes with full paths/links for traceability. Idempotent and logged.
6. **ONLY THEN**:
   - Consider the task complete / ready for acceptance.
   - Open the PR (from short-lived branch).
   - Update the originating task in the queue with status, links to review artifacts, and result summary.

**Examples of recorded mandatory steps**:
- `docs/A2_BRANCH_PROTECTION_AGENT_REVIEW_HANDOFF.md` (task bc6fa462)
- `docs/A7_BRANCH_PROTECTION_AGENT_REVIEW_HANDOFF.md`
- `docs/A1_BRANCH_PROTECTION_RESEARCH_REPORT.md` (includes handoff 1f3ceb91)
- `docs/REVIEW_CHECKLIST_AGENT_REVIEW_HANDOFF.md` (this checklist + related doc updates, P2 B5)

This is the **judgment layer** that replaces traditional "required GitHub approvals" (see Branch Protection A7 decision). It is mandatory for all agent-generated changes before merge to `main`. 

**Agent-review is now the default path**: Every agent (Grok, Antigravity, etc.) must run it after work and usually create a follow-up review task. This is the standard for the current closure waves.

**CI Enforcement (Post-100% Hardening, task ee507687)**: The GitHub Actions job `agent-review-link` (powered by `bin/check-agent-review-link.sh`) is a **hard gate** for all PRs originating from `agent/` or `jules/` branches. The PR title or body **must** contain evidence of the completed agent-review + handoff record (e.g. handoff ID like "8806e0a2", "agent-review", "AGENT_REVIEW_HANDOFF", or link to the handoff doc). Missing evidence causes the CI job to fail. Use `AGENT_REVIEW_ADVISORY=1` only for local debugging. This makes the AGENTS.md process mechanically non-bypassable at the CI layer while preserving Level M2 (0 GitHub approvals).

Failure to follow this (or pre-commit/traceability) will cause the PR to be rejected during agent-review or CI gates.

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

- **`bin/install-pre-commit`** — **MANDATORY** one-command installation of the hard quality+traceability gate hook:
  ```bash
  ./bin/install-pre-commit
  ```
  Run this **immediately** on every fresh clone, worktree, or new branch before any `git commit`.
  The hook (`bin/pre-commit`) is a **hard gate** (exits non-zero on failure):
  - Blocks secrets and files >800KB
  - Rust: `cargo fmt -- --check` + `cargo clippy --workspace -D warnings` (fail on warnings)
  - Python: `ruff check --fix` + `black --check`
  - **Shellcheck**: advisory by default on staged .sh files. Set `PRECOMMIT_STRICT=1` to make it a hard blocking gate (like Rust/Python).
  - **Traceability (hard)**: requires Task ID or Jules session in commit message (via `bin/validate-commit-msg`, bypass only via `PRECOMMIT_BYPASS_TRACE=1` in true emergencies)
  - Full env controls and bypass policy documented in `bin/pre-commit` header + `bin/install-pre-commit` output.
  See also "Code Changes" and the agent-review section.

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
