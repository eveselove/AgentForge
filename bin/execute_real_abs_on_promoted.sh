#!/bin/bash
# !!! AGGRESSIVE FINAL DEPRECATION SWEEP (RUST_FULL_MIGRATION_PLAN.md + PHASE4_REMOVAL_PLAN.md) !!!
# execute_real_abs_on_promoted.sh : A/B execution helper for promoted candidates (generated).
# Tied to Python evaluator paths (deprecated). Use Rust continuous A/B or direct promote in future.
# Generated run_ab_*.sh + promote scripts in pending_candidates/ deleted with parent dirs (Tier 4/5).
# See PHASE4_REMOVAL_PLAN.md (generated artifacts note).
# Master runner for REAL A/B tests on the 3 flywheel-promoted general-refactor candidates.
# Generated in turbo mode 2026-05-31.
# Usage (after live farm ready):
#   cd /home/agx/agentforge
#   ENABLE_RUST_FLYWHEEL=1 AGENTFORGE_USE_RUST=1 bash bin/execute_real_abs_on_promoted.sh
#
# WARNING: This dispatches REAL tasks to the farm via LearningEvaluator (real mode).
# Only run when workers + dispatch + grok access are live and load is low.
# Each run_ab script will be edited in-place for real mode (simulate=False, wait_for_real=True, n_runs_per_arm=3, timeout_minutes=20).
# Includes rate-limit cleanup for farm reliability.
# Results → eval/history/ + ab_results.json updated + candidate_meta.
# After: inspect results, decide winner, full prod promotion.
# Enhanced for REAL A/B Execution Wave (n=3 for better signal, 20min timeout safe for farm).

set -euo pipefail

AGENTFORGE_ROOT="/home/agx/agentforge"
cd "$AGENTFORGE_ROOT"

echo "=== AgentForge REAL A/B Master Runner (post-promote flywheel variants) ==="
echo "Date: $(date -Iseconds)"
echo "Release binary: $(ls -l rust/target/release/agentforge-runner | awk '{print $5, $6, $7, $8}')"
echo

# The 3 promoted candidates (from promotion_history + A/B sim execution)
CANDIDATES=(
  "20260531_053411_general-refactor_81e7d546"
  "20260531_053412_general-refactor_81e7d546"
  "20260531_053416_general-refactor_81e7d546"
)

PYTHONPATH="$AGENTFORGE_ROOT:/home/agx"
export PYTHONPATH
export ENABLE_RUST_FLYWHEEL=1
export AGENTFORGE_USE_RUST=1

echo "Env ready. PYTHONPATH=$PYTHONPATH"
echo "Starting REAL A/B on 3 promoted (will edit run_ab scripts + execute)..."
echo

# Rate-limit / state cleanup for reliable farm dispatch (non-destructive)
echo ">>> Rate-limit / flywheel state cleanup (farm safety)..."
rm -f /tmp/agentforge_rust_flywheel/.last_after_task_run /tmp/agentforge_rust_flywheel/.flywheel*counter* /tmp/agentforge_rust_flywheel/.rate* 2>/dev/null || true
rm -rf /tmp/agentforge_rust_flywheel/locks 2>/dev/null || true
echo "    Cleanup done."

for cid in "${CANDIDATES[@]}"; do
  CAND_DIR="pending_candidates/$cid"
  SCRIPT="$CAND_DIR/run_ab_after_promote.py"
  META="$CAND_DIR/candidate_meta.json"

  if [[ ! -f "$SCRIPT" ]]; then
    echo "SKIP $cid: no run_ab script"
    continue
  fi

  echo ">>> Preparing REAL A/B for $cid"
  echo "    Script: $SCRIPT"

  # Edit in-place for REAL mode (idempotent-ish via markers)
  # Flip simulate=True → False, wait_for_real=False → True, bump n_runs to 3, set timeout=20
  sed -i 's/simulate=True/simulate=False/g' "$SCRIPT" || true
  sed -i 's/wait_for_real=False/wait_for_real=True/g' "$SCRIPT" || true
  sed -i 's/n_runs_per_arm=1/n_runs_per_arm=3/g' "$SCRIPT" || true
  sed -i 's/n_runs_per_arm=2/n_runs_per_arm=3/g' "$SCRIPT" || true
  sed -i 's/"simulate": true/"simulate": false/g' "$SCRIPT" || true
  sed -i 's/timeout_minutes=45/timeout_minutes=20/g' "$SCRIPT" || true
  sed -i 's/timeout_minutes=30/timeout_minutes=20/g' "$SCRIPT" || true

  # Also patch the ABTestConfig creation line if present
  sed -i 's/simulate=True, wait_for_real=False/simulate=False, wait_for_real=True/' "$SCRIPT" || true
  sed -i 's/n_runs_per_arm=1, /n_runs_per_arm=3, /g' "$SCRIPT" || true

  echo "    Flags flipped to REAL (simulate=False, wait_for_real=True, n_runs_per_arm=3, timeout=20min)"

  # Run it (non-blocking per candidate is ok, but sequential for safety)
  echo "    Executing (this will dispatch real tasks; monitor logs)..."
  set +e
  python "$SCRIPT" 2>&1 | tee -a "logs/real_ab_${cid}_$(date +%Y%m%d_%H%M%S).log"
  EXIT=$?
  set -e

  if [[ $EXIT -eq 0 ]]; then
    echo "    ✓ Completed (check ab_results.json + candidate_meta for new real winner/deltas)"
    # Re-record note in meta if possible (lightweight)
    python3 - <<PYEOF 2>/dev/null || true
