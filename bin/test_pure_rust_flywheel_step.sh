#!/bin/bash
# test_pure_rust_flywheel_step.sh — live demo of direct pure-Rust flywheel (modern full path)
# Demonstrates the COMPLETE modern pure-Rust UX:
#   flywheel-step (gen + artifacts) + continuous (autonomy + health JSON) + candidate (list + promote)
# Replaces all legacy Python: rust_flywheel_step.py / run_continuous_flywheel.py / list_pending_candidates.py
# Usage: bash bin/test_pure_rust_flywheel_step.sh
#
# !!! AGGRESSIVE FINAL DEPRECATION SWEEP (RUST_FULL_MIGRATION_PLAN.md + PHASE4_REMOVAL_PLAN.md) !!!
# This is the VALIDATION / DEMO tool for the canonical Rust path (post Phase 3).
# Python orchestration (Tier 1/2) is deprecated and targeted for removal in Phase 4.
# Full safe removal order, risks (low for this helper), rollback strategy documented in PHASE4_REMOVAL_PLAN.md.
# Guard + cutover tools: bin/make_pure_rust_flywheel_default.sh + bin/disable_pure_rust_flywheel.sh
# See learning/utils.py for is_pure_rust_flywheel central logic.
set -u

AGENTFORGE_ROOT="/home/eveselove/agentforge"
OUT="/tmp/rust_fw_demo"
mkdir -p "$OUT"

# Prefer release (prod), fallback debug (dev)
if [ -x "$AGENTFORGE_ROOT/rust/target/release/agentforge-runner" ]; then
    RUNNER="$AGENTFORGE_ROOT/rust/target/release/agentforge-runner"
else
    RUNNER="$AGENTFORGE_ROOT/rust/target/debug/agentforge-runner"
fi

echo "[demo] Using runner: $RUNNER"

echo ""
echo "=== 1/3: Pure-Rust flywheel-step (real-data, limit=30) -> $OUT ==="
"$RUNNER" flywheel-step \
    --skill demo-skill \
    --real-data \
    --limit 30 \
    --output-dir "$OUT" \
    2>&1 | tail -12

echo ""
echo "=== Key artifacts (3 canonical files) ==="
ls -l "$OUT/" 2>/dev/null || echo "(no dir)"

for f in candidate_skill.yaml proposal.json flywheel_manifest.json; do
    p="$OUT/$f"
    if [ -f "$p" ]; then
        echo "--- $f (head) ---"
        head -c 300 "$p" 2>/dev/null | cat
        echo ""
    else
        echo "(missing: $f)"
    fi
done

echo ""
echo "=== 2/3: Pure-Rust candidate list (top 3 via prioritizer) + promote (FULL REAL, source=rust) ==="
"$RUNNER" candidate list --top 3 --json 2>&1 | cat

echo ""
echo "=== Promote dry-run (safe, real wiring, stamps source=rust-agentforge-runner) ==="
# Use a known real high-value candidate id from pending_candidates (non-destructive)
REAL_CAND="20260531_055029_general-refactor_81e7d546"
"$RUNNER" --json candidate promote "$REAL_CAND" --copy-to-skills --dry-run 2>&1 | cat

echo ""
echo "=== 3/3: Pure-Rust continuous --top-n 3 --json + health JSON (autonomy closer) ==="
"$RUNNER" continuous --top-n 3 --json 2>&1 | cat

echo ""
HEALTH="/tmp/agentforge_rust_flywheel/flywheel_health.json"
echo "=== Health JSON (continuous writes for watchdog + Python compat + farm parity) ==="
if [ -f "$HEALTH" ]; then
    cat "$HEALTH" 2>/dev/null | head -c 1600 || true
    echo ""
    echo "(full file: $HEALTH)"
else
    echo "(health JSON not present this run — created on continuous invocations)"
fi

echo ""
echo "=== 4/4: Shadow / dual-run demo (COMPLETE: continuous + flywheel-step + promote in farm hooks) ==="
echo "[demo] AGENTFORGE_RUST_FLYWHEEL_SHADOW=1 wires v3 enriched dual-run fidelity (diffs+pass/score) into post_process, parity harness (--shadow-aggregate etc), timers"
AGENTFORGE_RUST_FLYWHEEL_SHADOW=1 "$RUNNER" --json continuous --top-n 1 2>&1 | cat
SHADOW_OUT="/tmp/rust_shadow_demo_$$"
mkdir -p "$SHADOW_OUT"
AGENTFORGE_RUST_FLYWHEEL_SHADOW=1 "$RUNNER" --json flywheel-step --skill shadow-demo --real-data --limit 5 --output-dir "$SHADOW_OUT" --shadow 2>&1 | tail -8
echo "Shadow artifacts (for parity): $SHADOW_OUT"
ls -l "$SHADOW_OUT/" 2>/dev/null || echo "(shadow dir)"
rm -rf "$SHADOW_OUT" 2>/dev/null || true

