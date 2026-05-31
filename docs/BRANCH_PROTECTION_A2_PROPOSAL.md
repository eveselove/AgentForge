# Branch Protection — A2: Smallest Effective Rule Set Design (task bc6fa462)

**Task**: [CM-Phase1-A2] Design the minimal effective branch protection rule set for AgentForge (PHASE1_TASK_BREAKDOWN.md Cluster A)  
**Date**: 2026-06  
**Owner / Producer**: Grok (this session)  
**Status**: Proposal complete. Ready for review (mandatory agent-review), A3 playbook consolidation, and A4 implementation.  
**Related**: A1 research (`docs/BRANCH_PROTECTION_A1_RESEARCH.md`), A7 architectural decision (recorded in `.github/BRANCH_PROTECTION.md`).

---

## Executive Summary

The **smallest effective** set of branch protection rules for the AgentForge public repo (`main` branch) is:

- Require pull request before merging
- 0 required approving reviews at GitHub level (judgment via mandatory `agent-review` skill + process)
- Require status checks: **exactly `Rust` and `Python`** (strict)
- Require branches to be up to date (strict)
- Require conversation resolution
- Block force pushes + deletions on main
- Do not allow admins to bypass

This is delivered via **GitHub Ruleset** (preferred, Evaluate → Active) or classic protection rule.

It directly enforces the non-bypassable mechanical invariants while preserving maximum velocity for the parallel agent swarm (Grok + Jules) that is the primary development mode.

---

## Required Status Checks (Exact)

| Status Check | Source (ci.yml job) | Rationale for inclusion in *smallest* set |
|--------------|---------------------|-------------------------------------------|
| `Rust`       | `name: Rust` (runs under `rust/` workspace) | Enforces `cargo fmt -- --check`, `cargo clippy --workspace -D warnings`, `cargo check --locked`, `cargo doc`. This is the strict core gate for the Rust flywheel, agent system, and all performance-critical code. Mirrors the mandatory pre-commit v2 behavior exactly. |
| `Python`     | `name: Python`      | Enforces `ruff check .` + `black --check .`. Protects the Python task queue, agent orchestration, jules-watch, pre-commit scripts, and all glue code. |

**Explicitly excluded from required list (rationale for "smallest")**:

- `Shell & Scripts`: The shellcheck step uses `continue-on-error: true`. Policy treats shell scripts as advisory (see pre-commit v2: advisory mode). Requiring it would turn style warnings into hard merge blocks — not smallest.
- `Docs`: Pure placeholder (`echo "Docs check passed (expand later)"`). Requiring it adds zero value.

Future expansion of the required list is expected (e.g. when tests become reliable non-flaky gates, or secret-scanning/dependency-review jobs are added) but is out of scope for the *initial* smallest effective set.

---

## Full Rule Set (Ruleset form — target)

**Target**: `main` (or `~DEFAULT_BRANCH`)  
**Enforcement**: Start in **Evaluate** mode for soak, then Active.

Rules:

1. Require a pull request before merging
   - Required approving reviews: 0
   - Dismiss stale pull request approvals when new commits are pushed: true
   - Require conversation resolution before merging: true
   - Require review from Code Owners: false (notifications via CODEOWNERS are still useful; hard requirement adds friction)

2. Require status checks to pass before merging
   - Checks: `Rust`, `Python`
   - Require branches to be up to date before merging: true (strict)

3. Restrict pushes and deletions
   - Block force pushes: true
   - Block deletions: true

4. (Optional later layering) Commit message metadata rule requiring task/Jules ID pattern (for harder traceability enforcement — see Phase 2 Cluster A).

Bypass list: only the primary maintainer account (break-glass use must be logged via high-priority task + post-mortem).

---

## Rationale — Why This Is Smallest *Effective* for AgentForge

**Context (high-velocity agent-driven repo)**:
- Primary authors: autonomous agents (local Grok via `agent-team`, Jules via `launch-jules-parallel` with 2 accounts, Antigravity for architecture).
- Workflow: task queue → short-lived `agent/...` / `jules/...` / `task/...` branches → PR with task ID + agent-review handoff attached → merge.
- Existing strong layers (local first):
  - `./bin/setup-agent-dev` (mandatory in every clone/worktree) → pre-commit v2 (secrets, >512KiB, Rust fmt+clippy strict, Python black strict, traceability hint).
  - Mandatory `agent-review` skill invocation (independent Jules or peer Grok in separate context produces auditable handoff package + findings) before any agent change is eligible for merge.
  - PR template requires explicit "Agent review performed" + task/Jules linkage.
