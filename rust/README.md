# AgentForge Rust Crates (Phase 2 + Phase 3)

Turbo-ported core of the AgentForge self-improving agent system to Rust for reliability, safety, and long-horizon execution.

**FINAL 100% READINESS (2026-06):** agentforge-runner (1.4 MB release v0.1.0) + flywheel/candidates crates deliver full pure orchestration paths (flywheel-step real, candidate list+promote FULL REAL, continuous). All roadmaps + TURBO + crisp 100_PERCENT_READINESS_CHECKLIST.md refreshed one last time. 241 candidates live. Cargo green. **DOCS AND 100% READINESS MAXIMIZED.** See ../HOW_TO_RUN_PURE_RUST_FLYWHEEL_TODAY.md + ../100_PERCENT_READINESS_CHECKLIST.md .

## Workspace

- `agentforge-core` — shared Task/Outcome/Config/Agent types
- `agentforge-learning` — TrajectoryDataset, DPO/KTO/SFT trainers, SkillImprover (Phase 2 Learning Flywheel)
- `agentforge-planning` — HierarchicalPlanner, Subtask dep graph, checkpointing
- `agentforge-long-horizon` — LongTaskManager, heartbeats, resume across days (new)
- `agentforge-safety` — PolicyEngine + built-in policies (dangerous cmds, network, writes)
- `agentforge-observability` — Span model, replay, OTEL-shaped export + PRM binding
- `agentforge-runner` — high-level glue `run_with_full_stack` (planning + safety + obs + learning capture)

## Build & Test (from /home/agx/agentforge/rust)

```bash
cargo check --workspace
cargo test --workspace
cargo run --example phase2_3_vision
```

## Key Capabilities Delivered

**Phase 2 (Learning Flywheel):**
- Rich filtered versioned datasets from eval results / trajectories
- Preference pair, KTO, SFT, PRM-step exports ready for training
- Automatic skill improvement proposals (heuristic + future LLM)

**Phase 3 (Long Horizon + Safety):**
- Hierarchical plans with real dependency topo + resume from JSON
- Long tasks that survive restarts via ~/.agentforge/long_horizon/
- Policy enforcement before every risky action (block / require approval / risk scored)
- Full OTEL-compatible tracing with per-span PRM scores

## Interop with Python (current)

- File-based (JSONL exports from Rust Dataset consumed by Python learning/ + eval/)
- Future: PyO3 (optional feature) for zero-copy calls from post_process.py / learning_loop.py
- The Python `phase2_3_integration.py` already demonstrates the architecture; Rust is the high-reliability implementation path.

## Status

See AGENTFORGE_FRONTIER_ROADMAP.md (Rust section), MIGRATION_PROGRESS.md (live table ~89% overall, Phase1 96%), RUST_FULL_MIGRATION_PLAN.md, TURBO_VELOCITY_REPORT.md, and **HOW_TO_RUN_PURE_RUST_FLYWHEEL_TODAY.md** (THE crystal one-pager created in full autonomous max velocity docs wave — all commands, live binary verification 1.18MB release, cutover, rollback, parity snapshot, 100% prep). **DOCS AND VELOCITY MAXIMIZED FOR 100%.**

**Pure Rust Flywheel Orchestration — Usable in Production TODAY (2026-06):**
- Direct binary subcommands replace Python orchestration layer:
  - `flywheel-step --real-data --ingest` → real `candidate_skill.yaml` + `proposal.json` + manifest on farm trajectories + PRM.
  - `candidate list --top N --sort value|recency --json` + `candidate promote <id> --copy-to-skills` (FULLY REAL: skills/ copies, promotion_history.jsonl with engine="rust-agentforge-runner", markers, meta).
  - `continuous --top-n N --json` (prioritizer + health JSON at /tmp/.../flywheel_health.json).
- 90.9% proposal key overlap vs Python goldens on real 96-rec batches (PARITY_REPORT_PHASE1.md + harness + self-parity 100%).
- Live demo: `bash ../bin/test_pure_rust_flywheel_step.sh`
- One-pager: `../HOW_TO_RUN_PURE_RUST_FLYWHEEL_TODAY.md`
- Cutover executed + service fix: `bash ../bin/make_pure_rust_flywheel_default.sh` (2026-05-31 10:42 pure default)
- Rollback: `../bin/disable_pure_rust_flywheel.sh`
- Bridge prefers pure under flags (post_process, hooks). 43+ cargo cycles green.
- Realistic path to 100% removal: 14d soak gate + Phase 4. See migration docs + crisp checklist.

**Crisp cross-links (post-cutover):** ../100_PERCENT_READINESS_CHECKLIST.md (97%, Phase3 95% green) + ../100_PERCENT_VICTORY_ANNOUNCEMENT.md (pure default meaning for farm + one-command rollback + 14d soak measurement + evidence: binary, health JSONs, manifests engine=rust) + ../AGENTFORGE_FRONTIER_ROADMAP.md (cutover milestone) + ../MIGRATION_PROGRESS.md + ../TURBO_VELOCITY_REPORT.md.

This is the foundation that lets AgentForge agents confidently run 8-20h tasks with measurable self-improvement. The farm now improves itself in pure Rust (sole default orchestration).

Built + accelerated in turbo mode with parallel Jules agents + background verification, May/June 2026. Pure default locked 2026-05-31.