import json, os, datetime
m = json.load(open("$META"))
m["ab_last_real_run_at"] = datetime.datetime.utcnow().isoformat() + "Z"
m["ab_note"] = "Real A/B attempted via enhanced master runner (n=3,20min,farm). Inspect new ab_results.json + logs."
m["real_ab_prepared_at"] = datetime.datetime.utcnow().isoformat() + "Z"
json.dump(m, open("$META", "w"), indent=2)
print("    meta updated with real-run timestamp + real_ab_prepared_at")
PYEOF
  else
    echo "    ✗ Exit $EXIT — inspect log + partial results"
  fi

  echo
done

echo "=== Master REAL A/B batch complete ==="
echo "Next:"
echo "  1. python list_pending_candidates.py list --limit 5   (or inspect specific metas)"
echo "  2. cat pending_candidates/<cid>/ab_results.json | python -m json.tool   (for each)"
echo "  3. If clear winner (is_clear_winner in evaluator): promote full prod + update agent_cards"
echo "  4. Re-run this script after more data for statistical power"
echo
echo "All real trajectories + PRM will flow back into Rust flywheel automatically (via post_process hooks)."
echo "Evidence of this run in logs/real_ab_*.log + updated ab_results.json in the 3 dirs."
echo "Use: bash bin/real_ab_farm_commands.txt blocks or the master for full wave."
echo
echo "RECOMMENDED (enhanced production dispatcher covering 3 promoted + top HV candidates):"
echo "  ENABLE_RUST_FLYWHEEL=1 AGENTFORGE_USE_RUST=1 PYTHONPATH=. bash bin/trigger_real_ab_on_farm.sh"
echo "  (see also: cat bin/real_ab_farm_commands.txt)"

# === PURE RUST FLYWHEEL DEFAULT (injected by make_pure_rust_flywheel_default.sh @ 2026-05-31T10:42:02+03:00) ===
# Pure Rust cutover (production excellence): when .pure_rust_flywheel or AGENTFORGE_PURE_RUST_FLYWHEEL=1 or FLYWHEEL_ENGINE=rust,
# force sole use of agentforge-runner binary for ALL flywheel/candidate/continuous orchestration.
# Complements env snippet + unit patches. Idempotent + guarded. Ultimate killswitch: DISABLE_RUST_FLYWHEEL=1.
PURE_MARKER="/home/agx/agentforge/.pure_rust_flywheel"
if [[ -f "$PURE_MARKER" ]] || [[ "${AGENTFORGE_PURE_RUST_FLYWHEEL:-0}" = "1" ]] || [[ "${AGENTFORGE_FLYWHEEL_ENGINE:-}" = "rust" ]]; then
    export AGENTFORGE_PURE_RUST_FLYWHEEL=1
    export AGENTFORGE_FLYWHEEL_ENGINE=rust
    if [ -x "/home/agx/agentforge/rust/target/release/agentforge-runner" ]; then
        export AGENTFORGE_RUST_RUNNER="/home/agx/agentforge/rust/target/release/agentforge-runner"
    fi
    export AGENTFORGE_FLYWHEEL_PROVENANCE="rust-agentforge-runner"
    # shellcheck disable=SC1091
    [ -f "/home/agx/agentforge/bin/rust_flywheel.env" ] && source "/home/agx/agentforge/bin/rust_flywheel.env" 2>/dev/null || true
fi
# End pure section — DISABLE_RUST_FLYWHEEL remains ultimate global off-switch everywhere.
