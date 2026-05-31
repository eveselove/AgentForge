# Branching Strategy (Draft)

**Status**: Proposed — needs review and finalization (see task CM-Phase2-01)

## Recommended Model: Trunk-Based + Short-Lived Agent Branches

- `main` is the single source of truth.
- All changes come in via Pull Requests.
- Agents create short-lived branches for their work.

### Branch Naming

- `agent/<short-kebab-description>` — for agent-initiated work
- `task/<task-id>` — when linked to internal task queue
- `jules/<session-id>` — when directly from a Jules session
- `human/<your-name>/<topic>` — for human-driven exploratory work

### Workflow

1. Create branch from latest `main`
2. Do the work (agent or human)
3. Open PR with proper template (link task + Jules session)
4. Get review (preferably via `agent-review` or human)
5. Merge after approvals + green CI

### Rules

- Do not push directly to `main` (enforce via protection when possible)
- Keep branches small and focused
- Rebase on latest `main` before opening PR when practical
- Delete branches after merge

### Agent-Specific Notes

- When using `agent-team` or `launch-jules-parallel`, the resulting branch should follow the naming convention above.
- Jules sessions that produce code should have their branch names recorded in the acceptance task.

---

This strategy is part of making AgentForge development itself agent-native and disciplined.
