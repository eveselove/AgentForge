# Rust Migration Plan (100% Rustification)

This document outlines the strategic plan to migrate all remaining Python components in AgentForge to Rust, achieving a 100% native Rust ecosystem for maximum performance, memory safety, and concurrency.

## Phase 1: Worker Consolidation & Orchestration (High Priority)
Currently, workers (`antigravity_worker.py`, `builder_worker.py`, `core/grok_worker.py`) run as separate Python scripts relying on process isolation via git worktrees.
- **Goal:** Create a unified Rust `agentforge-runner` capable of spawning worker threads/tasks natively.
- **Action Items:**
  - Port `antigravity_worker.py` logic (Model Rate-Limit Rotation, atomic POST `/claim`, Guardian interaction) to a native Rust worker pool.
  - Implement Git worktree isolation in Rust using `std::process::Command` or `git2-rs`.
  - Migrate `watchdog.py` and `core/agentforge_watchdog.py` into a Rust supervisor daemon.
  - Port MCP server bindings (`mcp_server.py`) to Rust.

## Phase 2: Core Subsystems (`safety/`, `planning/`, `observability/`)
- **Goal:** Bring critical path business logic into `agentforge-core`.
- **Action Items:**
  - **Safety:** Rewrite `safety/policy_engine.py` and `safety/sandbox.py` into a Rust `agentforge-safety` crate. Apply WebAssembly or native sandboxing for task isolation.
  - **Planning:** Port `planning/planner.py` to Rust, integrating directly with LanceDB for memory retrieval.
  - **Observability:** Migrate `observability/spans.py` and `observability/replay.py` to use `tracing` and `tracing-subscriber` in Rust.

## Phase 3: Utilities and Binaries (`bin/`)
- **Goal:** Replace slow Python startup times for CLI utilities with instantaneous Rust binaries.
- **Action Items:**
  - Rewrite `consume-handoff-reviews.py` into `agentforge-cli review consume`.
  - Rewrite `swarm-decompose.py` into `agentforge-cli swarm decompose`.
  - Rewrite `lance_compact.py` (already partially handled by Gateway's background compaction).

## Phase 4: Evaluation & Analytics (`eval/`, `learning/`)
This is the largest remaining Python module, currently used for generating trajectory reports and evaluating learning datasets.
- **Goal:** Build `agentforge-eval` as a dedicated Rust workspace capable of parallelized evaluation against LanceDB.
- **Action Items:**
  - Port `eval/runner.py` and `eval/report.py` to Rust using `tera` or `askama` for template generation.
  - Rewrite `learning/trajectory_dataset.py` for high-throughput LanceDB batch processing.
  - Replace `eval/phase1_demo.py` and legacy testing frameworks with Rust `#[test]` macros and `cargo test`.

## Success Criteria
- [ ] `find . -name "*.py"` returns 0 results.
- [ ] 100% of Gateway, Workers, and Evaluators run as compiled Rust binaries.
- [ ] Docker footprint reduced by removing Python environment overhead.
