# JULES_RUNNER_CLI_POLISH.md

**Track C completed — agentforge-runner binary production polish (2026-05-30)**

## Summary of Changes

### 1. Proper --help / Usage + Subcommand Structure
- Full documented usage via `agentforge-runner --help` (and per-global --json mode).
- Clear SUBCOMMANDS section with flags and examples.
- Globals (`--json/-j`, `--help/-h`, `--version/-V`) supported before/after subcommand.
- Subcommands implemented as specified + extras:
  - `demo [goal]`
  - `full-stack --goal G [--agent A] [--input I]`
  - `export-pairs --input I --output O [--min-prm F]`
  - `export-prm-steps --input I --output O`
  - `improve-skill --skill NAME --input I [--output O]`
  - `export-sft --input I --output O` (added)
  - `stats --input I` (added, always emits structured JSON)
  - `version`

### 2. Real Input Support
- `--input` (and aliases `--from`/`-i`/`-f`) accepts:
  - Directories of eval results (`*.json` in `eval/results`)
  - JSONL files: full `TrajectoryRecord`s, learning export pairs/flat, or raw trajectory event streams (fallback synthesizes record)
- Smart candidate resolution (absolute + `/home/eveselove/agentforge/<path>` + relatives) so relative paths work from `rust/` cwd.
- Uses new `TrajectoryDataset::load_from_real_input` / `load_from_eval_results_dir` / `load_from_jsonl` + lenient outcome parser.
- `compute_learning_value()` always run before exports.

### 3. Clean Machine-Readable `--json` Output
- When `--json` present: human logs via `eprintln!`, final result (or error envelope) via `println!` as compact JSON.
- All commands (pairs, prm-steps, sft, improve, stats, full-stack, demo) emit structured objects with `cmd`, counts, data, etc.
- Python bridge friendly: `subprocess` + `json.loads(stdout)` works for every new command.

### 4. Added 2-3+ Useful Commands for Python/Farm
- `export-prm-steps`: writes step-level PRM labels JSONL (direct from `export_prm_step_labels`).
- `export-sft`: writes success trajectories in SFT-ready shape (mirrors trainer).
- `improve-skill`: runs `SkillImprover::propose_improvements` on loaded success/fail split; outputs `ProposedSkill` + summary.
- `stats`: machine-readable dataset overview (basic_stats + by_outcome + has_prm) — ideal for post_process / flywheel scripts.
- All callable today from `learning/trajectory_dataset.py` bridge or `rust_flywheel_demo.py`.

### 5. Vision Example
- Added `agentforge-long-horizon` dependency to `crates/agentforge-runner/Cargo.toml`.
- Added explicit `[[example]]` stanza.
- `cargo run -p agentforge-runner --example phase2_3_vision` now runs cleanly end-to-end (all crates integrated: learning trainers+improver, long-horizon, planning, safety, obs, runner full-stack).

### 6. More CLI / Integration Tests that Exec the Binary
- Added in `src/lib.rs` (no new files):
  - `cli_binary_help_and_version_exec`: spawns binary, validates --help/--version text + exit codes.
  - `cli_binary_json_stats_exec`: spawns with `--json stats --input <real dir>`, validates JSON shape.
- All 4 tests in runner crate now pass (`cargo test -p agentforge-runner`).
- Existing full-stack + cross-crate serde/Outcome unification tests retained + enhanced.

### 7. Clean Warnings + Compilation Fixes
- Fixed broken `agentforge_core` re-exports in `agentforge-learning` (types.rs + lib.rs) that prevented build.
- Aligned everything on canonical `agentforge_core::Outcome` (Success/Failure/PartialSuccess/...) across learning + runner (updated parse helpers, all call sites, tests).
- Removed unused `mut`, fixed move errors in improve-skill, other small lints.
- `cargo build --offline -p agentforge-runner` and full `--workspace` checks produce **zero warnings**.
- `cargo test -p agentforge-runner` clean.

### 8. Production Tool Feel
- Binary now feels like a first-class farm dependency (replacement path for grok_runner/post_process heavy lifting).
- Robust error handling (JSON error objects under `--json`, graceful empty ds fallback).
- Consistent with Python `TrajectoryDataset` / `export_*` shapes.
- Updated docs in `--help`, code comments, and cross-crate unification notes.
- Real data flows: eval JSONs + trajectory JSONLs → Rust dataset → DPO/PRM/SFT/improver outputs consumable by training pipelines.

## Verification Commands (all succeed)
```bash
cd /home/eveselove/agentforge/rust
cargo build --offline -p agentforge-runner
./target/debug/agentforge-runner --help
./target/debug/agentforge-runner --json version
./target/debug/agentforge-runner --json stats --input eval/results
./target/debug/agentforge-runner --json export-pairs --input eval/results --output /tmp/p.jsonl
./target/debug/agentforge-runner export-prm-steps --input /home/eveselove/agentforge/eval/results --output /tmp/prm.jsonl
cargo run --offline -p agentforge-runner --example phase2_3_vision
cargo test --offline -p agentforge-runner
cargo test --offline --workspace  # (broader context)
```

## Files Changed (key paths)
- `crates/agentforge-runner/Cargo.toml` (+ long-horizon dep + [[example]])
- `crates/agentforge-runner/src/main.rs` (complete CLI rewrite + real loaders + --json)
- `crates/agentforge-runner/src/lib.rs` (+ 2 CLI exec integration tests + Outcome fixes)
- `crates/agentforge-learning/src/dataset.rs` (new load_from_*_dir/jsonl/real_input + parse_outcome + smart fallback)
- `crates/agentforge-learning/src/types.rs` + `lib.rs` (Outcome unification cleanup)
- `JULES_RUNNER_CLI_POLISH.md` (this report)

## Next (optional farm integration)
- Wire new subcommands (`export-prm-steps`, `improve-skill`, `stats`) into `learning/trajectory_dataset.py:export_*_via_rust` and `post_process.py`.
- Extend `load_from_real_input` with full trajectory event + PRM attachment (re-use Python `load_trajectory` via FFI later).
- PyO3 cdylib for zero-copy (see existing PYO3_INTEGRATION.md).

**Status: Track C complete. Binary is now a dependable production tool the AgentForge farm can call for dataset export, PRM labeling, skill improvement proposals, and full-stack orchestration.**

Jules (Rust + AgentForge specialist) — done turbo.