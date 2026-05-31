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

- D1. Write exact step-by-step instructions (with screenshots placeholders) for applying the A2/A7 branch protection ruleset in GitHub UI (0 approvals + strict status checks).
- D2. Run `bin/setup-branch-protection` (or manual) and update `.github/BRANCH_PROTECTION.md` + plan with "Applied on [date]" status.
- D3. Add a small CI job or script that can later self-audit branch protection config.

**Target artifacts:** Branch protection actually active on `main`.

---

## Cluster E: Phase 4 Dogfooding Acceleration

**Owner priority:** Mixed (Grok creates, Antigravity reviews strategy)

- E1. Create 6-8 new high-quality P4 dogfood tasks from the current closure wave (examples: "Audit last 30 commits for traceability compliance", "Measure effect of new REVIEW_CHECKLIST on PR quality", "Feed closure wave trajectories into Rust flywheel").
- E2. Update `AGENTFORGE_CODE_MANAGEMENT_PLAN.md` Phase 4 section and overall status to reflect real dogfooding activity.
- E3. Ensure at least 3 commits in the next 48h reference newly created P4 tasks.

**Target artifacts:** Visible increase in P4 activity and real trajectories entering the flywheel from self-improvement work.

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