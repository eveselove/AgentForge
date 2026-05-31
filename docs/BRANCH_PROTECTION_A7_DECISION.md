# A7: Architectural Decision Record — Branch Protection Level for High-Velocity Agent-Driven Repo

**Task**: A7 (PHASE1_TASK_BREAKDOWN.md, Cluster A)  
**Decision Lead**: Grok (this session)  
**Traceability ID**: A7-phase1-cm (see commits + this doc)  
**Date**: 2026-06  
**Status**: Recommended — Ready for A3 (playbook consolidation) and A4 (implementation)  
**Review Status**: Independent agent-review (Jules) mandatory step to be executed after this document + related fixes; record appended to `docs/A7_BRANCH_PROTECTION_AGENT_REVIEW_HANDOFF.md`

---

## Executive Summary

**Recommended protection level for `main` in AgentForge: Level M2 ("Mechanical Invariants + Agent-Native Judgment").**

GitHub branch protection (via Ruleset preferred) shall enforce only the non-bypassable *mechanical* guarantees:

- Require a pull request before merging
- 0 required approving reviews
- Require status checks to pass: exactly `Rust` and `Python` (strict "up to date before merge")
- Require conversation resolution before merging
- Block force pushes and branch deletions
- Do not allow bypassing for administrators

**All substantive quality, design, security, and correctness judgment lives in the mandatory `agent-review` skill** (independent peer agent in a completely separate context, producing a portable auditable handoff package with findings) + the existing strong local gates (`./bin/install-pre-commit` v2, pre-commit hook), CI parity, PR template checklist, CODEOWNERS notifications, and full task/Jules ID traceability on every commit and PR.

This is the only protection level that is simultaneously safe for `main` (always-deployable, clean history friendly to flywheel/eval/bisect/provenance) *and* compatible with the project's core operating model: extreme parallel agent velocity (Grok + multiple Jules accounts + Antigravity) as the primary development force.

Traditional "1 approval" models (Level M1) impose an unacceptable velocity tax and turn the GitHub review step into rubber-stamping theater when the real review work already happens via the `agent-review` handoff process.

---

## Protection Levels Evaluated

| Level | Name                        | GitHub Approvals Req. | Required Status Checks          | Additional Rules                  | Velocity Impact on Agent Swarm                  | Primary Risk                              | Recommendation for AgentForge |
|-------|-----------------------------|-----------------------|---------------------------------|-----------------------------------|------------------------------------------------|-------------------------------------------|-------------------------------|
| M0    | Unprotected                 | 0                     | None                            | None                              | Maximum (but unsafe)                           | Direct bad pushes, lost history, secrets  | Rejected — no gate at all    |
| M1    | Traditional OSS Lite        | 1 (human or "agent")  | All CI jobs (incl. advisory)    | Linear history, often more        | High tax — serializes parallel output, review debt | Rubber-stamp approvals, human bottleneck  | Rejected — defeats agent model |
| **M2**| **Agent-Native (chosen)**   | **0**                 | **Rust + Python only (strict)** | Up-to-date, conv. resolution, force/delete blocks, no-bypass | Low tax — parallel friendly, agents move at full speed | Medium (accepted): relies on process + spot checks for high-impact items | **Strongly Recommended** |
| M3    | Paranoid / Heavy            | 1–2 + owner           | All + future test gates + more  | Signed commits, merge queue, path rules | Very high tax — artificial serialization       | Lowest (but velocity destroyed)           | Rejected — overkill for this repo |

**Decision**: Level M2. It directly operationalizes the philosophy in [AGENTS.md](/home/agx/agentforge/AGENTS.md): dogfooding, task-driven work, mandatory agent-review before merge, traceability, and maximum safe parallelism via worktrees + short agent branches.

---

## Why M2 Is the Right Level (Detailed Rationale)

