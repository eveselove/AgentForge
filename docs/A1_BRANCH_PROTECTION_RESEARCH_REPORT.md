# A1 Research Report: GitHub Branch Protection Capabilities for Public Repos (Free Tier)

**Task**: A1 from [docs/PHASE1_TASK_BREAKDOWN.md](PHASE1_TASK_BREAKDOWN.md)  
**Task ID (traceability)**: bc931676  
**Date**: 2026-06-01  
**Context**: eveselove/AgentForge (public personal account on GitHub Free)  
**Research method**: Official GitHub Docs (current as of 2026) + GitHub API verification on this repo + web_search confirmation

**Agent-review**: Mandatory independent review performed via agent-review skill (handoff 1f3ceb91, Jules reviewer). Review recorded at `~/.grok/handoffs/1f3ceb91/jules-review-1f3ceb91.md` (0 bugs, 3 suggestions, 4 nits — all non-blocking; primary notes were on artifact duplication in parallel work and tighter A2 alignment). Suggestions addressed in spirit by making this the canonical short report.

## Executive Summary

**Core branch protection features required for AgentForge are fully available on public repositories under the GitHub Free plan.** No GitHub Pro (or higher) is needed.

The previous assumption in plans ("blocked on GitHub Pro for private repo") no longer applies — the repository is now public.

All controls needed for the project's model (PR before merge, status checks with strict mode, linear history option, signed commits, conversation resolution, block force/deletes, "do not allow bypass for admins", code owners) are present via classic branch protection rules and/or repository rulesets.

## What Is Available on GitHub Free — Public Repositories

### Classic Branch Protection Rules (Settings → Branches)
Fully supported for public repos on Free (personal accounts and orgs):

- Require a pull request before merging
  - Required approving reviews count (1, 2, ...)
  - Dismiss stale pull request approvals when new commits pushed
  - Require review from Code Owners (limited on personal accounts; full teams support in orgs)
  - Require approval of the most recent push
- Require status checks to pass before merging (strict "up to date before merge" supported)
- Require conversation resolution before merging
- Require signed commits
- Require linear commit history
- Require deployments to succeed before merging
- Lock branch (read-only)
- Block force pushes (default: blocked)
- Block branch deletions (default: blocked)
- "Do not allow bypassing the above settings" (enforce_admins / include administrators)
- Restrict who can push / create matching branches — **limited on personal accounts** (stronger in Free org-owned public repos; see "Free organization vs personal" distinction in docs)

One rule per branch pattern (fnmatch supported). Only the highest-priority matching rule applies.

### Repository Rulesets (modern, recommended complement)
Also fully available on GitHub Free for public repos (branch + tag rulesets):

- Multiple overlapping rulesets can target the same branch (they layer; most restrictive wins).
- Same core rules as above + extras:
  - File path / extension / size / length restrictions (on updates)
  - Commit message pattern / author/committer metadata rules (availability varies)
  - Require code scanning results (GitHub Advanced Security / code scanning merge protection is free on public repos)
- Better visibility: any read user can inspect active rulesets.
- Up to 75 rulesets per repository.
- Easy enable/disable without deletion. "Evaluate" (dry-run) mode is excellent for safe rollout.

**Push rulesets** (repo-wide/fork-network restrictions on paths, sizes, etc.) are **NOT available** on Free — require GitHub Team or higher.

Organization-level rulesets (across many repos) require Enterprise (Team for some org features since 2025).

## Key Limitations on Free Public (Personal Account)

| Limitation                              | Impact for AgentForge                          | Workaround                                      |
|-----------------------------------------|------------------------------------------------|-------------------------------------------------|
| Push rulesets unavailable               | Cannot easily block specific file patterns on every push | Rely on pre-commit v2 + CI + PR review + agent-review |
| Granular "restrict who can push" + bypass actor lists | Limited (personal accounts lack teams/roles) | Use "enforce admins" + process/docs + CODEOWNERS |
| No native teams                         | Code Owner reviews and team-required-reviewers weaker | Manual review process + mandatory agent-review skill |
| Only one classic BP rule per branch     | Minor                                          | Use rulesets for complex / layered needs        |
| Merge queue, some advanced Enterprise rules | Not critical for our trunk-based model      | Not needed for current velocity                 |

Private repos on Free have almost none of these features (require Pro+). Our public status unlocks everything we need for a professional agent-driven repo.

## Current State of This Repository (verified 2026-06)

- No branch protection rule on `main` (API 404 "Branch not protected").
- No repository rulesets configured.
- `bin/setup-branch-protection` exists (uses classic API; falls back gracefully).
- `docs/BRANCH_PROTECTION_A7_DECISION.md` (A7 architectural level decision: Level M2 for high-velocity agent-driven repo) + `docs/BRANCH_PROTECTION_A2_PROPOSAL.md` (concrete minimal set) + `.github/BRANCH_PROTECTION.md` (current status + pointer) document the full recommended path.

## Recommendations (for A2/A3/A4)

1. **For A4 implementation**: Follow the exact configuration in `.github/BRANCH_PROTECTION.md` (A7 + A2 sections). It maps directly to available Free public features and incorporates the velocity-first philosophy for agent swarms.
2. Rulesets are a safe future layer (they coexist with classic rules) but the minimal effective set deliberately keeps the bar low on GitHub approvals (0) in favor of `agent-review` + CI + pre-commit as the judgment layer.
3. Update `bin/setup-branch-protection` (or add ruleset variant) as part of A4.
4. A5 doc updates (AGENTS.md, CONTRIBUTING.md, BRANCHING_STRATEGY.md) must reference the active protection + the mandatory agent-review gate.

## Sources (Authoritative, accessed 2026-06-01)

- https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches
- https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/managing-a-branch-protection-rule
- https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets
- https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets
- GitHub Plans: https://docs.github.com/en/get-started/learning-about-github/githubs-products

**Conclusion**: A1 complete. All meaningful protections for a high-velocity public agent repo are available today without any paid plan. Canonical research artifact: this file (bc931676). Independent Jules review (handoff 1f3ceb91) obtained and recorded per AGENTS.md — 0 blocking issues.

---
*Traceability: This report fulfills A1 (PHASE1_TASK_BREAKDOWN.md, task bc931676). All follow-up work (A2–A7, A5 updates, implementation) must link commits/PRs to task IDs or Jules sessions per AGENTS.md and docs/BRANCHING_STRATEGY.md.*
