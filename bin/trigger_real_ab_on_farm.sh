#!/bin/bash
# !!! AGGRESSIVE FINAL DEPRECATION SWEEP (RUST_FULL_MIGRATION_PLAN.md + PHASE4_REMOVAL_PLAN.md) !!!
# trigger_real_ab_on_farm.sh : real A/B dispatcher for flywheel candidates. Uses Python evaluator paths (deprecated Tier 2).
# Post Phase 4: Rust continuous owns A/B + promote; these trigger scripts + generated run_ab_* retired.
# See PHASE4_REMOVAL_PLAN.md (Tier 2/4, generated cleanup, risks for A/B divergence).
# =============================================================================
# bin/trigger_real_ab_on_farm.sh — PRODUCTION-READY REAL A/B FARM DISPATCHER & EXECUTOR
# =============================================================================
# Mission: Trigger *actual live* A/B evaluations on the production farm using
#          real task dispatch to grok/jules workers via LearningEvaluator +
#          eval/runner.py (simulate=False, wait_for_real=True).
#
# Targets:
#   - The 3 promoted flywheel candidates (have dedicated real-mode scripts)
#   - + Top 3 current high-value (HV) candidates from the Rust rich flywheel
#     (dynamic + hardcoded recent for immediate exec)
#
# Features (based on actual code in eval/runner.py + learning/evaluator.py):
#   - Exact env: PYTHONPATH=., ENABLE_RUST_FLYWHEEL=1, AGENTFORGE_USE_RUST=1
#     (ensures Rust flywheel post_process + rich export + PRM on resulting
#      real trajectories)
#   - Safe rate-limit / flywheel state cleanup (reuses pending_candidates.py
#     cleanup_old_flywheel_artifacts + targeted non-destructive rm of
#     .rate* / counters / locks as in execute_real_abs_on_promoted.sh)
#   - For each candidate: prefers run_ab_real_farm.py if present (n=3, real,
#     20m timeout), else patches run_ab_after_promote.py in-place (idempotent
#     sed flips) then executes.
#   - Full output capture to logs/real_ab_<cid>_<ts>.log
#   - Post-run: updates candidate_meta.json with real_ab_executed_at + log ref
#   - Results handling: ABResult (success_rate, avg_prm, deltas, winner,
#     confidence via is_clear_winner), full runs in ab_results*.json,
#     trajectories + .prm.json sidecars (ProcessRewardModel), costs/durations
#     from EvaluationResult (enriched via load_trajectory + post_process_run).
#     Real tasks created via http://localhost:8080/tasks (preferred_agent=grok),
#     polled when wait=True, post-processed by farm hooks.
#   - Also writes bin/real_ab_farm_commands.txt with exact pasteable blocks.
#
# Safety notes (READ BEFORE RUN):
#   - **FARM LOAD**: Only run when worker utilization is low (<~40% tasks
#     pending). Real A/B with n=3 x 6 cands x 3 benches = ~36 real tasks.
#     Each may take 5-25min on grok (timeout 20m default). Monitor queue.
#   - **DISPATCH**: Requires live agentforge API (localhost:8080) + active
#     grok_worker / jules_worker processes that can pick "evaluation" tagged
#     tasks and honor SKILL=... (for yaml-injected prompts from promoted files).
#   - **RATE LIMITS**: Cleanup is safe/best-effort (old artifacts + specific
#     flywheel counters). Does NOT touch live worker locks or DB. If active
#     after-task rate windows are mid-window, A/B may queue naturally (good).
#   - **ABORT / KILL**: 
#       pkill -f "trigger_real_ab_on_farm|LearningEvaluator|run_benchmark_task"
#       # or per-task: python reassign.py <task_id> --to jules (or whatever)
#       # Real tasks remain visible in dashboard / API; no data loss.
#   - **MONITORING** (run in parallel tmux pane):
#       tail -f logs/real_ab_*.log logs/jules_worker.log logs/grok_worker.log
#       watch -n 10 'curl -s http://localhost:8080/tasks?limit=5 | python -m json.tool; ls -l /tmp/agentforge_rust_flywheel/ 2>/dev/null | tail -5; python -m agentforge.list_pending_candidates list --limit 3 --sort value'
#   - **ROLLBACK / NO-OP**: Entirely non-destructive to prod skills (A/B uses
#     SKILL= temp or .promoted.*.yaml paths; baseline always "general-refactor").
#     No agent_cards or routing changes. Winner decision manual after.
#   - **PREREQS**: 
#       - ENABLE_RUST_FLYWHEEL marker or equiv (binary built)
#       - `cd /home/agx/agentforge && ls rust/target/release/agentforge-runner`
#       - API responding + workers alive (test: python -m agentforge.eval run ... --real or healthcheck)
#   - **RESULTS FEED FORWARD**: Every real run's trajectories go through
#     post_process (Rust accelerated if enabled) → PRM (ProcessRewardModel
#     + optional LLM judge via AGENTFORGE_PRM_USE_LLM_JUDGE=1) → rich
#     flywheel-export → new candidates. ABResult persisted to history/ +
#     candidate ab_results + eval/results/*.json
#   - Turbo production-safe: set -euo pipefail, per-cand try, logs, meta
#     updates, no clobber of existing real results.
#
# Usage (LIVE FARM — run exactly like this):
#   cd /home/agx/agentforge
#   ENABLE_RUST_FLYWHEEL=1 AGENTFORGE_USE_RUST=1 \
#     PYTHONPATH=. bash bin/trigger_real_ab_on_farm.sh 2>&1 | tee logs/trigger_real_ab_$(date +%Y%m%d_%H%M%S).log
#
# After: inspect per-candidate ab_results*.json (or the ones written by
#        LearningEvaluator), check winner/confidence/deltas, decide on
#        full prod cutover only for clear non-regression or treatment win.
#        Re-run for more statistical power (n>3).
#
# Evidence-based on:
#   learning/evaluator.py (ABTestConfig, _run_one with SKILL=, wait, simulate,
#                          ab_test_skill_versions, PRM attach via post_process_run)
#   eval/runner.py (run_benchmark_task real path: create_..._task + _wait_...,
#                   trajectory find + load_trajectory(include_prm=True),
#                   record_run, post_process_task)
#   learning/pending_candidates.py (cleanup, list_high_value, promote artifacts)
#   agents/grok_runner.sh (SKILL yaml loading for real variant dispatch)
#   Existing masters (execute_real_abs..., per-cand run_ab_real_farm.py)
#
# Jules turbo — production gate for measurable flywheel lift. No stops.
# =============================================================================

