# AgentForge — Code Management & Repository Professionalization Plan

**Date:** 2026-05-31  
**Goal:** Bring the entire AgentForge codebase under proper, professional source control and project management, using AgentForge itself (dogfooding) in turbo mode with Jules + local agents.

> **Current Status (updated live):**  
> **Phase 0 — Immediate Stabilization: ✅ COMPLETED**  
> Standalone GitHub repo: https://github.com/eveselove/AgentForge (public)  
> `main` branch initialized and pushed.  
> CONTRIBUTING.md + AGENTS.md + CODEOWNERS + PR template + REPO_STRUCTURE.md + BRANCHING_STRATEGY.md added.  
> Basic CI workflow in place.  
> Branch protection: Manual setup recommended.  
> Extreme parallel agent execution active (Jules currently paused).

**Current Reality (as of this plan):**
- Code lives only at `/home/agx/agentforge/`
- Local Git repository on `master` with **zero remotes**
- ~600+ uncommitted changes (very dirty tree)
- 8 Rust crates in a workspace + large Python + shell + systemd surface
- Heavy use of `.bak.pure*` files from recent cutover
- No CI, no remote backup, no clean branching strategy, no contribution process
- The project that builds autonomous agents does not yet properly manage its own code

---

## Vision (Target State)

AgentForge should be developed like a frontier agentic system:
- Clean, versioned Git repository (GitHub or self-hosted)
- Trunk-based or well-defined branching with mandatory agent review
- Strong .gitignore + pre-commit hygiene
- Automated CI (Rust + Python + integration)
- All major work goes through the internal task system + Jules / Grok agents
- Self-improving: the system uses its own flywheel to improve its own development process
- Reproducible builds and easy onboarding

---

## Phased Plan (Turbo Execution)

### Phase 0 — Immediate Stabilization (Today)

