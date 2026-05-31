# AgentForge — Code Management & Repository Professionalization Plan

**Date:** 2026-05-31  
**Goal:** Bring the entire AgentForge codebase under proper, professional source control and project management, using AgentForge itself (dogfooding) in turbo mode with Jules + local agents.

> **Current Status (updated live):**  
> Standalone GitHub repo: https://github.com/eveselove/AgentForge (now public)  
> `main` branch initialized and pushed.  
> CONTRIBUTING.md + AGENTS.md + CODEOWNERS + PR template added.  
> Basic CI workflow in place.  
> Branch protection: Manual setup recommended (see `.github/BRANCH_PROTECTION.md`).  
> Extreme parallel agent execution + Jules automation active.

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
- [x] Document current repo structure (Rust workspace layout, Python package, services) — REPO_STRUCTURE.md created + AGENTS.md covers much of it

### Phase 1 — Remote & Hosting (Critical)

- [x] Decide on hosting location (GitHub personal/org, self-hosted Gitea/Forgejo, or internal) → **GitHub (eveselove/AgentForge)**
- [x] Initialize remote + first push (`main` branch pushed to https://github.com/eveselove/AgentForge)
- [ ] Set up branch protection rules (require agent review for merges where possible) — **blocked on GitHub Pro for private repo**
- [ ] Mirror strategy or single source of truth decision
- [x] Created basic CI workflow (`.github/workflows/ci.yml`)

### Phase 2 — Development Workflow (Turbo with Agents)

- [ ] Define branching strategy (recommend: trunk-based with short-lived agent branches)
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

## Immediate Next Actions (Start in This Session) — Updated 2026-05-31 (Full Power Mode)

1. ✅ Backup branch + aggressive .gitignore + baseline commit done
2. ✅ Standalone GitHub repo created (public): https://github.com/eveselove/AgentForge
3. ✅ CONTRIBUTING.md + AGENTS.md + CODEOWNERS + PR template created
4. ✅ Basic CI workflow added and improved
5. ✅ Created 10+ high-quality tasks in queue for remaining Phase 2 & Phase 3 items
6. ✅ Launched parallel Jules wave (both keys) + local Grok agents on Phase 2 tasks
7. ✅ Created starter `bin/pre-commit`, `docs/BRANCHING_STRATEGY.md`, `REPO_STRUCTURE.md`
8. In progress: Full agent swarm working on branching strategy, pre-commit integration, and automation quality
9. Next priority: Strengthen CI (full tests + caching), finish branching strategy doc, wire pre-commit into agent workflows
10. Phase 4 dogfooding: Start routing all remaining CM work exclusively through task queue + flywheel

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
