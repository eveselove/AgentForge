# Branching Strategy for Agent-Driven Development

**Status**: v1.0 — Authoritative (defined under task 62a84821 [CM-03])  
**Date**: 2026-05-31  
**Owner**: Current agent swarm (Grok 4.3 + parallel agents) — dogfooding

This is the official branching model for AgentForge. It enables safe, high-parallelism development by autonomous agents while keeping `main` clean and always green.

## Core Model: Trunk-Based + Short-Lived Agent Branches

- `main` is the single source of truth and must remain in a deployable state (green CI, no obvious breakage).
- **All changes to `main` happen exclusively through Pull Requests.** No direct pushes (enforced via GitHub branch protection when fully configured).
- Both humans and agents use **short-lived branches** (hours to a few days max).
- We optimize for extreme parallelism: dozens of agents (Grok, Jules x2 accounts, Gemini, etc.) working simultaneously via `bin/agent-worktree` isolation.
- Recommended base model from the Code Management Plan: trunk-based development.

## Branch Naming Conventions

Use the following prefixes. The `agent/cm-` pattern is the explicit recommendation from task 62a84821 for Code Management work and is the preferred form for most agent-driven changes.

| Prefix                    | Purpose / Who                          | Example                                           |
|---------------------------|----------------------------------------|---------------------------------------------------|
| `agent/cm-xxx-...`        | CM Phase 2/3 + general agent work (canonical for task-linked agent branches) | `agent/cm-03-branching-strategy-62a84821`        |
| `agent/<slug>`            | Any agent-initiated work (auto-created by `bin/agent-worktree`) | `agent/fix-taskstore-atomic`, `agent/implement-xai-keys` |
| `task/<id>-<slug>`        | Explicit link to internal task queue entry | `task/62a84821-branching-precommit`              |
| `jules/<full-session-id>` | Work originating directly from a Jules session | `jules/12237721410778183159`                     |
| `human/<name>/<topic>`    | Human exploratory/spike/debug work     | `human/agx/rust-migration-audit`                 |
| `backup/...`              | Rare long-lived archival or rollback snapshots | `backup/pre-management-2026-05-31`               |

**Slug guidelines**:
- kebab-case, lowercase letters + digits + hyphens only
- Max ~60 characters
- Include the task ID (short form) whenever the work is task-driven for full traceability
- `bin/agent-worktree create <raw-slug>` will auto-slugify and prefix with `agent/`

The task record for 62a84821 pre-suggested `git_branch: "agentforge/62a84821"`. In practice we normalize to the `agent/cm-...` or `agent/<slug>` forms above.

## Agent & Human Workflow (Standard Path)

1. **Sync** — `git fetch && git checkout main && git pull --ff-only`
2. **Create isolated workspace** (strongly preferred for agents):
   ```bash
   ./bin/agent-worktree create cm-03-branching-precommit-62a84821
   cd /tmp/agentforge-work/cm-03-branching-precommit-62a84821
   ```
   Or manual branch:
   ```bash
   git checkout -b agent/cm-03-branching-strategy-62a84821
   ```
3. **Do the work** using the full AgentForge stack (`implement` skill, `agent-review`, etc.).
4. **Quality gates before commit**:
   - `./bin/install-pre-commit` (first time in this checkout)
   - The hook runs automatically, or invoke checks manually:
     - Rust: `cargo fmt -- --check && cargo clippy --workspace -- -D warnings`
     - Python: `ruff check . && black --check .`
5. **Commit** with explicit task/Jules traceability (see examples in AGENTS.md).
6. **Push + PR early** (even for WIP — use draft PRs). Use `.github/PULL_REQUEST_TEMPLATE.md`.
7. **Mandatory agent review** (see section below).
8. CI must pass.
9. Merge to `main` (prefer squash for agent PRs to keep history clean).
10. Cleanup:
    ```bash
    ./bin/agent-worktree cleanup cm-03-branching-precommit-62a84821 --force
    git branch -d agent/cm-03-... 2>/dev/null || true
    ```

## Mandatory Agent Review Gate

This is a Phase 2 requirement (see CM plan + task 62a84821 description):

- **Before any PR is eligible for merge to `main`, it must receive documented review from at least one autonomous agent.**
  - Preferred: run the `agent-review` skill against the branch diff and post the output.
  - Acceptable: Jules review session summary, detailed Grok/Gemini analysis recorded in PR comments.
- The review must cover at least: correctness, no breakage to agent runtime/flywheel, adherence to style, test coverage where applicable.
- Human merge approval is still possible, but agent review is the default and expected path for the majority of changes.
- Record the review reference (session, log path, or skill output hash) in the PR description or a top-level comment.

This rule makes the development process itself self-reviewing and dogfooded.

**Exceptions**: Trivial doc fixes, `.md` only changes, or coordinator-declared emergencies. Still require a PR.

## Traceability Requirements

- Every commit message that represents real work **must** mention a task ID and/or Jules session ID.
- Every PR **must** fill the "Related" section of the PR template (Task ID + Jules Session).
- When `jules-watch.sh` creates an acceptance task, it should capture the branch name used by the Jules session.
- The internal task record (`git_branch` field) should be kept up-to-date by launchers / agents.

Example good commit:
```
docs: finalize branching strategy + pre-commit wiring (task 62a84821, CM-03)
```

## Pre-Commit Integration (Quality Gate on Every Commit)

See `bin/pre-commit` and `bin/install-pre-commit`.

All agent and human contributors **must** have the hook active in their working tree / worktrees.

The hook currently enforces:
- No obvious secrets in staged files
- No huge files (>500KB)
- `cargo fmt` + `cargo clippy -D warnings` on any Rust change
- `ruff` + `black --check` on any Python change

Integration points (enforced via docs + future launcher updates):
- `bin/agent-worktree` drops a note recommending hook installation.
- AGENTS.md and CONTRIBUTING.md contain the one-liner install command.
- New worktrees / fresh clones should run the installer as part of onboarding.

Future improvements tracked under follow-on CM tasks (e.g. CM-Phase2-04 area).

## Remote, Protection & CI

- Primary: `origin` = git@github.com:eveselove/AgentForge.git (public repo)
- See `.github/BRANCH_PROTECTION.md` for current recommended manual settings (require PR + status checks + up-to-date branches).
- CI (`.github/workflows/ci.yml`) runs on every PR: Rust fmt/clippy, Python ruff/black, shellcheck.
- Long-term: tighten protection + add required "agent-review" status when we have a bot/check-run bridge.

## Updating This Strategy

Branching rules changes are high-impact CM work. They must:
- Be captured as a task in the queue (with `code-mgmt` tag)
- Be developed on a short-lived `agent/cm-...` branch
- Go through PR + mandatory agent-review
- Update this file + AGENTS.md + CONTRIBUTING.md + PR template in one atomic change where possible

---

**Philosophy**: The project that creates autonomous engineering agents must itself be developed with the same discipline, traceability, and agent-native processes.

**References**:
- Task 62a84821 [CM-03]
- AGENTFORGE_CODE_MANAGEMENT_PLAN.md (Phase 2)
- AGENTS.md (Core Principles + Recommended Patterns)
- CONTRIBUTING.md
- bin/agent-worktree
- .github/PULL_REQUEST_TEMPLATE.md
- docs/REPO_STRUCTURE.md