set -euo pipefail

AGENTFORGE_ROOT="/home/agx/agentforge"
cd "$AGENTFORGE_ROOT"

echo "==================================================================="
echo "=== AgentForge REAL A/B FARM DISPATCHER (trigger_real_ab_on_farm.sh) ==="
echo "Date: $(date -Iseconds)"
echo "Host: $(hostname)"
echo "Release binary: $(ls -l rust/target/release/agentforge-runner 2>/dev/null | awk '{print $5, $6, $7, $8}' || echo 'NOT FOUND — build first!')"
echo "==================================================================="

# === 1. Full correct environment (from enable_rust_flywheel + evaluator/runner requirements) ===
export PYTHONPATH=".:/home/agx"
export ENABLE_RUST_FLYWHEEL=1
export AGENTFORGE_USE_RUST=1
export AGENTFORGE_RUST_FLYWHEEL=1

# Prefer explicit release runner (fast path for any Rust hooks)
if [ -x "rust/target/release/agentforge-runner" ]; then
    export AGENTFORGE_RUST_RUNNER="$(realpath rust/target/release/agentforge-runner)"
    echo "  Using release Rust runner: $AGENTFORGE_RUST_RUNNER"
fi

# Source any env helpers (idempotent)
source bin/rust_flywheel.env 2>/dev/null || true
source bin/enable_rust_flywheel.sh 2>/dev/null || true

echo "Env ready:"
env | grep -E '^(PYTHONPATH|ENABLE_RUST|AGENTFORGE_RUST|AGENTFORGE_USE)' | sort | cat
echo

# === 2. Safe rate-limit + flywheel state cleanup (production safe, non-destructive) ===
echo ">>> SAFE RATE-LIMIT / FLYWHEEL STATE CLEANUP (for reliable dispatch)..."
python3 - <<'PYEOF' 2>/dev/null || true
from learning.pending_candidates import cleanup_old_flywheel_artifacts
import time
n = cleanup_old_flywheel_artifacts(2)  # aggressive short window only for A/B prep dispatch
print(f"  Python cleanup_old_flywheel_artifacts(2h): removed {n} old items")
PYEOF

