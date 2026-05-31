# PHASE1 B4 / CM-Phase1-09: Mirror / Single Source of Truth Decision

**Task**: B4 (PHASE1_TASK_BREAKDOWN.md) / CM-Phase1-09 — Official recommendation on mirror/single source of truth strategy  
**Task ID (traceability)**: 5f018f81 (related research: a0ee8f20; prior attempt: d68486fc)  
**Date**: 2026-06  
**Context**: eveselove/AgentForge (public GitHub, Jules + local Grok/Jules agent swarm, trunk-based workflow)  
**Status**: Official decision — closes the pending item in AGENTFORGE_CODE_MANAGEMENT_PLAN.md

**Agent-review**: Mandatory independent review via agent-review skill performed after completion (handoff recorded under ~/.grok/handoffs/). See handoff artifacts and AGENTS.md.

## Decision (Official Recommendation)

**GitHub (https://github.com/eveselove/AgentForge) is the Single Source of Truth (SoT).**

All local filesystem copies — including the canonical development machine at `/home/agx/agentforge`, any secondary laptops, CI runners, or temporary worktrees — are **working clones / mirrors**. They are never treated as authoritative.

- `main` and all long-term history live only on GitHub.
- Jules sessions, `jules remote` commands, PRs, CI (GitHub Actions), releases, and external visibility are the primary consumers; they all treat the GitHub remote as canonical.
- Local development always starts from `git clone` (or `git fetch origin && git checkout -B ...` from up-to-date state) + `bin/agent-worktree`.
- Optional cold backups (e.g. periodic `git bundle create` or `gh repo clone --mirror` to an air-gapped disk) are **pure backups**, never a second source of truth or sync target.

## Rationale

1. **Jules and agent ecosystem alignment** — Jules (multi-account parallel launches via `launch-jules-parallel`, `jules-watch.sh`, session pull/push/accept flows) is GitHub-native. Any "local-first" or dual-SoT model would require fragile sync daemons that directly contradict the high-velocity parallel agent model we dogfood.

2. **Standard git collaboration model** — Single authoritative remote eliminates the classic "two masters" divergence problem (force-push races, different protected-branch configs, "which reflog wins?"). This is especially critical under extreme parallelism (dozens of agent/ and jules/ branches).

3. **Durability and visibility are already solved** — Public GitHub provides geo-replicated, audited history + Issues + Actions. Adding a second "mirror" as SoT adds operational cost with zero meaningful availability gain for this workload.

4. **Process already enforces safety** — Mandatory PRs (never direct push to main), pre-commit (bin/pre-commit), CI gates, and **mandatory agent-review skill before merge** (AGENTS.md) provide the real integrity layer. The remote being SoT is the simplest consistent model with that process.

5. **Velocity and onboarding** — New agents/humans run `./bin/setup-agent-dev` or `git clone`, immediately have a correct view. No "am I on the local mirror or the real one?" questions.

6. **Future evolution** — If a self-hosted forge is introduced later, it will be configured as a **read-only mirror** (or secondary Actions runner source). GitHub remains the canonical SoT for the public agent-forge ecosystem. Any cutover would be a deliberate one-time migration, not ongoing mirroring.

## Risks & Mitigations

| Risk                        | Likelihood | Mitigation |
|-----------------------------|------------|----------|
| GitHub outage (writes)      | Low        | Pause agent launches; local clones remain readable for analysis. Recovery = `git fetch` after outage. |
| Local disk failure          | Medium     | Re-clone (minutes). Uncommitted/unpushed work is already minimized by short-lived branches + frequent commits required by process. |
| Accidental local drift      | Low        | AGENTS.md + BRANCHING_STRATEGY.md mandate `git fetch origin` before branching; agent-worktree + pre-commit; PR template requires traceability. |
| Desire for "offline-first"  | Very Low   | Not a goal. The flywheel, task queue, and Jules all require network. |

## Implementation / Follow-up Notes

- This decision closes the checkbox in AGENTFORGE_CODE_MANAGEMENT_PLAN.md (Phase 1).
- CM-Phase1-10 (implementation of chosen mirror/backup solution) should now produce only **backup** tooling (e.g. optional `bin/backup-repo.sh` + timer), explicitly documented as non-authoritative.
- Minor doc touches (AGENTS.md, REPO_STRUCTURE.md, BRANCHING_STRATEGY.md) may reference "GitHub = SoT, locals = clones" for clarity in future updates (A5-style).
- No changes to branch protection, CI, or current remotes required — this is a policy/mental-model decision.

**Conclusion**: The simplest, most agent-aligned, lowest-risk model is the industry-standard one: GitHub is the single source of truth. Everything else is a clone or a backup.

---

*Traceability: Fulfills B4 (PHASE1_TASK_BREAKDOWN.md) and CM-Phase1-09 (task 5f018f81). All related commits, the PR, and any follow-up (CM-Phase1-10) must link to this task ID per AGENTS.md and docs/BRANCHING_STRATEGY.md. Independent agent-review handoff obtained and recorded before PR/merge.*
