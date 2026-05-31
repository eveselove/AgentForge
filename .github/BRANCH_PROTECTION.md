# Branch Protection

We want to protect the `main` branch.

**See full A2 design + rationale**: `docs/BRANCH_PROTECTION_A2_PROPOSAL.md` (task bc6fa462)  
**See A7 architectural decision + target Ruleset config**: same file + the A2 section.

## Current Status (2026-06)

- `main` is **unprotected** (API 404).
- Strong local + process gates exist: mandatory `./bin/setup-agent-dev` (pre-commit v2), CI, PR template, `agent-review` skill (mandatory for agent changes per AGENTS.md).
- A2 (this task) has defined the **smallest effective** rule set. A7 chose the 0-approval Ruleset model for agent velocity. A4 will apply it.

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

See `bin/setup-branch-protection` (updated for A2) and the detailed proposal doc for exact rationale, why only two checks, and why 0 approvals.