1. **The development model is agent-primary, not human-primary**.
   - Dozens of short-lived `agent/...`, `jules/...`, `task/...` branches are created daily by `agent-team`, `launch-jules-parallel` (2 Jules accounts), etc.
   - Requiring even 1 GitHub approval on every PR would create a permanent review queue and force humans (or simulated agent "approvers") into the critical path. This directly contradicts the goal of a self-improving agent-native flywheel.

2. **The real review already happens at higher fidelity via `agent-review`**.
   - The skill produces a full diff + context handoff package on disk, launches an independent Jules (or named peer Grok) in a *separate memory/context window*, and records structured findings (bugs / suggestions / nits with file:line).
   - This is strictly stronger than a GitHub "LGTM" click, which has no persistent artifact, no separate reasoning, and is often performed by the same cognitive context that wrote the code.
   - AGENTS.md explicitly makes this step mandatory before any agent change is eligible for merge.

3. **Mechanical invariants are still non-negotiable and fully enforceable on Free public repos**.
   - A1 research confirmed that PR requirement, status checks (strict), conversation resolution, force/delete blocks, and "do not allow bypass" are all available without GitHub Pro.
   - These prevent the classes of accidents that would actually damage `main` (unreviewed direct pushes, force-rewriting history needed for training data, landing code that failed the mandatory pre-commit/CI gates).
   - See [docs/A1_BRANCH_PROTECTION_RESEARCH_REPORT.md](A1_BRANCH_PROTECTION_RESEARCH_REPORT.md) and [docs/BRANCH_PROTECTION_A2_PROPOSAL.md](BRANCH_PROTECTION_A2_PROPOSAL.md) (the concrete minimal rule *set* that realizes M2).

4. **0 approvals is not "no review" — it is "review where it actually adds value"**.
   - GitHub approvals would frequently become performative once the agent-review handoff + CI green + traceability are present.
   - CODEOWNERS still provides notification to the maintainer for awareness/spot-checking without blocking.

5. **Risk acceptance is explicit and bounded**.
   - Accepted: slightly higher chance that a sophisticated change slips through with only the recorded agent-review (no second human eye).
   - Mitigations: task tagging for high-impact items, human spot-audits, post-merge monitoring via flywheel/eval, owner as sole CODEOWNER, and the fact that the pre-commit + CI layers are already strong and non-bypassable locally/CI.
   - The blast radius of a bad merge is limited because `main` is trunk-based with frequent small PRs and excellent rollback tooling.

---

## Explicitly Rejected Alternatives

- **"Just use 1 approval like a normal repo" (M1)**: Ignores the actual workload (agent-generated PR volume) and the existence of a superior separate-context review mechanism. Would slow the entire system for theater.
- **"Add linear history requirement now"**: Desirable for git bisect / flywheel cleanliness, but adds rebase pressure during high-parallel Jules waves. Deliberately deferred (see A2). Can be added later as a Ruleset evolution once velocity impact is measured.
- **Relying only on local pre-commit without GitHub enforcement**: Violates the "non-bypassable for admins" and "protect main even from the owner on a bad day" requirement.

---

## Relationship to Other Phase 1 Artifacts

- **A1**: Research foundation — all needed controls exist on public Free repos.
- **A2**: The *minimal effective concrete rule set* (exactly the checks and rules that implement Level M2). This A7 decision provides the "why 0 approvals and agent judgment" layer on top of A2's design.
- **A3**: Will consolidate this decision + the A2 set into the official "Branch Protection Playbook" (one source of truth).
- **A4**: Apply via GitHub Ruleset (start in Evaluate mode for soak, then Active). Prefer UI + capture the resulting JSON for reproducibility in `bin/setup-branch-protection`.
- **A5**: Update AGENTS.md / CONTRIBUTING.md / PR template (already largely aligned; add explicit pointer to this decision and the playbook).
- **BRANCHING_STRATEGY.md**: Trunk-based model is a prerequisite for M2 to make sense (short-lived branches + frequent clean merges).