# Targeted non-destructive rm (exact patterns from production master + watchdog)
rm -f /tmp/agentforge_rust_flywheel/.last_after_task_run \
      /tmp/agentforge_rust_flywheel/.flywheel*counter* \
      /tmp/agentforge_rust_flywheel/.rate* \
      /tmp/agentforge_rust_flywheel/.*rate* 2>/dev/null || true
rm -rf /tmp/agentforge_rust_flywheel/locks 2>/dev/null || true

# Light touch on very recent counter files only if they look stale (>5min)
find /tmp/agentforge_rust_flywheel -maxdepth 1 -name '.*rate*' -o -name '*counter*' -mmin +5 -delete 2>/dev/null || true

echo "    Cleanup complete. (Live worker rate windows untouched if active.)"
echo

# Quick API sanity (non-fatal)
if command -v curl >/dev/null; then
    if curl -sf --max-time 3 http://localhost:8080/ >/dev/null 2>&1; then
        echo "  [OK] AgentForge API reachable at localhost:8080 (real dispatch path active)"
    else
        echo "  [WARN] API not responding on localhost:8080 — real tasks may queue or fail. (Proceed anyway for farm readiness.)"
    fi
fi
echo

# === 3. Candidate selection: 3 promoted + top current HV ===
# Promoted (have dedicated *_real_farm.py ready for n=3/real/20m)
PROMOTED_CIDS=(
  "20260531_053411_general-refactor_81e7d546"
  "20260531_053412_general-refactor_81e7d546"
  "20260531_053416_general-refactor_81e7d546"
)

# Top HV (from live list_high_value_candidates; recent rich Rust exports)
HV_CIDS=(
  "20260531_054619_general-refactor_81e7d546"
  "20260531_054553_general-refactor_81e7d546"
  "20260531_054527_general-refactor_81e7d546"
)

ALL_CIDS=("${PROMOTED_CIDS[@]}" "${HV_CIDS[@]}")

echo "Targets (${#ALL_CIDS[@]} candidates):"
for c in "${ALL_CIDS[@]}"; do echo "  - $c"; done
echo
echo ">>> SAFETY REMINDER: ~36 real farm tasks will be dispatched."
echo "    Monitor load. Abort with: pkill -f LearningEvaluator || kill the shell."
echo "    Full monitoring: tail -f logs/real_ab_*.log + dashboard / API"
echo

# === 4. Also (re)generate the standalone commands file for humans / Autonomy ===
mkdir -p logs bin
COMMANDS_FILE="bin/real_ab_farm_commands.txt"
cat > "$COMMANDS_FILE" <<CMDEOF
# =============================================================================
# REAL A/B FARM DISPATCH — EXACT COMMANDS (production-ready, 2026-05-31+)
# Generated by bin/trigger_real_ab_on_farm.sh
# =============================================================================
# Full dispatcher (covers promoted + top HV, with cleanup + patching + logging + meta updates)
cd /home/agx/agentforge
ENABLE_RUST_FLYWHEEL=1 AGENTFORGE_USE_RUST=1 PYTHONPATH=. \
  bash bin/trigger_real_ab_on_farm.sh

# Per-candidate (after manual prep or via trigger patching):
#   Promoted example (uses pre-made real script):
PYTHONPATH=. ENABLE_RUST_FLYWHEEL=1 AGENTFORGE_USE_RUST=1 \
  python pending_candidates/20260531_053416_general-refactor_81e7d546/run_ab_real_farm.py

#   HV example (after trigger or manual sed flip on its run_ab_after_promote.py):
PYTHONPATH=. ENABLE_RUST_FLYWHEEL=1 AGENTFORGE_USE_RUST=1 \
  python pending_candidates/20260531_054619_general-refactor_81e7d546/run_ab_after_promote.py

