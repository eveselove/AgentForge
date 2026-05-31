# AgentForge Branching Strategy

**Status**: Official  
**Version**: 1.1  
**Last updated**: 2026-05-31  
**Owner**: AgentForge Core Team (current extreme wave)

This document defines the official branching model for AgentForge. As a self-improving agentic system, our workflow is designed to maximize parallel development by both humans and autonomous agents while keeping history clean and traceable.

## Core Model: Trunk-Based Development

AgentForge follows a **Trunk-Based Development** model optimized for high agent parallelism.

- `main` is the only long-lived branch. It must always be in a deployable state.
- All changes are introduced through short-lived branches + Pull Requests.
- Direct pushes to `main` are strictly prohibited (enforced via branch protection when possible).
- We deliberately accept a higher rate of conflicts in exchange for speed and parallelism.

## Branch Naming Conventions

To keep history searchable and understandable for both humans and agents, all branches must follow these patterns:

| Prefix   | Pattern                        | When to use                                      | Example                              |
|----------|--------------------------------|--------------------------------------------------|--------------------------------------|
| `task/`  | `task/<task-short-id>`         | Work directly linked to a task in the queue      | `task/1870c84c`                      |
| `agent/` | `agent/<kebab-desc>`           | Work initiated by local agents (Grok, etc.)      | `agent/improve-jules-watcher`        |
| `jules/` | `jules/<session-id>`           | Work originating from a specific Jules session   | `jules/11158842600384206278`         |
| `human/` | `human/<name>/<topic>`         | Exploratory or coordination work by humans       | `human/eveselove/audit-ci`           |
| `feat/`  | `feat/<description>`           | Standard new feature work                        | `feat/multi-jules-support`           |
| `fix/`   | `fix/<description>`            | Bug fixes (can be combined with other prefixes)  | `fix/watcher-parsing`                |

**Strong recommendation**: Always include a Task ID or Jules Session ID when possible.

## Workflow

### 1. Starting Work
- Always branch from the latest `main`.
- Use the naming convention above.
- If the work comes from the internal task queue, the branch should reference the task ID.

### 2. During Development
- Commit frequently with clear messages that reference the originating Task ID and/or Jules Session ID.
- Follow code style (run pre-commit hook).
- For Jules work — the session usually creates the branch on GitHub automatically.

### 3. Finishing Work
- Open a Pull Request to `main`.
- **Mandatory**: Link the PR to at least one Task ID or Jules Session ID (use the PR template).
- Get review (preferably via another agent using the `agent-review` skill when possible).
- All CI checks must pass.
- Branch protection design for `main` (A2, task bc6fa462) lives in [`.github/BRANCH_PROTECTION.md`](.github/BRANCH_PROTECTION.md). The exact rules (1-review vs later evolution) are maintained there; always consult the live doc before assuming enforcement details.

### 4. After Merge
- Delete the branch immediately.
- Update the task status in the queue (if applicable).
- If it was a Jules session, the acceptance task created by `jules-watch.sh` should be completed.

## Enforcement

| Layer     | Tool / Mechanism                          | Current Status (2026-05-31)      |
|-----------|-------------------------------------------|----------------------------------|
| Local     | `bin/pre-commit` + `bin/install-pre-commit` | Available                      |
| CI        | GitHub Actions (fmt, clippy, tests, etc.) | Basic version exists, being strengthened |
| PR        | Mandatory linking + review                | PR template + CODEOWNERS exist   |
| Branch    | Protection on `main`                      | Manual setup recommended (see `.github/BRANCHING_PROTECTION.md`) |
| Process   | `jules-watch.sh` + task queue             | Running                          |

## Agent-Specific Rules

- **Worktree Isolation**: Agents **must** use `git worktree` (via `bin/agent-worktree` when available) to avoid file collisions when multiple agents run in parallel.
- **Automatic Cleanup**: Execution runners (`agent-team`, `launch-jules-parallel`, custom scripts, etc.) are responsible for cleaning up their worktrees and local branches when a task completes or fails.
- **Self-Verification**: For high-priority or complex tasks, agents should use the `--check` flag (or equivalent self-review mode) before marking the work ready for external review.

## Special Cases

### Hotfixes
Use `fix/` or `hotfix/` prefix. Still require a PR, but can be merged faster after CI + at least one quick review.

### Long-running experiments
Avoid long-lived branches. Prefer feature flags. If a long branch is unavoidable, it must be regularly rebased on `main`.

## Emergency Procedures

In case of critical failures on `main`:
- Use existing rollback scripts such as `bin/disable_pure_rust_flywheel.sh` (or equivalent) as documented in `ANTIGRAVITY_DEFAULT.md`.
- Prefer fast reverts over complex hotfixes when the fix would take more than ~15 minutes.
- All fixes should still go through a (fast) PR process when possible.
- High-priority "Fix the Build" tasks can be created in the task queue to coordinate recovery.

### High-volume Jules periods
When running large parallel waves via `launch-jules-parallel`, we expect more conflicts and messier history. This is an accepted trade-off for speed.

## Commit & PR Message Guidelines

**Mandatory linking** (enforced as much as possible):
- Every commit **must** reference a Task ID or Jules Session ID.
- Recommended formats:
  - `type(scope): description (task <short-id>)`
  - `type(scope): description (jules <session-id>)`

Good examples:
```
feat(branching): improve agent branch naming (task 6f948c10, jules/11158842600384206278)
fix(jules): reduce precondition errors on parallel launches (task bcd05a4b)
```

This makes history auditable and allows the system to automatically connect code changes to tasks and flywheel trajectories.

## Relationship to Other Documents

- `CONTRIBUTING.md` — high-level contribution rules
- `AGENTS.md` — detailed guide for agents (includes branching expectations)
- `AGENTFORGE_CODE_MANAGEMENT_PLAN.md` — tracks the overall professionalization effort

## Ownership & Evolution

This document is maintained by the team running the Code Management Professionalization effort. Any agent or human can propose improvements via PR. Major changes should first be discussed as a task in the queue.

---

**Enforcement philosophy**: We prefer tooling and process over pure documentation. As we close Phase 3, we will add more automated checks to make violating this strategy increasingly difficult.