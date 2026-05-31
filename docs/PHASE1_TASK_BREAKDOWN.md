# Phase 1 Task Breakdown — Remote & Hosting Final Closure

**Goal**: Finish the last 10-15% of Phase 1 (remote setup, branch protection, single source of truth) with parallel agents. Most heavy lifting (repo creation, first push, basic CI, public) is already done.

**B1 (MIRROR_STRATEGY) status**: ✅ Completed (short section declared in BRANCHING_STRATEGY.md).

**Date**: 2026-06
**Owner**: Current extreme closure wave (Grok + Antigravity)

## Remaining Phase 1 Items (as of now)

1. Set up branch protection rules on GitHub (main) — manual UI + script polish (API limited on personal accounts)
2. Decide + document mirror strategy / single source of truth (GitHub is it; optional secondary mirrors later)
3. Polish any remaining remote/backup/hygiene items (SSH key docs, clone instructions, worktree + dev setup end-to-end)

---

## Cluster A: Branch Protection Enforcement (Highest Leverage)

- A1. Test and improve `bin/setup-branch-protection` (make it idempotent, better error messages, support Rulesets vs classic protection)
- A2. Update `.github/BRANCH_PROTECTION.md` with exact current GitHub UI steps (screenshots not possible, but numbered clicks + Ruleset vs Branch protection choice)
- A3. (Antigravity) Final architectural decision on "0 approvals + strong process gates" vs "1 approval minimum" for this repo (document in BRANCH_PROTECTION_A2_PROPOSAL.md or new ADR)
- A4. Apply the chosen protection via UI (or script if it succeeds) and update status in all docs + plan
- A5. Add a CI job or small script that verifies branch protection config (self-audit)

**Recommended agents**: Grok for A1,A2,A4,A5 (scripts + docs). Antigravity owns A3 (policy).

## Cluster B: Mirror / Single Source of Truth & Backup

- [x] B1. (Antigravity) Decide and document the official mirror/backup policy for AgentForge (GitHub = single source of truth; optional read-only mirrors to self-hosted Forgejo or git bundle strategy?) — **COMPLETED**: Short `MIRROR_STRATEGY` section added to `docs/BRANCHING_STRATEGY.md` v1.3 (task d68486fc / 5f018f81 / P1 B1). See also CONTRIBUTING.md. B2+ remain for optional implementation.
- B2. Create a `bin/mirror-to-secondary` (or docs recipe) for optional periodic push to a secondary location (if policy says yes)
- B3. Add "How to clone and contribute from scratch" section to CONTRIBUTING.md or a new `docs/ONBOARDING.md` (covers SSH keys, worktree setup, task queue, pre-commit)
- B4. Audit current `.git/config` and remotes in the live repo; ensure origin is correct and documented
- B5. Create a lightweight "disaster recovery" one-pager: how to restore from GitHub if local is lost (for the agent farm)

**Recommended agents**: Antigravity primary on B1 (strategic decision). Grok on B2-B5 implementation + docs.

## Cross-cutting / Glue (X)

- X1. (Antigravity) Write the "Phase 1 Closure Report" (one-pager) confirming remote is trustworthy, protection gates exist (even if manual), single source of truth declared, and all Phase 1 success criteria met.
- X2. Update central `AGENTFORGE_CODE_MANAGEMENT_PLAN.md` Phase 1 section + % to 100% once A4 + B1 done.
- X3. Ensure every remaining Phase 1 commit references a real task ID from the queue (create CM-P1-* tasks if missing).
- X4. Verify that `bin/setup-agent-dev` + `bin/agent-worktree` + pre-commit form a complete "new agent can start in <5 min" flow; add any missing one-liners.
- X5. Final hygiene: remove any lingering .bak.pure* or large untracked files from working tree that shouldn't be committed.

**Total**: 15 small, parallel tasks (many are docs + 1-2 line script changes + one manual GitHub action).

**Launch recommendation (extreme parallel)**:
- 2-3 Grok on Cluster A scripts/docs
- 1-2 Antigravity + 1 Grok on Cluster B (vision first)
- 1 Antigravity + 1-2 Grok on X (closure report + plan update)
- All agents MUST use `bin/agent-worktree create p1-xxx` before editing
- All commits: `git commit -m "chore(p1): ... (task <id>)"` or reference PHASE1_TASK_BREAKDOWN item
- After each small PR-ready change: run the `agent-review` skill

This completes the "нареж задачи на фазу 1" request and enables full team attack on the last remote items while P2/P3 are also being slammed in parallel.

**Antigravity explicit ownership table** (per user directive):
- A3, B1, X1 — primary (architectural decisions + final report)
- Advises on all others.

Once these + P2/P3 breakdowns are cleared, Phase 1/2/3 = 100%, Phase 4 dogfooding begins immediately.