- Goal for `main`: always deployable, clean history (good for flywheel trajectories, eval, provenance), no secrets or huge blobs, full traceability.

**Why 0 GitHub approvals**:
- Requiring 1+ human (or even agent) "Approve" clicks on the PR UI would serialize the output of the parallel agent system and create review debt.
- The real, high-quality review already happens via the `agent-review` skill (separate memory, full context + diff on disk, structured issues list, recorded handoff). GitHub approval would often become rubber-stamping theater.
- A7 architectural decision explicitly chose this model for agent-native velocity. A2 design aligns with and operationalizes it.

**Why strict "up to date"**:
- Prevents subtle integration bugs from landing.
- Keeps `main` history linear and friendly to `git bisect`, flywheel training, and agent consumption of trajectories.
- Cost (occasional rebase) is accepted in the trunk-based model (see BRANCHING_STRATEGY.md) and is manageable with current PR volume and worktree tooling. If it becomes painful, we can relax or adopt merge queue (higher operational cost).

**Why only these two status checks**:
- They are the jobs whose failure actually indicates "this change would have failed the mandatory local quality gates."
- All other current jobs are either advisory or not yet meaningful.
- Matches the spirit of pre-commit v2 (strict core vs advisory).

**Why Ruleset over (or layered with) classic branch protection**:
- Evaluate mode for safe rollout (A1 research + 2026 best practice).
- Easier future evolution (add commit-message rules, path-specific rules for `.github/workflows/**`, bypass lists).
- Better visibility and audit (anyone can read active rules).

**Risks explicitly accepted**:
- Routine agent PRs may land with only the recorded `agent-review` + CI green + CODEOWNERS notification (no mandatory second human "LGTM" click). Mitigations: task tagging for complex items, human spot-checks on high-impact work, post-merge monitoring, and the fact that the owner is the only CODEOWNER.
- Slightly higher blast radius if a sophisticated bypass of the entire agent + pre-commit + CI stack occurs (very low probability given the tooling).

This set gives ~95% of the protection value of a "stricter" 1- or 2-review + all-checks config while imposing near-zero velocity tax on the agent flywheel.

---

## How This Proposal Updates Prior Art

- Supersedes the very early 1-review + "Rust (stable)" recommendation in the original short `.github/BRANCH_PROTECTION.md` and `bin/setup-branch-protection`.
- Builds directly on A1 research (full capabilities available on public Free; no Pro purchase needed).
- Is consistent with A7 "mechanical invariants + agent process" philosophy.
- Will be consolidated by A3 into the official "Branch Protection Playbook".
- A4 will apply it (UI or improved script).
- A5 will update AGENTS.md / CONTRIBUTING.md / PR template if needed (mostly already aligned).

---

## Recommended Next (for A3/A4)

1. Update `bin/setup-branch-protection` to prefer/create a Ruleset (with the exact A2 list) and support Evaluate mode.
2. Add a short "Branch Protection" section or link in `CONTRIBUTING.md` and `AGENTS.md` (A5).
3. Consider a future ruleset layer for commit message traceability enforcement (Phase 2 A2/A3).
4. After application, verify with a test PR that:
   - Direct push to main is rejected.
   - PR without green `Rust` + `Python` cannot merge.
   - PR with green checks + agent-review reference can merge (0 approval clicks needed).

---

## Traceability & References

- **This proposal fulfills A2** under internal task **bc6fa462**.
- A1 research: `docs/BRANCH_PROTECTION_A1_RESEARCH.md`
- A7 decision + current recommended config: `.github/BRANCH_PROTECTION.md`
- Branching rules: `docs/BRANCHING_STRATEGY.md` (v1.1, task 62a84821)
- Agent requirements: `AGENTS.md` (mandatory pre-commit, mandatory agent-review before merge, task/Jules IDs in every commit + PR)
- PR template: `.github/PULL_REQUEST_TEMPLATE.md` (already requires agent-review evidence)
- CI definition: `.github/workflows/ci.yml`

**Every commit and the PR implementing/landing this proposal must contain the Task ID `bc6fa462`.**

After this design work completes, the **mandatory agent-review step** (per AGENTS.md and the user request for this task) must be executed using the `agent-review` skill (e.g. `/agent-review --to-jules`) before the task is considered done or a PR is opened.

---

*Dogfooding note*: This document itself was produced by a Grok agent on a proper `agent/cm-...` branch, after running `./bin/setup-agent-dev`, with full intent to invoke independent agent-review on the resulting diff.