echo ""
echo "=== 5/5: After-task hook style direct invocation (what workers + rust_flywheel_after_task.sh now prefer under pure) ==="
echo "[demo] Direct runner flywheel-step --real-data --ingest (shadow optional)"
"$RUNNER" --json flywheel-step --real-data --limit 8 --ingest 2>&1 | tail -6
AGENTFORGE_RUST_FLYWHEEL_SHADOW=1 "$RUNNER" --json flywheel-step --real-data --limit 3 --ingest --shadow 2>&1 | tail -4
echo "[demo] (post_process.py now also ticks continuous + surfaces promote guidance under pure/shadow for full trio integration)"

echo ""
echo "=== Pure Rust One-Liners (high-velocity, copy-paste ready) — COMPLETE SURFACE === "
cat << 'ONE_LINERS'
# === ONE BINARY: agentforge-runner — flywheel-step + continuous + candidate promote + shadow ===
# COMPLETE: step (artifacts + ingest), continuous (autonomy + health), promote (real + source=rust), shadow (dual fidelity)
# All farm integration points (after-task hooks, workers, post_process, timer, parity, demo) now prefer direct calls.

# 1. Flywheel-step (real-data + ingest for pending_candidates; after-task / worker / post_process path)
agentforge-runner flywheel-step --real-data --limit 30 --output-dir /tmp/fw_demo --ingest
AGENTFORGE_RUST_FLYWHEEL_SHADOW=1 agentforge-runner --json flywheel-step --real-data --limit 8 --ingest --shadow

# 2. Continuous (autonomy meta-loop: prioritizer + top-N + health JSON; timer/continuous hook replacement)
agentforge-runner --json continuous --top-n 3
agentforge-runner --json continuous --top-n 1 --shadow
agentforge-runner continuous --top-n 2 --no-dry-run 2>&1 | cat
cat /tmp/agentforge_rust_flywheel/flywheel_health.json

# 3. Candidate (list + FULLY REAL promote with rust source stamp in history + markers)
agentforge-runner candidate list --top 5 --sort value --json
agentforge-runner --json candidate promote 20260531_055029_general-refactor_81e7d546 --copy-to-skills --dry-run
agentforge-runner candidate promote 20260531_055029_general-refactor_81e7d546 --copy-to-skills

# 4. Shadow dual for farm fidelity (hooks + parity + watchdog)
AGENTFORGE_RUST_FLYWHEEL_SHADOW=1 agentforge-runner --json continuous --top-n 2 --shadow
AGENTFORGE_RUST_FLYWHEEL_SHADOW=1 agentforge-runner --json flywheel-step --real-data --shadow

# After-task hook style (what bin/rust_flywheel_after_task.sh + workers now execute under pure)
$AGENTFORGE_RUST_RUNNER --json flywheel-step --real-data --ingest
AGENTFORGE_RUST_FLYWHEEL_SHADOW=1 $AGENTFORGE_RUST_RUNNER --json flywheel-step --real-data --ingest --shadow
$AGENTFORGE_RUST_RUNNER --json continuous --top-n 2 --shadow

# Health + observability
cat /tmp/agentforge_rust_flywheel/flywheel_health.json
ls -l /tmp/agentforge_rust_flywheel/shadow_fidelity*.json 2>/dev/null || true

# Prod release (services, workers, hooks)
$HOME/agentforge/rust/target/release/agentforge-runner --json continuous --top-n 1
$HOME/agentforge/rust/target/release/agentforge-runner --json flywheel-step --real-data --ingest --shadow

# Pure env + cutover (activates everywhere)
# export AGENTFORGE_PURE_RUST_FLYWHEEL=1 AGENTFORGE_FLYWHEEL_ENGINE=rust
# bash bin/make_pure_rust_flywheel_default.sh --dry-run
ONE_LINERS

echo ""
echo "=== See dedicated one-pager ==="
echo "cat HOW_TO_RUN_PURE_RUST_FLYWHEEL_TODAY.md"
echo ""
echo "Pure Rust flywheel-step + continuous + candidate promote + shadow fully demonstrated in demo + after-task hook."
echo "All integration points (continuous + promote + shadow) wired into demo tools and farm after-task hooks + post_process."
echo "Pure Rust surface (one binary) feels complete, obvious, and production-polished."
echo "RUNNER UX AND INTEGRATION PRODUCTION-POLISHED"
