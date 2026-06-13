# AgentForge — Full Rust-Only Migration Plan (2026)

**Status:** Initiated 2026-05-31  
**Goal:** Eliminate Python as a runtime dependency for core AgentForge operation. The system must be able to run end-to-end using only the Rust binary + minimal necessary bridges.

**Current State (as of start of this plan):**
- Flywheel orchestration: **Rust default** (`is_pure_rust_flywheel() == True`)
- `agentforge-runner` handles: flywheel-step, continuous, candidate operations, rich export, improve-skill
- Python still present: **~90+ files**
- Critical remaining Python surfaces:
  - Task management system (API + queue)
  - Evaluation framework (trajectories, PRM, insights, regression)
  - Multiple creation and utility scripts
  - Learning bridges and post-process hooks

---

## Python Component Categorization

### Tier 1 — Must Port / Replace (Core Runtime)

| Component                  | File(s)                          | Why Critical                          | Rust Target Crate          | Priority |
|---------------------------|----------------------------------|---------------------------------------|----------------------------|----------|
| Task Queue + API          | `task_queue.py`, `mcp_server.py` | Central task distribution for all agents | agentforge-core + new task service | P0 |
| Task Creation             | `create_*.py` (multiple)        | How work enters the system            | CLI in runner or new tool  | P0 |
| Continuous Flywheel Runner| `bin/run_continuous_flywheel.py` | 24/7 autonomy entrypoint              | Direct use of runner binary| P0 |
| Post-process Hook         | `DELETED (Tier2) - direct runner`  | Bridge after real agent work          | Move logic into Rust       | P1 |
| Phase 2/3 Integration     | `phase2_3_integration.py`        | Heavy bridge for flywheel             | Already partially in Rust  | P1 |

### Tier 2 — High Value (Learning & Evaluation)

| Component             | Location              | Purpose                              | Rust Target             | Priority |
|-----------------------|-----------------------|--------------------------------------|-------------------------|----------|
| Evaluation Framework  | `eval/` (entire)     | Trajectories, PRM, insights, regression | agentforge-learning + eval crate | P1 |
| Learning Layer        | `learning/`          | TrajectoryDataset, parity, skill improver | Mostly already ported  | P1 |
| Long Horizon          | `long_horizon/`      | Complex multi-step tasks             | agentforge-long-horizon | P2 |
| Safety & Planning     | `safety/`, `planning/` | Policy + hierarchical planning     | Already in Rust crates  | P2 |

### Tier 3 — Utilities & Scripts (Lower Urgency)

- `fix_*.py`, `check_status.py`, `show_agent_stats.py`, `reassign.py`, etc.
- Example scripts
- Generated files in `pending_candidates/`

These can be kept longer or rewritten in Rust/Shell as needed.

---

## Migration Strategy — Speed Mode / Unblock Development (2026-05-31)

**Current active mode: Speed Mode** (switched because real development work is blocked behind the migration).

Focus has shifted from flooding with many small tasks to **concentrated effort on the critical path** that unblocks downstream development.

Primary target: Replace the Python Task Management layer (`task_queue.py` + `mcp_server.py`) with a viable Rust path as fast as possible.

See also: `RUST_MIGRATION_SPEED_MODE.md` for the detailed speed strategy.

---

## Previous Strategy (kept for reference)

We previously ran in **Maximum Parallelism** mode.

### Core Principles:
- Break work into the smallest possible independent atomic tasks.
- Distribute across different `preferred_agent` values (`grok`, `jules`, `auto`).
- Multiple independent workstreams run in parallel (Banners, Script Cleanup, Rust Design, Docs, Analysis, etc.).
- Prefer creating tasks in the internal system over direct edits when possible.
- Local Grok session acts as orchestrator + does high-urgency or blocking work.
- Goal: Keep as many agents as possible busy simultaneously on non-conflicting pieces.

### Current Parallel Workstreams:
1. **Deprecation Banner Wave** — many small independent file tasks
2. **Shell & Service Cleanup Wave** — different .sh and .service files
3. **Documentation Wave** — updating JULES_*, README, plans
4. **Rust Foundation Wave** — designing structs, CLI improvements, new modules
5. **Analysis & Inventory Wave** — mapping remaining surface
6. **Bridge Reduction Wave** — removing Python post-process hooks where possible

1. **Do not delete Python immediately.** Keep it as fallback during transition.
2. **Make the Rust binary the single source of truth** for all core operations.
3. **Replace Python entrypoints** with thin shell wrappers or direct Rust CLI calls.
4. **Port evaluation & learning quality components** aggressively (they directly impact flywheel fidelity).
5. **Task system** is the hardest part — consider building a small Rust task service or using the existing Rust core more heavily.

---

## Immediate Execution Steps (Turbo Mode)

- [x] Full inventory of Python files (done 2026-05-31)
- [ ] Categorize every Python file into Tier 1/2/3
- [ ] Add aggressive deprecation banners to all Python orchestration files
- [ ] Create Rust CLI surface for task management (or extend `agentforge-runner`)
- [ ] Port or replace `list_pending_candidates` + creation scripts
- [ ] Move `post_process` + after-task logic fully into Rust where possible
- [ ] Update all JULES_*, services, and docs to remove Python assumptions
- [ ] Measure: "Can we run a full flywheel cycle with zero Python in PATH?"

---

## Success Criteria

- `agentforge-runner` (or a small set of Rust binaries) can perform:
  - Task ingestion
  - Agent dispatching (or at least feeding agents)
  - Full flywheel cycle
  - Evaluation / PRM on trajectories
- No hard dependency on Python for normal operation
- Python only remains for optional tools / migration bridges

---

**Mode:** Full turbo. Use AgentForge agents (Jules waves + local implement/review) to execute this migration on itself.

This document will be the living tracker.
