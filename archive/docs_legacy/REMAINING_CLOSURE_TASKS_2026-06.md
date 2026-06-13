# Remaining Closure Tasks — Final Push to 100% (Wave 2)

**Date:** 2026-06
**Goal:** Close the last 25-30% of the Code Management Plan after the first aggressive wave.
**Current Status:** P0 100%, P1 91%, P2 84%, P3 58%, P4 23%

This document contains the highest-leverage remaining work, broken into small parallel tasks for maximum agent parallelism.

---

## Cluster A: Agent-Review as Default Path (P2 — Highest Process Impact)

**Owner priority:** Grok (implementation) + Antigravity (policy confirmation)

- A1. Update `grok_runner.sh`, `agent-team`, and `jules_runner.sh` to automatically remind / create follow-up "agent-review" tasks after work completion.
- A2. Modify `create_tasks.py` / task queue logic to support `requires_agent_review: true` tag and auto-create review tasks.
- A3. Update `AGENTS.md` and `CONTRIBUTING.md` with explicit "agent-review is now the mandatory default path" section + examples.
- A4. Add a lightweight enforcement hook (pre-commit or CI comment) that warns if a PR from an agent branch has no linked agent-review.

**Target artifacts:** Updated runners, task schema change, clear documentation.

---

## Cluster B: Rust CI Hardening (P3)

**Owner priority:** Grok (heavy lifting)

- B1. Make `cargo test --workspace` a required (non-continue-on-error) job in `.github/workflows/ci.yml` with reasonable timeouts.
- B2. Improve Swatinem/rust-cache configuration for the `rust/` workspace (fix any remaining issues from task 90fcbf89).
- B3. Add a simple "Rust CI Health" report step (build time, test count, flakiness notes) that runs on main.

**Target artifacts:** Stronger CI that actually runs full tests reliably.

---

## Cluster C: Antigravity Policy & Vision (P3 — High Value)

**Owner priority:** Antigravity (primary)

- C1. Define and document the release versioning policy for `agentforge-runner` (when to cut releases, semver vs calendar, backward compat rules).
- C2. Write the long-term vision and success criteria for shadow/fidelity checks inside AgentForge's own CI (what to measure, when to block, reuse of existing parity harness).
- C3. Create `docs/CI_POLICY.md` (or section in existing docs) containing the above two policies + CI performance standards (A5 from PHASE3).

**Target artifacts:** Clear, actionable policy documents that Grok agents can implement against.

---

## Cluster D: Branch Protection Application (P1 — Final Manual Step)

**Owner priority:** Grok (execution)

- D1. ~~Write exact step-by-step instructions (with screenshots placeholders) for applying the A2/A7 branch protection ruleset in GitHub UI (0 approvals + strict status checks).~~ ✅ Done 2026-05-31 (task 3cdd6813) — see `.github/BRANCH_PROTECTION.md` "D1: Exact Step-by-Step..."
- D2. ~~Run `bin/setup-branch-protection` (or manual) and update `.github/BRANCH_PROTECTION.md` + plan with "Applied on [date]" status.~~ ✅ Done 2026-05-31 (task 3cdd6813) — Ruleset 17085567 created active via script+API; `.github/BRANCH_PROTECTION.md` + `.github/rulesets/main-protection.json` updated.
- D3. Add a small CI job or script that can later self-audit branch protection config.

**Target artifacts:** Branch protection actually active on `main`. ✅ Achieved (Ruleset active, verified via API).

---


## Cross-cutting

- X1. Sync the top sections of `AGENTFORGE_CODE_MANAGEMENT_PLAN.md` (current status box, immediate next actions, success criteria) with the actual delivered state and new %.
- X2. Add a one-page "Wave 2 Closure Report" (short) after this wave lands.

---

**Total:** 15 small, high-leverage tasks.

**Recommended launch pattern for this wave:**
- 4-5 Grok agents on A + B + D + E
- 2-3 Antigravity agents on C (policy) + E
- All agents must use `bin/agent-worktree` + full process (traceability, pre-commit, REVIEW_CHECKLIST, agent-review before PR)

**Success condition for this wave:**
P1 → 95%+, P2 → 95%+, P3 → 80%+, P4 → 40%+ with clear dogfooding evidence.

This is the final targeted push. After this, the plan should be effectively closed.

---

## Pure Rust Flywheel Soak Prep (task-5af0e350, 2026-06-13)
**Status: SOAK READY** — 14-day mandatory soak clock can/should start immediately.
- .pure_rust_flywheel marker created/touched in worktree (/tmp/agentforge-work/pure-soak-prep-5af0e350) + main (note: sync on merge).
- Updated: all agentforge-*.service, systemd/*.service, services/*.service, install_services.sh, bin/{enable,disable,make}*_flywheel*.sh , bin/rust_flywheel.env , grok_worker.sh , agents/grok_runner.sh , rust_flywheel_after_task.sh , scripts/ etc. to export AGENTFORGE_PURE_RUST_FLYWHEEL=1 , AGENTFORGE_RUST_RUNNER=.../release/agentforge-runner , FLYWHEEL_PROVENANCE=rust-agentforge-runner .
- Stubbed py flywheel entrypoints (rust_flywheel_step.py, run_continuous_flywheel.py, learning/{skill_improver,pending_candidates,evaluator}.py) to direct to runner when invoked as main.
- learning/utils.py guards made worktree-aware via _get_agentforge_root() + marker honored.
- bin/phase4_pre_removal_audit.sh : dynamic root (supports worktree), fixed manifest bash err, jules legacy checks, updated dupe filter.
- Also updated docs (PHASE4_*, REMAINING_*) with soak-ready status + traceability.
- Pre-commit installed per setup. All changes include "task-5af0e350".
- Verification: test_pure script, audit re-runs (pre-binary/health expected fails ok until farm).
- This unblocks Tier3/4 deletions post-14d green soak + clean audit + 100% provenance.
- Next: run on farm, monitor logs/manifests/health for "rust-agentforge-runner", start 14d timer, handoff for review.
Traceability enforced (AGENTS.md).