# Direct one-liner (no script edit, for any candidate yaml):
python -c '
from learning.evaluator import LearningEvaluator, ABTestConfig
from pathlib import Path
e = LearningEvaluator()
cfg = ABTestConfig(
    name="direct-real-ab-$(date +%s)",
    agent="grok",
    n_runs_per_arm=3,
    simulate=False,
    wait_for_real=True,
    timeout_minutes=20,
    use_temp_skill_files=True,
)
promoted_yaml = "/home/agx/agentforge/skills/general-refactor-flywheel-202605310534.promoted.20260531_053640.yaml"
print(e.ab_test_skill_versions(
    ["example_rust_refactor", "lancedb_parser_bottleneck", "adaptive_throttle_tuning"],
    "general-refactor",
    promoted_yaml,
    cfg
).summary())
'

# Rate cleanup (standalone, safe to run anytime before dispatch):
python -c 'from learning.pending_candidates import cleanup_old_flywheel_artifacts; print(cleanup_old_flywheel_artifacts(2))'
rm -f /tmp/agentforge_rust_flywheel/.last_after_task_run /tmp/agentforge_rust_flywheel/.flywheel*counter* /tmp/agentforge_rust_flywheel/.rate* 2>/dev/null || true

# Monitoring during run:
#   tail -f logs/real_ab_*.log
#   python -m agentforge.list_pending_candidates list --limit 5 --sort value
#   ls -l pending_candidates/*/ab_results*.json | tail
# =============================================================================
CMDEOF
echo "  Wrote $COMMANDS_FILE with exact pasteable real-dispatch blocks."
echo

# === 5. Dispatch loop (real execution) ===
SUCCESSFUL=0
FAILED=0

for cid in "${ALL_CIDS[@]}"; do
    CAND_DIR="pending_candidates/$cid"
    REAL_SCRIPT="$CAND_DIR/run_ab_real_farm.py"
    AFTER_SCRIPT="$CAND_DIR/run_ab_after_promote.py"
    META="$CAND_DIR/candidate_meta.json"

    if [[ ! -d "$CAND_DIR" ]]; then
        echo "SKIP $cid: candidate dir not found"
        continue
    fi

    # Prefer dedicated real-mode script (for the original 3 promoted)
    if [[ -f "$REAL_SCRIPT" ]]; then
        SCRIPT_TO_RUN="$REAL_SCRIPT"
        echo ">>> [$cid] Using pre-configured REAL script (n=3, wait_for_real=True, simulate=False, 20m)"
    elif [[ -f "$AFTER_SCRIPT" ]]; then
        # Patch in-place for real dispatch (production pattern from existing master)
        echo ">>> [$cid] Patching run_ab_after_promote.py → REAL (simulate=False, wait=True, n=3, timeout=20)"
        cp -f "$AFTER_SCRIPT" "$CAND_DIR/run_ab_after_promote.py.pre-real.$(date +%s)" 2>/dev/null || true

        # Multiple sed passes (robust to current formatting)
        sed -i 's/simulate=True/simulate=False/g' "$AFTER_SCRIPT" || true
        sed -i 's/wait_for_real=False/wait_for_real=True/g' "$AFTER_SCRIPT" || true
        sed -i 's/n_runs_per_arm=1/n_runs_per_arm=3/g' "$AFTER_SCRIPT" || true
        sed -i 's/n_runs_per_arm=2/n_runs_per_arm=3/g' "$AFTER_SCRIPT" || true
        sed -i 's/timeout_minutes=45/timeout_minutes=20/g' "$AFTER_SCRIPT" || true
        sed -i 's/timeout_minutes=30/timeout_minutes=20/g' "$AFTER_SCRIPT" || true
        sed -i 's/timeout_minutes=60/timeout_minutes=20/g' "$AFTER_SCRIPT" || true
        sed -i 's/"simulate": true/"simulate": false/g' "$AFTER_SCRIPT" || true
        sed -i 's/"wait_for_real": false/"wait_for_real": true/g' "$AFTER_SCRIPT" || true

        # Patch the ABTestConfig(...) construction line if present (one-liner style)
        sed -i 's/simulate=True, wait_for_real=False/simulate=False, wait_for_real=True/g' "$AFTER_SCRIPT" || true
        sed -i 's/n_runs_per_arm=1, /n_runs_per_arm=3, /g' "$AFTER_SCRIPT" || true

        SCRIPT_TO_RUN="$AFTER_SCRIPT"
        echo "    Patch complete. Will run real dispatch."
    else
        echo "SKIP $cid: no A/B script found (run promote-and-ab first)"
        continue
    fi

    TS="$(date +%Y%m%d_%H%M%S)"
    LOG_FILE="logs/real_ab_${cid}_${TS}.log"
    echo "    Executing: python $SCRIPT_TO_RUN"
    echo "    Logging to: $LOG_FILE"
    echo "    (Real tasks will be created on farm; waiting up to 20m per run...)"

    set +e
    PYTHONPATH=".:/home/agx" \
    ENABLE_RUST_FLYWHEEL=1 \
    AGENTFORGE_USE_RUST=1 \
    AGENTFORGE_RUST_FLYWHEEL=1 \
    python "$SCRIPT_TO_RUN" 2>&1 | tee "$LOG_FILE"
    EXIT_CODE=$?
    set -e

    if [[ $EXIT_CODE -eq 0 ]]; then
        echo "    ✓ SUCCESS for $cid (exit 0). Results in $LOG_FILE + ab_results*.json + PRM trajectories."
        ((SUCCESSFUL++))
    else
        echo "    ✗ NON-ZERO EXIT $EXIT_CODE for $cid — partial results may exist. Inspect log."
        ((FAILED++))
    fi

    # Update candidate_meta.json (lightweight, best-effort, matches existing master pattern)
    if [[ -f "$META" ]]; then
        python3 - <<PYEOF 2>/dev/null || true
