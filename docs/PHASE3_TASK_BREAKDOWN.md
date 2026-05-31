# Phase 3 Task Breakdown — CI/CD & Quality Gates

**Goal**: Turn the basic CI we have into a production-grade, trustworthy system that supports high-velocity agent-driven development.

## Remaining Phase 3 Items (as of 2026-05-31)

1. Full Rust workspace build + test (all crates) with proper caching
2. Python health + parity harness in CI
3. Automated release binary building for `agentforge-runner`
4. Shadow / fidelity checks on PRs (future, but we can lay groundwork)

---

## Cluster A: Rust CI Hardening

- A1. Add full `cargo test --workspace` (with reasonable timeouts and parallelization)
- A2. Implement proper Rust caching (target/ + registry) that works reliably in CI
- A3. Add `cargo test --all-features` or feature matrix if relevant
- A4. Create a "Rust CI Health Dashboard" script or job that reports build/test times and flakiness
- A5. (Antigravity) Define the target CI performance and reliability standards for the Rust workspace (what "good" looks like)

**Recommended agents**: Mostly Grok for implementation. Antigravity for A5 (standards).

---

## Cluster B: Python Parity & Health in CI

- B1. Integrate the existing Python health checks into CI (so they run on every PR)
- B2. Add the learning/flywheel_parity harness as a required or optional CI job
- B3. Make parity failures block PRs (or at least post clear warnings + reports)
- B4. Create a simple "Parity Regression Report" that agents can easily consume
- B5. (Antigravity) Decide the policy: Should parity failures be hard blockers, soft warnings, or something else?

**Recommended agents**: Grok for integration work. Antigravity for policy decision (B5) and report design.

---

## Cluster C: Automated Release Binary

- C1. Create a GitHub Actions workflow that builds `agentforge-runner` release binary on tags or manual trigger
- C2. Store the binary as a release artifact (or attach to GitHub Releases)
- C3. Document the release process (how to cut a new version, what gets built, where it lives)
- C4. Add basic smoke tests for the built binary in CI
- C5. (Antigravity) Define the release process and versioning policy for the Rust binary (how often, what triggers a release, backward compatibility rules)

**Recommended agents**: Grok for the workflow and smoke tests. Antigravity for the release policy (C5).

---

## Cluster D: Shadow / Fidelity Foundations (Future)

- D1. Design what "shadow / fidelity checks on PRs" should look like at a high level for AgentForge
- D2. Identify which existing tools (parity harness, etc.) can be reused or extended for shadow runs
- D3. Create a lightweight prototype that runs a small shadow comparison on a PR (even if not enforced yet)
- D4. (Antigravity) Define the long-term vision and success criteria for shadow/fidelity checks in the CI pipeline

**Recommended agents**: Antigravity should lead D1 and D4 (this is architectural). Grok can do the prototype work (D2, D3).

---

## Cross-cutting

- X1. Standardize CI job naming and output formats so agents can reliably parse results
- X2. Create a "CI Failure Triage Guide" for agents (what to do when Rust tests / parity / etc. fail)
- X3. Add a lightweight "Security & License" scan job (even if advisory at first)
- X4. Document the full "Definition of Done" for CI (what must pass before a PR can be merged)

---

**Total**: ~17 small, parallel tasks.

**Launch recommendation (full team)**:

**Grok-heavy**:
- Most of Cluster A (Rust CI)
- Most of Cluster C (release binary implementation)
- Cross-cutting implementation tasks (X1, X2, X3)

**Antigravity-heavy (architectural / standards / vision)**:
- A5 (CI performance standards)
- B5 (Parity failure policy)
- C5 (Release process and versioning policy)
- D1 + D4 (Shadow/fidelity vision and success criteria)
- X4 (Definition of Done for CI)

**Mixed**:
- B2, B3, B4 (parity integration) — Grok implements, Antigravity reviews the design

This keeps the same aggressive parallel style as Phase 2, with Antigravity owning the high-level decisions and Grok doing the heavy implementation lifting.