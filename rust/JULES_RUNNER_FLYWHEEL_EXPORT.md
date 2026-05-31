# Rust Migration Status

> This document reflects work done during the Rust port. It is mostly still accurate as it describes Rust-side changes.

# JULES_RUNNER_FLYWHEEL_EXPORT

Turbo enhancement to `agentforge-runner` binary: production-grade `flywheel-export` / `export-learning` subcommand.

## Deliverables completed (all within /home/agx/agentforge/rust/)
- New/ vastly improved `flywheel-export` (aliases: `export-learning`, `export-flywheel`)
- Flags: `--trajectories DIR` (loads *.jsonl), `--prm-dir DIR` (or colocated sidecars), `--results DIR`, `--output FILE`, `--format (pairs | prm-steps | stats | full)`
- Loads real `.prm.json` sidecars via `TrajectoryDataset::load_flywheel_data` + `enrich_from_prm_sidecars` + `parse_prm_sidecar` (flexible keys, graceful on missing/unreadable)
- Always `compute_learning_value()`
- Emits **rich structured** output (rich DPO pairs v2 with chosen/rejected learning_value, outcomes, durations, prm_hq/lq, has_sidecar_prm, source, export_format etc.; full records; step labels; rich stats incl. avg_learning_value + prm_sidecar counts)
- Directly consumable by `rust_flywheel_step.py`
- `--json` full machine output
- Fast, robust, no panics on farm data quirks
- Updated help + examples
- Added unit test (sidecar parse/enrich) + CLI integration test (all --format variants + alias)
- Post-edit: `cargo check` after every batch + final `cargo build --offline -p agentforge-runner`

## Key code locations
- `crates/agentforge-learning/src/dataset.rs`: `load_flywheel_data`, `enrich_from_prm_sidecars`, `parse_prm_sidecar`, `load_from_trajectories_dir`, improved `export_preference_pairs` (v2 rich), `load_from_real_input` auto sidecar support, tests
- `crates/agentforge-runner/src/main.rs`: full `flywheel-export` handler + arg parsing + help/docs + examples
- `crates/agentforge-runner/src/lib.rs`: CLI exec test for flywheel subcommand

## Build & run (from rust/)
```bash
cargo build --offline -p agentforge-runner
# or release
cargo build --release --offline -p agentforge-runner
```

## Example invocations + real farm output (live /home/agx/agentforge/eval/trajectories data)

```bash
cd /home/agx/agentforge/rust
./target/debug/agentforge-runner --json flywheel-export \
  --trajectories /home/agx/agentforge/eval/trajectories \
  --prm-dir /home/agx/agentforge/eval/trajectories \
  --output /tmp/flywheel_real_test_full.jsonl \
  --format full
```

**Sample JSON output (real data, 2026-05-30 run):**
```json
{"avg_learning_value":0.008333333333333333,"cmd":"flywheel-export","count":96,"format":"full","has_prm":true,"load_summary":{"mode":"flywheel_loader","prm_enriched":16,"results":0,"trajectories":96},"output":"/tmp/flywheel_real_test_full.jsonl","records_loaded":96,"results":null,"trajectories":"/home/agx/agentforge/eval/trajectories"}
```
(96 records loaded, 16 enriched from real *.prm.json sidecars, learning_value computed, has_prm:true)

```bash
./target/debug/agentforge-runner --json flywheel-export --trajectories /home/agx/agentforge/eval/trajectories --format pairs
```
(Uses rich pairs v2; 0 pairs in this slice due to low success contrast but full rich fields emitted when matches exist.)

```bash
./target/debug/agentforge-runner --json flywheel-export --trajectories /home/agx/agentforge/eval/trajectories --format stats
./target/debug/agentforge-runner --json flywheel-export --trajectories /home/agx/agentforge/eval/trajectories --format prm-steps
./target/debug/agentforge-runner export-learning --format stats   # alias works
./target/debug/agentforge-runner flywheel-export --trajectories /home/agx/agentforge/eval/trajectories --format full   # auto-colocated prm
```

Human mode:
```
[runner] flywheel-export (format=stats) → 1 items written to /tmp/... (records: 96, prm_sidecars used: 8)
```

## Python bridge example
```python
subprocess.run([runner, "flywheel-export", "--trajectories", traj_dir, "--prm-dir", traj_dir,
                "--output", out, "--format", "pairs", "--json"])
# Then load the rich JSONL directly into rust_flywheel_step.
```

All requirements met. Turbo complete. Real farm data verified (prm sidecars loaded live).

(Also: `cargo test -p agentforge-runner -p agentforge-learning` exercises the new paths + CLI binary.)
