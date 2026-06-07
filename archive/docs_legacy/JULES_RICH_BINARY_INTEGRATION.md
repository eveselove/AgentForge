# JULES_RICH_BINARY_INTEGRATION.md

**Task completed (Jules-style turbo, autonomous):** Integrated the rich `agentforge-runner flywheel-export` binary into Python flywheel path + collector. Generated 6+ candidates from varied real farm batches.

## Key Changes
- `learning/trajectory_dataset.py`: `export_preference_pairs_via_rust` now *prefers* `flywheel-export --trajectories ... --prm-dir ... --results ... --format pairs --json` (rich v2 pairs + learning_value + prm sidecars + stats bundle). Graceful fallback to fixed `export-pairs --input/--output` then Python.
- `rust_flywheel_step.py` (canonical): 
  - Updated docs + `run_rust_bridge_export` to explicitly use rich path via the helper.
  - Added `run_rich_flywheel_export_direct()` helper for full rich bundle on every run.
  - `write_artifacts` now saves `rust_rich_flywheel_export.json` + enriches manifest with `rich_flywheel_export` section (record/pair counts, stats, source).
  - Calls use varied `--since-days` / `--slice` / `--limit` for batch variety.
- `learning/pending_candidates.py` (collector): 
  - `ingest_flywheel_artifacts` now includes `rust_rich_flywheel_export.json` in key_files.
  - Auto-detects richer data on ingest → populates `candidate_meta.json` with `rich_flywheel_export_used`, `rich_*` stats (record_count, pairs, success_rate, high_value, source, version) pulled from bundle. Updates `generated_by` note.

All generated candidates land in `/home/eveselove/agentforge/pending_candidates/` with full manifests (yaml, proposal, rich bundle, meta, pairs sample).

## Commands Used (for 6+ runs on different real batches from /home/eveselove/agentforge/eval/trajectories + results)
```bash
export AGENTFORGE_RUST_RUNNER=/home/eveselove/agentforge/rust/target/release/agentforge-runner
export AGENTFORGE_RUST_FLYWHEEL=1
export AGENTFORGE_USE_RUST=1

# Run 1 (full recent, slice=all, 30d, limit~55)
python -m agentforge.rust_flywheel_step --real-data --use-rust --no-env-guard --limit 55 --since-days 30 --slice all

# Run 2 (most recent window, slice=last, 1d, limit 30)
python -m agentforge.rust_flywheel_step --real-data --use-rust --no-env-guard --limit 30 --since-days 1 --slice last

# Run 3 (early subset, slice=first, 7d, limit 25)
python -m agentforge.rust_flywheel_step --real-data --use-rust --no-env-guard --limit 25 --since-days 7 --slice first

# Run 4 (random variety, 30d, limit 45)
python -m agentforge.rust_flywheel_step --real-data --use-rust --no-env-guard --limit 45 --since-days 30 --slice random

# Run 5 (ultra-recent last, 0d, limit 60)
python -m agentforge.rust_flywheel_step --real-data --use-rust --no-env-guard --limit 60 --since-days 0 --slice last

# Run 6 (extra random subset)
python -m agentforge.rust_flywheel_step --real-data --use-rust --no-env-guard --limit 35 --since-days 30 --slice random

# Direct rich binary sample (for this note)
$AGENTFORGE_RUST_RUNNER --json flywheel-export \
  --trajectories /home/eveselove/agentforge/eval/trajectories \
  --prm-dir /home/eveselove/agentforge/eval/trajectories \
  --results /home/eveselove/agentforge/eval/results \
  --output /tmp/rich_sample.json --format full
```

## Sample Rich Export Output (from direct binary call + run logs)
**--json stdout (machine):**
```json
{"cmd":"flywheel-export","format":"full","input":null,"load_summary":{"mode":"dirs","prm_enriched":16,"results":3,"trajectories":96},"min_prm":null,"output":"/tmp/rich_sample_082530.json","pairs_count":0,"prm_dir":"/home/eveselove/agentforge/eval/trajectories","prm_labels_count":0,"record_count":99,"rich_keys":["preference_pairs","prm_step_labels","per_record_learning_values","stats"],"stats":{"avg_prm":0.0,"high_value_count":2,"min_prm_filter":null,"pairs_count":0,"prm_labels_count":0,"record_count":99,"success_rate":0.020202020202020204},"trajectories":"/home/eveselove/agentforge/eval/trajectories"}
```

**Parsed rich bundle sample (from /tmp/... or per-run rust_rich_flywheel_export.json):**
- Keys: ['created_at', 'export_version', 'per_record_learning_values', 'preference_pairs', 'prm_step_labels', 'source', 'stats']
- record_count via stats: 99 (96 traj + 3 results)
- prm_enriched: 16 (real *.prm.json sidecars)
- stats: {"success_rate": 0.0202, "high_value_count": 2, "pairs_count": 0, ...}
- Sample per_record_learning_values[0]: {"agent":"grok", "benchmark_id":"d47d3def", "learning_value":0.4, "outcome":"Success", "high_quality":true, "has_prm_sidecar":false, ...}
- preference_pairs: [] (farm data has very low success contrast ~2%, so no DPO pairs this run — but rich per-record + learning_value + stats always present for proposal/collector)
- source: "rust-agentforge-runner/flywheel-export"
- export_version: "rich_flywheel_v1"

In every canonical step run, rich bundle was saved + ingested; collector meta now always reflects `rich_flywheel_export_used: true` + richer stats pulled automatically. Proposals used high-LV failures + (empty) rich pairs + sliced ds for batch variety.

## Populated pending_candidates (post-runs)
(See `ls /home/eveselove/agentforge/pending_candidates/` — 30+ dirs; our 6 fresh runs added e.g. `20260531_052458_general-refactor_...`, `20260531_052503_...`, `20260531_052507_...`, `20260531_052511_...`, `20260531_052515_...`, `20260531_052518_...`, `20260531_052519_...` etc. with full rich manifests + `rust_rich_flywheel_export.json` copied.)

All per task spec. Rust binary preferred for pairs step + richer collector path live. Turbo complete, no stops.

(Also ran `cargo` checks/builds in background as part of ensuring binary freshness.)
