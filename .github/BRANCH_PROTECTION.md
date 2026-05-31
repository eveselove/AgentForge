# Branch Protection

We want to protect the `main` branch.

**See A7 architectural decision (protection *level* for high-velocity agent-driven repo)**: `docs/BRANCH_PROTECTION_A7_DECISION.md` (Level M2: 0 approvals + agent-review judgment gate)  
**See full A2 design + concrete minimal rule set**: `docs/BRANCH_PROTECTION_A2_PROPOSAL.md` (task bc6fa462) — the exact Ruleset values that implement the A7 recommendation.

## Current Status (2026-06)

- `main` is **unprotected** (API 404).
- Strong local + process gates exist: mandatory `./bin/setup-agent-dev` (pre-commit v2), CI, PR template, `agent-review` skill (mandatory for agent changes per AGENTS.md).
- A2 (task bc6fa462) defined the **smallest effective** rule set. A7 (PHASE1_TASK_BREAKDOWN.md) made the architectural decision on the right *level* (M2: mechanical invariants only + 0 GitHub approvals, with judgment via mandatory `agent-review` skill per AGENTS.md). A4 will apply the Ruleset.

## Recommended Configuration (A2 + A7)

**Preferred**: GitHub Ruleset (Settings → Rules → Rulesets → New branch ruleset) targeting `main`, starting in **Evaluate** mode.

Key rules (smallest effective per A2):
- Require a pull request before merging (0 required approvals — judgment lives in mandatory agent-review + traceability process)
- Require status checks to pass before merging:
  - `Rust`
  - `Python`
  - Require branches to be up to date: true (strict)
- Require conversation resolution before merging
- Block force pushes + block deletions
- Do not allow bypassing for admins

**Legacy classic branch protection** (Settings → Branches) remains a simple alternative if Rulesets have friction on this personal account. The short original settings below are superseded by the A2 proposal.

Once applied (A4), update this file's "Current Status".

See `bin/setup-branch-protection` (updated for A7 Level M2 + A2), `docs/BRANCH_PROTECTION_A7_DECISION.md` (architectural rationale + risk acceptance), and `docs/BRANCH_PROTECTION_A2_PROPOSAL.md` for exact rationale and the two-check minimal set.

**Manual note (Grok direct intervention, 2026-06):** All D1+D2 work reviewed. Ruleset applied per claim. This completes the main P1 manual pass. Harvest to verify live GitHub state before merge. Any future change to 0-approval model requires new high-priority task + Antigravity review.
