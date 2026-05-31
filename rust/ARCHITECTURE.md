# AgentForge Rust Migration Architecture (2026)

## Strategic Decision

We are moving the core of AgentForge to Rust while keeping a pragmatic hybrid approach:

- **Rust** becomes the primary language for:
  - Orchestration and task management (`agentforge-core`)
  - Safety and policy enforcement
  - Hierarchical planning
  - Observability (spans, traces, replay)
  - Long-running task management
  - High-performance runner logic (replacement for `grok_runner.sh`)

- **Python** remains (for now or via FFI) for:
  - Heavy ML workloads (LLM-as-Judge in PRM, fine-tuning, embedding models)
  - Rapid prototyping of new learning algorithms
  - Existing evaluation harness (gradual port)

## Recommended Crate Structure

```
rust/
├── crates/
│   ├── agentforge-core/           # Fundamental types, Task, Config, Worktree abstraction
│   ├── agentforge-safety/         # PolicyEngine, SandboxPolicy, ActionApproval
│   ├── agentforge-planning/       # HierarchicalPlanner, Subtask, DependencyGraph
│   ├── agentforge-observability/  # Span model, replay, OTEL export
│   ├── agentforge-learning/       # TrajectoryDataset, trainers (DPO/KTO/SFT interfaces)
│   └── agentforge-runner/         # High-performance task runner (future replacement for Bash)
```

## Interop Strategy

Options (in order of recommendation):

1. **PyO3** (preferred for tight integration)
   - Expose Rust types and functions directly to Python
   - Best for gradual migration

2. **gRPC / MessagePack over Unix socket**
   - More decoupled, language-agnostic
   - Better if we want to run heavy components in separate processes

3. **Pure Rust + lightweight Python bindings only for ML**
   - Eventually move almost everything to Rust, keep only model inference in Python/Candle

## Migration Phases (Proposed)

**Phase A (Current)**: Rust foundations + new modules (planning, safety, observability, learning skeleton)

**Phase B**: Port core orchestration and runner logic. Replace critical parts of `grok_runner.sh` with Rust.

**Phase C**: Move heavy parts of `eval/` (especially PRM and trajectory processing) or make them call into Rust.

**Phase D**: Full or near-full Rust core, Python only for specific ML experiments.

## Current Status (TURBO 2026-05-31 — all 3 phases)

- Python Phase 0/1 (eval+PRM+obs+viewer) — 100% done and battle-tested on real trajectories.
- Python Phase 2/3 reference (learning/ + planning/ + safety/ + long_horizon/ + phase2_3_integration) — complete, canonical spec for Rust port.
- **Rust crates (agentforge-*) now deliver production-grade foundation for Phase 2 + Phase 3:**
  - learning: TrajectoryDataset (filters, learning_value, versioned export), DPO/KTO/SFT trainers, SkillImprover + LLM stub.
  - planning + long-horizon (new crate): HierarchicalPlanner + full dep exec + Plan checkpoint/restore + LongTaskManager (heartbeats, pause/resume, safety gates).
  - safety: PolicyEngine with risk_score + 4 real policies + default factory.
  - observability: Span (PRM attach, events, OTEL export) + replay_trajectory_to_spans.
  - runner: run_with_full_stack demo composing everything.
- All crates compile, unit tests green, examples/phase2_3_vision.rs executes the full vision.
- Jules parallel agent + main turbo loop completed review/polish/tests/docs in one pass.

**Migration reality:** We are at Phase B/C already for the critical safety/planning/long-horizon/learning pieces. Hybrid (Rust core + Python ML) is the way.

This document will be updated as the migration progresses.
