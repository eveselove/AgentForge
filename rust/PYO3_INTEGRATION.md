# PyO3 Integration & File-based Interop for AgentForge Rust Crates

## Current Recommended: File-based / Subprocess Interop (No FFI needed yet)

The `agentforge-runner` binary (and future bins) provides a clean boundary for Python:

- Build: `cargo build -p agentforge-runner --release` → `target/release/agentforge-runner`
- Exec from Python (e.g. eval/post_process, phase2_3_integration):
  ```python
  import subprocess, json
  out = subprocess.check_output(["/path/to/agentforge-runner", goal, agent], text=True)
  # or for dataset export (future): --export-preference-pairs /path/to/dataset.jsonl
  ```
- Benefits: zero Python build deps, works today, easy to version, crash-isolated.
- Example quick-win: Python `TrajectoryDataset` can shell out to Rust bin for `export_preference_pairs()` / `save_versioned()` on large data (see task 6 suggestion below).

The Rust `TrajectoryDataset`, trainers (DPO/KTO/SFT), `replay_trajectory_to_spans` etc already produce/consume the same JSONL + manifest format as `agentforge/learning/`.

## Optional Future: PyO3 Bridge Stub

Add to a crate (e.g. agentforge-core or new agentforge-py):

```toml
[dependencies]
pyo3 = { version = "0.21", features = ["extension-module"], optional = true }

[features]
python = ["pyo3"]
```

Stub in `src/py_bridge.rs` (or lib):

```rust
use pyo3::prelude::*;
use crate::planning::HierarchicalPlanner; // etc

#[pyfunction]
fn decompose_goal(goal: &str) -> PyResult<String> {
    let p = HierarchicalPlanner::new();
    let plan = p.decompose(goal);
    Ok(serde_json::to_string(&plan).unwrap())
}

#[pymodule]
fn agentforge_rust(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(decompose_goal, m)?)?;
    // expose Dataset, run_with_full_stack, Span etc.
    Ok(())
}
```

Build with `maturin` or `setuptools-rust`. Expose:

- `agentforge_rust.planning.decompose(...)`
- `agentforge_rust.learning.TrajectoryDataset` (via pyclass)
- `agentforge_rust.observability.replay...`
- Full stack runner entry.

See ARCHITECTURE.md for migration phases. File-based is sufficient and preferred until perf requires in-proc.

## Python side usage sketch (eval integration)

```python
# in agentforge/eval/ or post_process
def rust_export_dataset(py_ds_path: str) -> list:
    bin_path = os.path.join(..., "target/release/agentforge-runner")
    # extend bin to support `agentforge-runner --cmd export-pairs --in file.jsonl`
    data = subprocess.check_output([bin_path, "--export", py_ds_path])
    return json.loads(data)
```

This enables "Rust binary that can be exec'ed from Python for dataset export".

## Status (2026)
- File interop: ready (JSONL roundtrips via serde)
- PyO3 stub: documented, implementation deferred to Phase C/D when Python ML wants zero-copy access to Rust PRM/Span/Trainer.