- [x] Create this plan document + break into trackable tasks in the internal task system
- [x] Create a clean backup branch of current dirty state (`backup/pre-management-2026-05-31`)
- [x] Aggressive .gitignore improvements (pycache, logs, target/, *.bak.*, .pure* markers that shouldn't be committed, etc.)
- [x] Commit a "pre-management baseline" so we have a clean starting point
- [x] Document current repo structure (Rust workspace layout, Python package, services) — `REPO_STRUCTURE.md` (v1.0) created and significantly improved

### Phase 1 — Remote & Hosting (Critical)

- [x] Decide on hosting location (GitHub personal/org, self-hosted Gitea/Forgejo, or internal) → **GitHub (eveselove/AgentForge)**
- [x] Initialize remote + first push (`main` branch pushed to https://github.com/eveselove/AgentForge)
- [ ] Set up branch protection rules (require agent review for merges where possible) — **blocked on GitHub Pro for private repo**
- [x] Mirror strategy or single source of truth decision → **GitHub is the Single Source of Truth** (see `docs/PHASE1_B4_MIRROR_SOT_DECISION.md`, task 5f018f81 / B4)
- [x] Created basic CI workflow (`.github/workflows/ci.yml`)

### Phase 2 — Development Workflow (Turbo with Agents)

- [x] Define branching strategy (recommend: trunk-based with short-lived agent branches) → `docs/BRANCHING_STRATEGY.md` (v1.1) — reviewed and integrated best parts from Jules sessions 11158842600384206278 + 5861866188344060320
- [ ] Integrate task system with Git (every significant change linked to task ID)
- [ ] Make `jules_runner` and local `implement` + `agent-review` the default path for changes
- [x] Create `CONTRIBUTING.md` and `AGENTS.md` that describe "how we develop AgentForge using AgentForge"
- [ ] Pre-commit hooks or simple lint/format gates
- [x] Repository made public on GitHub (unlocks more features)

### Phase 3 — CI/CD & Quality Gates

- [x] GitHub Actions (or equivalent) for:
  - Rust workspace check + clippy + fmt (`.github/workflows/ci.yml`)
  - Python linting (ruff + black)
  - Shellcheck on bin/
- [ ] Full Rust workspace build + test (all crates) with caching
- [ ] Python health + parity harness in CI
- [ ] Automated release binary building for `agentforge-runner`
- [ ] Shadow / fidelity checks on PRs (future)
- [x] PULL_REQUEST_TEMPLATE.md created with task/Jules linking requirements

### Phase 4 — Self-Management (Dogfooding)

- [ ] All future development of AgentForge itself goes through the internal task queue with `preferred_agent` routing
- [ ] Use the Rust flywheel on trajectories produced while developing AgentForge
- [ ] Close the loop: improving the code management system itself feeds the flywheel

---

## Immediate Next Actions (Start in This Session) — Updated 2026-05-31 (Aggressive Phase 2 Closure Mode)

1. ✅ Backup branch + aggressive .gitignore + baseline commit done
2. ✅ Standalone GitHub repo created (public): https://github.com/eveselove/AgentForge
3. ✅ CONTRIBUTING.md + AGENTS.md + CODEOWNERS + PR template + REPO_STRUCTURE.md created
4. ✅ Basic CI workflow added and improved
5. ✅ `docs/BRANCHING_STRATEGY.md` (v1.1) created and pushed — Phase 2 item closed
6. ✅ Created high-priority tasks for remaining Phase 2 items:
   - [CM-Phase2-05] Integrate task system with Git (traceability) → task 3be670e1
   - [CM-Phase2-06] Make agent-review + implement the default path → task 285c1c6d
   - [CM-Phase2-07] Pre-commit / lint gates (work started with bin/pre-commit + install-pre-commit)
7. **Now in full aggressive Phase 2 closure mode**: Multiple Grok agents launched on remaining items (pre-commit enforcement + task ID traceability + agent-review as default).
8. Additional tooling created: bin/setup-agent-dev for fast onboarding.
9. Goal: Close all remaining Phase 2 items within the current wave.

---

## Success Criteria

- AgentForge has a real remote Git repository with history
- Working tree can be made clean on demand
- New changes are made through the agent system (not ad-hoc local edits)
- Anyone (or another agent) can clone and get a working development environment
- The project that powers autonomous engineering is itself a model of disciplined agent-driven development

---

**Owner:** This session (Grok + all available agents)  
**Mode:** Turbo + full dogfooding of AgentForge

Let's execute.

---

## Reviews Closed (2026-05-31)

**Two hanging Jules reviews closed by Grok:**

1. **[Rust-Flywheel-100] Review and update all JULES_*.md docs for current Rust migration state** (#57bdc864)
   - Status: ✅ Approved
   - Action: Added clear "Rust Migration Status" headers to the 5 most important JULES documentation files.
   - Commit: `c3987e6`
   - See: `docs/REVIEWS_CLOSED_2026-05-31.md`

2. **[Code Mgmt] Document AgentForge repository structure and development workflow**
   - Status: ✅ Approved
   - Action: Confirmed full coverage via existing docs (REPO_STRUCTURE.md, AGENTS.md, CONTRIBUTING.md, BRANCHING_STRATEGY.md v1.1) + formal closure note.
   - Commit: `ef2e522`
   - See: `docs/CODE_MGMT_DOCUMENTATION_STATUS.md` and `docs/REVIEWS_CLOSED_2026-05-31.md`

Both reviews are now formally closed in the repository history.

---

## Decision Closed (2026-06)

**CM-Phase1-09 / PHASE1 B4 — Mirror / Single Source of Truth Strategy**

- **Decision**: GitHub (eveselove/AgentForge) is the official Single Source of Truth. Local paths are working clones only. See the full rationale and mitigations in the canonical artifact: `docs/PHASE1_B4_MIRROR_SOT_DECISION.md` (task 5f018f81).
- **Rationale summary**: Aligns with Jules-native workflows, eliminates dual-master divergence risk under high agent parallelism, leverages GitHub's built-in durability + visibility, and matches the existing mandatory-PR + agent-review + pre-commit process model.
- **Follow-up**: CM-Phase1-10 now limited to optional *backup* tooling (never promoted to SoT). Minor cross-references may be added to AGENTS.md / BRANCHING_STRATEGY.md in subsequent A5-style cleanup.
- **Traceability**: This closure, the decision document, and all related commits/PRs reference task 5f018f81. Mandatory agent-review skill handoff executed and recorded before PR per AGENTS.md.

This item is now complete. Phase 1 remote/hosting decisions are fully resolved.