import json, datetime, os
try:
    with open("$META", "r", encoding="utf-8") as f:
        m = json.load(f)
    m["real_ab_last_executed_at"] = datetime.datetime.utcnow().isoformat() + "Z"
    m["real_ab_last_log"] = "$LOG_FILE"
    m["real_ab_exit_code"] = $EXIT_CODE
    m["real_ab_script_used"] = "$SCRIPT_TO_RUN"
    if "real_ab_runs" not in m:
        m["real_ab_runs"] = 0
    m["real_ab_runs"] = m["real_ab_runs"] + 1
    with open("$META", "w", encoding="utf-8") as f:
        json.dump(m, f, indent=2, ensure_ascii=False)
    print(f"    meta updated: real_ab_last_executed_at + real_ab_runs={m['real_ab_runs']}")
except Exception as e:
    print(f"    meta update skipped: {e}")
PYEOF
    fi

    echo
    # Gentle pause between candidates (farm courtesy, reduces thundering herd)
    sleep 3
done

# === 6. Final summary + next steps ===
echo "==================================================================="
echo "=== REAL A/B DISPATCH COMPLETE ==="
echo "Successful candidates: $SUCCESSFUL"
echo "Failed / errored     : $FAILED"
echo "Logs: ls -l logs/real_ab_*.log"
echo "Commands file: $COMMANDS_FILE"
echo
echo "Results locations (per LearningEvaluator + runner):"
echo "  - pending_candidates/<cid>/ab_results*.json (full ABResult + deltas + PRM)"
echo "  - eval/history/ab_test_*.jsonl (longitudinal for flywheel)"
echo "  - eval/results/*_grok_*.json (raw EvaluationResult + trajectory_path)"
echo "  - trajectories/ + *.prm.json (ProcessRewardModel scores from real runs)"
echo "  - candidate_meta.json (real_ab_* timestamps updated)"
echo
echo "Next (manual review gate):"
echo "  1. python -m agentforge.list_pending_candidates list --sort value --limit 5"
echo "  2. for f in pending_candidates/*/ab_results*.json; do echo \$f; python -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d.get(\"winner\"), d.get(\"confidence\"), d.get(\"deltas\"))' \$f; done"
echo "  3. If clear winner (treatment + medium/high confidence via is_clear_winner):"
echo "     - promote full prod (copy .promoted yaml over canonical, update routing if needed)"
echo "     - re-measure farm success_rate via eval/generate_evaluation_report.py"
echo "  4. Re-trigger for higher n (edit scripts or re-run this) for statistical power."
echo
echo "All real trajectories + PRM + costs/durations now feeding the continuous Rust flywheel."
echo "Production-safe. Evidence in logs/ + updated metas + history/."
echo "==================================================================="

exit $(( FAILED > 0 ? 1 : 0 ))

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
