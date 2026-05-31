# Phase 2 Task Breakdown — Maximum Parallel Agent Attack

**Goal**: Close all remaining Phase 2 items using 10-20 agents in parallel.

## Remaining Phase 2 Items (as of 2026-05-31)

1. Integrate task system with Git (mandatory task ID traceability)
2. Make `agent-review` + `implement` the default path for changes
3. Implement and enforce pre-commit / lint/format gates

Below is a fine-grained breakdown into small, parallelizable tasks suitable for many agents working at once.

### Cluster A: Task ID Traceability (Git Integration)

- A1. Create `.gitmessage` template that forces Task ID or Jules Session ID
- A2. Update `bin/pre-commit` to warn (or block) if no task ID is present in commit message
- A3. Add GitHub Action step that fails PR if title/description lacks Task or Jules ID
- A4. Update `AGENTS.md` and `CONTRIBUTING.md` with mandatory traceability rules + examples
- A5. Create a small script `bin/validate-commit-msg` that can be reused by CI and pre-commit
- A6. Audit last 30 commits on main and create a "traceability debt" report

### Cluster B: Agent Review as Default Path

- B1. Update `jules_runner.sh` to automatically suggest/create a follow-up "agent-review" task after session completion
- B2. Create `bin/request-agent-review` helper script (takes branch or PR, posts to task queue)
- B3. Add clear section in `AGENTS.md`: "After finishing work → always request agent-review before PR"
- B4. Update `grok_runner.sh` and `agent-team` launcher to remind about review step
- B5. Create lightweight "review checklist" that agents must follow before marking work ready
- B6. Add `requires_agent_review` field (or tag) to task schema and update dispatch logic

### Cluster C: Pre-commit & Quality Gates

- C1. Finalize and document `bin/pre-commit` (v2) with clear "strict" vs "advisory" modes
- C2. Make pre-commit installation automatic via `bin/setup-agent-dev`
- C3. Add shellcheck + markdown lint to the pre-commit hook
- C4. Create CI job that runs the same checks as pre-commit (fail fast)
- C5. Update `AGENTS.md` and `CONTRIBUTING.md` to state that the hook is mandatory
- C6. Add a "bypass pre-commit" policy (when and how it is allowed)

### Cross-cutting / Glue Tasks

- X1. Create "Phase 2 Agent Readiness Checklist" (one-pager or script)
- X2. Audit all current runners (`grok_runner.sh`, `jules_runner.sh`, `agent-team`) for workflow compliance
- X3. Write a short "How a new agent should work in AgentForge" guide (for future waves)
- X4. Measure current traceability rate on recent commits (as baseline)
- X5. Propose lightweight enforcement mechanisms (CI + bot comments) for the three rules above

---

**Total**: 17 small, parallel tasks.

These can be worked on by 10–15 agents simultaneously with minimal overlap.

Recommended launch pattern:
- 4–5 agents on Cluster A (traceability)
- 4–5 agents on Cluster B (agent-review default)
- 3–4 agents on Cluster C (pre-commit)
- 1–2 agents on cross-cutting items

This is the "бьем фазу 2 на всех агентов" approach.
