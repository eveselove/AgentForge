# AgentForge Branching Strategy

**Status**: Official (v1.0)  
**Last updated**: 2026-05-31  
**Owner**: Current extreme agent wave + human coordinator  
**Task**: CM-Phase2-01

This document defines how we manage Git branches in AgentForge — a project where the majority of coding work is done by autonomous agents (Grok, Jules, Antigravity, etc.).

## Core Principles

1. **Trunk-based development** — `main` is the only long-lived branch.
2. **High parallelism** — We deliberately optimize for many agents working simultaneously, even if it increases conflict risk.
3. **Traceability** — Every change must be clearly linked to a Task ID and/or Jules Session ID.
4. **Speed over perfect cleanliness** — We accept some messiness in exchange for agent velocity.
5. **Enforcement through tools** — We use automation (pre-commit, CI, jules-watch, Guardian-like scripts) rather than just documentation.

## Branch Model

### Only `main` is protected

- `main` — single source of truth. Always deployable.
- All other branches are short-lived.
- Direct pushes to `main` are forbidden (will be enforced via GitHub branch protection / rulesets once possible).

### Recommended Branch Naming

| Prefix       | When to use                          | Example                              | Owner     |
|--------------|--------------------------------------|--------------------------------------|-----------|
| `agent/`     | Work started by any local agent      | `agent/grok/6f948c10-branching`     | Grok      |
| `jules/`     | Work from a Jules session            | `jules/11158842600384206278`        | Jules     |
| `task/`      | Work directly tied to a task queue ID| `task/1870c84c`                      | Any       |
| `human/`     | Exploratory or complex human work    | `human/eveselove/fix-ci-flake`      | Human     |
| `feat/`      | Standard feature branches            | `feat/add-jules-multi-account`      | Any       |
| `fix/`       | Bug fixes                            | `fix/watcher-parsing`               | Any       |

**Rule**: Always include a task ID or Jules session ID when possible.

## Workflow

### 1. Starting Work
- Pull latest `main`.
- Create a short-lived branch following the naming convention.
- If the work comes from the task queue, the branch name should contain the task ID.

### 2. During Work
- Commit frequently with clear messages that reference the task/Jules session.
- Use the pre-commit hook (`bin/install-pre-commit`).
- For Jules work: the session itself usually creates the branch on GitHub.

### 3. Finishing Work
- Open a Pull Request to `main`.
- **Mandatory**: Link the PR to at least one Task ID or Jules Session ID.
- Run the new `jules-watch.sh` acceptance task (if it was a Jules session).
- Get review (preferably via another agent using `agent-review` when possible).
- Merge only after CI is green.

### 4. After Merge
- Delete the branch immediately.
- Update the task status in the queue (if applicable).
- The `jules-watch.sh` will eventually mark the Jules session as accepted.

## Handling Parallelism and Conflicts

We accept that multiple agents (especially multiple Jules sessions) will sometimes touch the same files.

Current mitigation strategies:

- **Task routing** — Try not to assign overlapping work to different agents at the same time.
- **Small PRs** — Encourage agents to keep changes focused.
- **Fast feedback** — CI + pre-commit should catch obvious problems quickly.
- **Manual intervention** — When conflicts happen, a human (or a dedicated review agent) resolves them.

Future improvements (Phase 3/4):
- Better conflict prediction before dispatching tasks.
- Semi-automatic conflict resolution agents.
- More aggressive use of feature flags instead of long branches.

## Enforcement

| Level       | Mechanism                          | Status (2026-05-31) |
|-------------|------------------------------------|---------------------|
| Local       | `bin/pre-commit` hook              | Available           |
| CI          | GitHub Actions (fmt, clippy, tests)| Basic version exists|
| PR          | Mandatory linking + review         | PR template exists  |
| Branch      | Protection on `main`               | Manual setup needed |
| Process     | `jules-watch.sh` + task queue      | Running             |

## Special Cases

### Hotfixes
Use `fix/` or `hotfix/` prefix. Can be merged faster, but still must go through a PR (no direct pushes).

### Long-running experiments
Avoid long-lived branches. Use feature flags or a separate `experiments/` namespace. Rebase frequently if you must keep a branch alive.

### Jules-heavy periods
When we run large parallel Jules waves (`launch-jules-parallel`), we expect more conflicts. This is acceptable. The priority is throughput, not zero conflicts.

## Commit Message Guidelines

Good example:
```
feat(branching): improve agent branch naming (task 6f948c10, jules/11158842600384206278)
```

Bad example:
```
update docs
```

## Ownership & Updates

This document is owned by the current wave of agents working on Code Management Professionalization.

Anyone (human or agent) may propose improvements via PR. Major changes should be discussed as a task in the queue first.

---

**Related documents**:
- `CONTRIBUTING.md`
- `AGENTS.md`
- `AGENTFORGE_CODE_MANAGEMENT_PLAN.md` (Phase 2)

**Enforcement note**: This strategy is real. We will gradually add more automated checks to make it harder to violate.