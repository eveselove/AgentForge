# AgentForge — Code Management & Repository Professionalization Plan

**Date:** 2026-05-31  
**Goal:** Bring the entire AgentForge codebase under proper, professional source control and project management, using AgentForge itself (dogfooding) in turbo mode with Jules + local agents.

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

- [ ] Create this plan document + break into trackable tasks in the internal task system
- [ ] Create a clean backup branch of current dirty state (`backup/pre-management-2026-05-31`)
- [ ] Aggressive .gitignore improvements (pycache, logs, target/, *.bak.*, .pure* markers that shouldn't be committed, etc.)
- [ ] Commit a "pre-management baseline" so we have a clean starting point
- [ ] Document current repo structure (Rust workspace layout, Python package, services)

### Phase 1 — Remote & Hosting (Critical)

- [ ] Decide on hosting location (GitHub personal/org, self-hosted Gitea/Forgejo, or internal)
- [ ] Initialize remote + first push (protected `main` branch)
- [ ] Set up branch protection rules (require agent review for merges where possible)
- [ ] Mirror strategy or single source of truth decision

### Phase 2 — Development Workflow (Turbo with Agents)

- [ ] Define branching strategy (recommend: trunk-based with short-lived agent branches)
- [ ] Integrate task system with Git (every significant change linked to task ID)
- [ ] Make `jules_runner` and local `implement` + `agent-review` the default path for changes
- [ ] Create `CONTRIBUTING.md` and `AGENTS.md` that describe "how we develop AgentForge using AgentForge"
- [ ] Pre-commit hooks or simple lint/format gates

### Phase 3 — CI/CD & Quality Gates

- [ ] GitHub Actions (or equivalent) for:
  - Rust workspace build + test (all crates)
  - Python health + parity harness
  - Service validation
- [ ] Automated release binary building for `agentforge-runner`
- [ ] Shadow / fidelity checks on PRs (future)

### Phase 4 — Self-Management (Dogfooding)

- [ ] All future development of AgentForge itself goes through the internal task queue with `preferred_agent` routing
- [ ] Use the Rust flywheel on trajectories produced while developing AgentForge
- [ ] Close the loop: improving the code management system itself feeds the flywheel

---

## Immediate Next Actions (Start in This Session)

1. Create backup branch + improved .gitignore (quick win)
2. Create 5–7 high-quality tasks in the task system for this plan (with proper `preferred_agent`)
3. Begin execution using:
   - Local Grok + `implement` / `agent-review` skills for code changes
   - Jules (once repo connectivity for the target is resolved)
4. Produce visible artifacts (cleaner tree, first remote push, updated docs)

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