---

## Risks, Blind Spots & Mitigations (Incorporating Prior Review Findings)

- **Jules / agent authorship identity**: `launch-jules-parallel` and Jules sessions create PRs under specific GitHub identities (PAT or app). These identities must never be granted admin or ruleset-bypass rights. Documented observation + restriction is required in the A3 playbook. (Addresses prior review Issue 6.)
- **Personal account admin power**: On a Free personal account the repo owner retains the ability to edit rulesets directly in the UI/API. Any such edit outside the documented emergency process must trigger a high-priority post-mortem task. (Addresses prior review Issue 7.)
- **Future evolution**: A commit-message metadata Ruleset rule (requiring task/Jules ID) is noted as a Phase 2/3 possibility once the basic M2 model is stable.
- **Verification after A4**: Must include explicit checks that (a) direct push is rejected, (b) PR missing Rust+Python cannot merge, (c) PR with green checks + agent-review reference *can* merge with 0 approval clicks.

---

## Rollout Guidance (for A4 / A3)

1. Create the Ruleset targeting `main` (or `~DEFAULT_BRANCH`) in **Evaluate** mode first.
2. Use exactly the rules from the A2 proposal (0 approvals, only Rust+Python strict, up-to-date, conversation resolution, force/delete blocks, no-bypass).
3. After soak period with no unexpected blocks, promote to Active.
4. Update `bin/setup-branch-protection` to prefer the Ruleset path (or at minimum stop claiming it sets 1 approval).
5. Store the authoritative Ruleset JSON under `.github/rulesets/` for reproducibility.
6. Update this document's "Current Status" section and the short `.github/BRANCH_PROTECTION.md` pointer.

---

## Current Status (as of this decision)

- `main` has **no** branch protection (API 404).
- Strong process + local + CI + agent-review layers already exist and are actively used.
- This A7 decision + the A2 minimal set together define the target for A4.
- Prior partial implementation attempt (handoff 7c763a72) produced the philosophical core but contained internal contradictions (status check lists, script values, stale cross-refs). This document + the accompanying fixes resolve them.

---

## Traceability & References

- Fulfills A7 from [PHASE1_TASK_BREAKDOWN.md](PHASE1_TASK_BREAKDOWN.md) (original Cluster A item assigned to architectural ownership).
- Complements [docs/BRANCH_PROTECTION_A2_PROPOSAL.md](BRANCH_PROTECTION_A2_PROPOSAL.md) (bc6fa462) — the "what" to this document's "why this level".
- A1 research: [docs/A1_BRANCH_PROTECTION_RESEARCH_REPORT.md](A1_BRANCH_PROTECTION_RESEARCH_REPORT.md) (bc931676).
- Process requirements: [AGENTS.md](/home/agx/agentforge/AGENTS.md) (mandatory agent-review, pre-commit, traceability).
- Branching model: [docs/BRANCHING_STRATEGY.md](BRANCHING_STRATEGY.md).
- Implementation target: `.github/BRANCH_PROTECTION.md` (short pointer) and the future A3 playbook.
- CI definition: `.github/workflows/ci.yml` (job names `Rust`, `Python` are the only strict gates).

**Every commit landing changes related to this decision must reference "A7 (PHASE1_TASK_BREAKDOWN.md)" or the internal task ID used in the queue.**

**Mandatory agent-review step**: This document (and any supporting doc/script fixes) was produced under the rules in AGENTS.md. After the changes, the `agent-review` skill **must** be invoked (e.g. `/agent-review --to-jules`), an independent review obtained and recorded in the handoff directory, and findings addressed before this work is considered complete or a PR is opened to `main`.

---

*Dogfooding note*: This document was authored following the full agent workflow (pre-commit active, proper traceability, short-lived branch, intent to perform the mandatory cross-agent review step before any merge). It replaces earlier ad-hoc descriptions of the A7 decision with a single clear, self-contained recommendation.