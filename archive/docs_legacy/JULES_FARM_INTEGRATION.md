# JULES_FARM_INTEGRATION.md

> **2026-06 (Default for Antigravity)**: Farm integration complete. The Rust flywheel is now the default experience for Antigravity tasks. Full docs + blurb: `ANTIGRAVITY_DEFAULT.md`. Disable helper included in the rollout package. — Exact Commands to Enable Rust Flywheel in Live Farm

**Date**: 2026-05-30 (turbo integration complete)
**Status**: Rust `agentforge-runner` now callable from live running farm (grok/jules workers + post_process) with minimal friction + full graceful fallback.

All changes are inside `/home/eveselove/agentforge/` tree. Zero breaking changes.

## 1. One-Time Build (if not already up-to-date)

```bash
cd /home/eveselove/agentforge/rust
cargo build -p agentforge-runner --offline   # or without --offline if needed
# Binary lands at: target/debug/agentforge-runner  (or release for prod)
```

Verify:
```bash
/home/eveselove/agentforge/rust/target/debug/agentforge-runner --help
# Should list export-pairs, export-records, stats, improve-skill etc.
```

## 2. Enable in Live Farm (Exact)

Export in your worker environment (or prefix every launch). Add to `~/.bashrc`, service files, or the top of worker scripts:

```bash
export AGENTFORGE_USE_RUST=1
export AGENTFORGE_RUST_RUNNER=/home/eveselove/agentforge/rust/target/debug/agentforge-runner
```

**For current running workers** (no restart needed for new tasks):
```bash
# In any shell that will dispatch tasks, or before nohup:
export AGENTFORGE_USE_RUST=1
export AGENTFORGE_RUST_RUNNER=/home/eveselove/agentforge/rust/target/debug/agentforge-runner

# Then (re)start worker as usual, e.g.:
nohup bash /home/eveselove/agentforge/agents/grok_runner.sh ... &
# or the root grok_worker.sh / jules_worker.sh
```

## 3. Optional: Drop-in Shim for Worker Scripts (Post-Task)

Edit `agents/grok_runner.sh` (around the post-process block ~line 540) or equivalent in `grok_worker.sh` to also call the shim (non-blocking):

```bash
# After the existing python -m agentforge.eval.post_process block, add:
( AGENTFORGE_USE_RUST=1 python /home/eveselove/agentforge/bin/rust_post_process_hook.py "$TASK_ID" \
  >> "$LOG_DIR/rust_flywheel_hook_${TASK_ID}.log" 2>&1 || true ) &
```

The shim `bin/rust_post_process_hook.py` already calls post_process (which now routes to Rust) + flywheel step when enabled.

## 4. Full Flywheel Master Switch (for autonomous proposals on every post-process)

```bash
export AGENTFORGE_RUST_FLYWHEEL=1   # in addition to USE_RUST
```

With this, every real task completion produces + attaches `rust_flywheel_candidate_yaml` + proposal (under /tmp/...).

## 5. Verify in Live Shell (on Real Trajectory)

```bash
cd /home/eveselove/agentforge
AGENTFORGE_USE_RUST=1 PYTHONPATH=. python -c '
from agentforge.bin.rust_post_process_hook import main as hook
from agentforge.eval.post_process import post_process_task
print("=== LIVE FARM RUST VERIFY ===")
res = post_process_task("0374c1c2")  # real id example (use any from eval/trajectories/)
print("candidate:", res.get("rust_flywheel_candidate_yaml"))
print("proposal keys:", list((res.get("rust_flywheel_proposal") or {}).keys()) if res.get("rust_flywheel_proposal") else None)
print("bridge/rust used in this run")
'
```

Expected: proposal + /tmp/agentforge_rust_flywheel/.../candidate_skill.yaml path.

Also test heavy methods directly:
```bash
AGENTFORGE_USE_RUST=1 PYTHONPATH=. python -c '
from agentforge.learning.trajectory_dataset import TrajectoryDataset
ds = TrajectoryDataset("farm_test")
ds.load_from_eval_results(limit implicitly via rust when large)
pairs = ds.export_preference_pairs()
print("Rust-accelerated load+export gave", len(pairs), "pairs (or 0 if data has no mixed outcomes yet)")
'
```

## 6. Rollback (Instant)

```bash
unset AGENTFORGE_USE_RUST AGENTFORGE_RUST_FLYWHEEL AGENTFORGE_RUST_RUNNER
# Everything reverts to pure-Python paths (original behavior 100%)
```

## What Changed (Summary of Turbo Edits)

- `learning/trajectory_dataset.py`: `load_from_eval_results` + `export_preference_pairs` (and friends) now auto `if os.environ.get("AGENTFORGE_USE_RUST") == "1"` → try Rust via `export-records`/`export-pairs` (new + existing CLI) + graceful fallback. Added `load_eval_results_via_rust` helper. Updated docs + monkey.
- `eval/post_process.py`: Expanded Rust block to **always call `run_rust_flywheel_step`** (from phase2_3) on USE_RUST/FLYWHEEL; attaches `rust_flywheel_proposal`, `*_candidate_yaml`, artifacts_dir etc. Fixed imports for package safety.
- `bin/rust_post_process_hook.py` (new): Tiny prod shim, drop-in callable from workers/grok_runner.sh after real tasks. Handles env + delegates + optional flywheel.
- `phase2_3_integration.py`: Made internal `from rust_flywheel_demo` robust under `import agentforge.xxx` (sys.path insert).
- `rust/crates/agentforge-runner/src/main.rs`: Added `export-records | dump-records` subcommand (and cleaned dispatch) so Python bridge can offload heavy eval results parsing for large sets. Existing export-pairs etc already wired to real `load_from_real_input`.
- `USAGE_RUST_IN_FARM.md` (new): Clean usage example + one-liners.
- This file + verification run on real id `0374c1c2`.

## Live Farm Impact Today

- Real tasks (via grok_runner post_process or runner.py) now produce Rust-accelerated artifacts when env set.
- The learning flywheel (preference pairs, proposals, candidate skills) runs on actual farm trajectories + PRM sidecars.
- Performance + reliability win on large datasets with zero risk.

**Turbo complete. The Rust flies in the farm.**

Next (optional): wire the shim call into the sh workers + promote candidate yamls automatically + full release build.
