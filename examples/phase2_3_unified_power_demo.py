#!/usr/bin/env python3
"""
examples/phase2_3_unified_power_demo.py

!!! AGGRESSIVE FINAL DEPRECATION SWEEP (RUST_FULL_MIGRATION_PLAN.md + PHASE4_REMOVAL_PLAN.md) !!!
Python flywheel orchestration demo DEPRECATED — Phase 4 removal target.
MIGRATE TO: agentforge-runner flywheel-step --real-data --ingest etc.
Guard exclusively: from agentforge.learning.utils import is_pure_rust_flywheel
See learning/utils.py (even stronger guards + file list) + PHASE4_REMOVAL_PLAN.md

Small but extremely powerful demonstration of the Phase 2/3 integration layer.

It shows the complete stack working together in < 30 lines of user code:

- Hierarchical planning + long-horizon checkpointing
- Safety policy enforcement (including PRM-aware rules)
- Automatic PRM scoring + rich observability spans on every step
- Direct feed into the Learning Flywheel (TrajectoryDataset)
- Seamless use of the existing eval runner infrastructure

Run:
    PYTHONPATH=. python -m agentforge.examples.phase2_3_unified_power_demo
    # or
    python agentforge/examples/phase2_3_unified_power_demo.py

This is the "glue that makes the new architecture feel real".
"""

from agentforge.phase2_3_integration import (
    run_long_task_with_planning_safety_and_prm_logging,
    auto_capture_learning_dataset,
    instrument_any_trajectory,
)
from agentforge.observability import summarize_spans


def main():
    print("=" * 72)
    print("AgentForge Phase 2/3 Unified Power Demo")
    print("Planning + Safety + Long Horizon + PRM Observability + Learning Flywheel")
    print("=" * 72)

    # === THE ONE-LINER THAT CHANGES EVERYTHING ===
    result = run_long_task_with_planning_safety_and_prm_logging(
        goal="Tune adaptive throttle for 4G mobile proxies using recent low-PRM trajectories + safety guardrails",
        agent="grok",
        use_real=False,           # Flip to True + --wait in real CI / prod
        benchmark_id="adaptive-throttle-tuning-001",
        auto_prm=True,
        export_spans=True,
    )

    print("\n[Demo] Long-horizon execution complete.")
    print(f"       LongTask ID     : {result.long_task_id}")
    print(f"       Outcome         : {result.outcome}")
    print(f"       PRM overall     : {result.prm_overall}")
    print(f"       Safety blocks   : {result.safety_blocks}")
    print(f"       Learning records prepared: {result.learning_dataset_records}")

    if result.spans_summary:
        print(f"       Observability   : {result.spans_summary['total_spans']} spans, "
              f"avg_prm={result.spans_summary.get('avg_prm')}, "
              f"llm_calls={result.spans_summary.get('llm_calls')}")

    # === Second killer capability: instant high-quality learning dataset ===
    print("\n[Demo] Building flywheel dataset from existing eval runs (Phase 2)...")
    ds = auto_capture_learning_dataset(min_prm=0.50, only_real=False, limit=20)
    print(f"       Dataset '{ds.name}' now contains {len(ds.records)} filtered TrajectoryRecords")
    if ds.records:
        print(f"       Top record PRM: {ds.records[0].prm_overall} (ready for DPO/KTO/SFT/PRM training)")

    # === Third: any previous trajectory can be instantly instrumented ===
    print("\n[Demo] Instrumenting a prior trajectory with full PRM+spans (if any exist)...")
    try:
        # Works on real task ids or the synthetic ones we just created
        info = instrument_any_trajectory(result.long_task_id, export=False)
        print(f"       Replayed into {info['spans_count']} spans with PRM attached")
    except Exception as e:
        print(f"       (no prior trajectory or graceful skip: {e})")

    print("\n" + "=" * 72)
    print("Phase 2/3 foundations are not only present — they are COMPOSABLE TODAY.")
    print("The eval runner, PRM, observability, planning, safety, long_horizon and")
    print("learning modules now operate as a single coherent self-improving system.")
    print("=" * 72 + "\n")

    # PHASE 2 SHADOW (FURTHER ENRICHED v4 + farm usability): easiest auto-paired dual
    #   python -m agentforge.learning.flywheel_parity.parity_harness --shadow-compare-latest --json
    # Produces /tmp/.../shadow_fidelity_latest.json with v4 metrics (bigram, numeric_deltas, title diffs, pass/score etc)
    # for continuous farm monitoring/gates.
    print("[Phase2 shadow v4 example] Easiest auto-paired enriched shadow (farm-ready):")
    print("  PYTHONPATH=. python -m agentforge.learning.flywheel_parity.parity_harness --shadow-compare-latest --json")
    try:
        from agentforge.learning.flywheel_parity.parity_harness import FlywheelParityHarness
        h = FlywheelParityHarness()
        # Real: h.run_shadow_compare_latest() or h.run_live...() for v4 JSONs
        print("  (Real runs auto-write v4 fidelity with expanded diffs + gates.)")
    except Exception:
        pass
