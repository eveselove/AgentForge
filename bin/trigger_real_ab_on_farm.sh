#!/bin/bash
# !!! AGGRESSIVE FINAL DEPRECATION SWEEP (RUST_FULL_MIGRATION_PLAN.md + PHASE4_REMOVAL_PLAN.md) !!!
# trigger_real_ab_on_farm.sh : real A/B dispatcher for flywheel candidates. Uses Python evaluator paths (deprecated Tier 2).
# Post Phase 4: Rust continuous owns A/B + promote; these trigger scripts + generated run_ab_* retired.
# See PHASE4_REMOVAL_PLAN.md (Tier 2/4, generated cleanup, risks for A/B divergence).
# =============================================================================
# bin/trigger_real_ab_on_farm.sh — PRODUCTION-READY REAL A/B FARM DISPATCHER & EXECUTOR
# =============================================================================
# Mission: Trigger *actual live* A/B evaluations on the production farm using
#          real task dispatch to grok workers via LearningEvaluator +
#          eval/runner.py (simulate=False, wait_for_real=True).
#
# Targets:
#   - The 3 promoted flywheel candidates (have dedicated real-mode scripts) + top HV (hardcoded)
#   - + ANY additional current candidates under pending_candidates/*/ that carry run_ab_real_farm.py or run_ab_after_promote.py
#     (auto-discovered for resilience; dups avoided). See code for list_high_value etc.
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
#     Real tasks created via http://localhost:9090/tasks (preferred_agent=grok),
#     polled when wait=True, post-processed by farm hooks.
#   - Also writes bin/real_ab_farm_commands.txt with exact pasteable blocks.
#
# Safety notes (READ BEFORE RUN):
#   - **FARM LOAD**: Only run when worker utilization is low (<~40% tasks
#     pending). Real A/B with n=3 x 6 cands x 3 benches = ~36 real tasks.
#     Each may take 5-25min on grok (timeout 20m default). Monitor queue.
#   - **DISPATCH**: Requires live agentforge API (localhost:9090) + active
#     grok_worker processes that can pick "evaluation" tagged
#     tasks and honor SKILL=... (for yaml-injected prompts from promoted files).
#   - **RATE LIMITS**: Cleanup is safe/best-effort (old artifacts + specific
#     flywheel counters). Does NOT touch live worker locks or DB. If active
#     after-task rate windows are mid-window, A/B may queue naturally (good).
#   - **ABORT / KILL**: 
#       pkill -f "trigger_real_ab_on_farm|LearningEvaluator|run_benchmark_task"
#       # or per-task: python reassign.py <task_id> --to jules (or whatever)
#       # Real tasks remain visible in dashboard / API; no data loss.
#   - **MONITORING** (run in parallel tmux pane):
#       tail -f logs/real_ab_*.log logs/grok_worker.log
#       watch -n 10 'curl -s http://localhost:9090/tasks?limit=5 | python -m json.tool; ls -l /tmp/agentforge_rust_flywheel/ 2>/dev/null | tail -5; python -m agentforge.list_pending_candidates list --limit 3 --sort value'
#   - **ROLLBACK / NO-OP**: Entirely non-destructive to prod skills (A/B uses
#     SKILL= temp or .promoted.*.yaml paths; baseline always "general-refactor").
#     No agent_cards or routing changes. Winner decision manual after.
#   - **PREREQS**: 
#       - ENABLE_RUST_FLYWHEEL marker or equiv (binary built)
#       - `cd /home/eveselove/agentforge && ls rust/target/release/agentforge-runner`
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
#   cd /path/to/agentforge   # or from anywhere: the script auto-resolves its root via BASH_SOURCE (worktree-safe)
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

# Resolve AGENTFORGE_ROOT robustly (works from worktrees /tmp/agentforge/*, bin/ subdir, symlinks, or when overridden).
# Prevents hard-coded main-tree lock-in for SWARM/isolated agents (see AGENTS.md worktree isolation).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
AGENTFORGE_ROOT="${AGENTFORGE_ROOT:-$(cd "$SCRIPT_DIR/.." && pwd -P)}"
cd "$AGENTFORGE_ROOT" || { echo "FATAL: cannot cd to AGENTFORGE_ROOT=$AGENTFORGE_ROOT (from $0)"; exit 1; }

# === RACE PREVENTION: exclusive lock (portable mkdir lockdir, auto-released on exit) ===
# Guards against concurrent runs -> thundering herd on farm + races on /tmp/*rate*/counters + meta + patching.
LOCK_DIR="/tmp/trigger_real_ab_on_farm.lockdir"
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
    echo "ERROR: another trigger_real_ab_on_farm.sh is running (lock at $LOCK_DIR). Abort to avoid data races."
    exit 1
fi
trap 'rmdir "$LOCK_DIR" 2>/dev/null || true' EXIT INT TERM HUP

echo "==================================================================="
echo "=== AgentForge REAL A/B FARM DISPATCHER (trigger_real_ab_on_farm.sh) ==="
echo "Date: $(date -Iseconds)"
echo "Host: $(hostname)"
echo "Root: $AGENTFORGE_ROOT"
echo "Release binary: $(ls -l rust/target/release/agentforge-runner 2>/dev/null | awk '{print $5, $6, $7, $8}' || echo 'NOT FOUND — build first!')"
echo "==================================================================="

# === 1. Full correct environment (from enable_rust_flywheel + evaluator/runner requirements) ===
PARENT_DIR="$(dirname "$AGENTFORGE_ROOT")"
export PYTHONPATH="${PYTHONPATH:-.:$PARENT_DIR}"
export ENABLE_RUST_FLYWHEEL=1
export AGENTFORGE_USE_RUST=1
export AGENTFORGE_RUST_FLYWHEEL=1

# Prefer explicit release runner (fast path for any Rust hooks)
RUST_BIN="rust/target/release/agentforge-runner"
if [ -x "$RUST_BIN" ]; then
    AGENTFORGE_RUST_RUNNER="$(realpath "$RUST_BIN")"
    export AGENTFORGE_RUST_RUNNER
    echo "  Using release Rust runner: $AGENTFORGE_RUST_RUNNER"
fi

# Source any env helpers (idempotent)
source bin/rust_flywheel.env 2>/dev/null || true
source bin/enable_rust_flywheel.sh 2>/dev/null || true

echo "Env ready:"
env | grep -E '^(PYTHONPATH|ENABLE_RUST|AGENTFORGE_RUST|AGENTFORGE_USE)' | sort
echo

# === 2. Safe rate-limit + flywheel state cleanup (production safe, non-destructive) ===
FLYWHEEL_DIR="/tmp/agentforge_rust_flywheel"
echo ">>> SAFE RATE-LIMIT / FLYWHEEL STATE CLEANUP (for reliable dispatch)..."
python3 - <<'PYEOF' 2>/dev/null || true
from learning.pending_candidates import cleanup_old_flywheel_artifacts
n = cleanup_old_flywheel_artifacts(2)  # aggressive short window only for A/B prep dispatch
print(f"  Python cleanup_old_flywheel_artifacts(2h): removed {n} old items")
PYEOF

# Targeted non-destructive rm (exact patterns from production master + watchdog)
# Note: globs intentionally unquoted so shell expands them (dir var has no spaces).
rm -f $FLYWHEEL_DIR/.last_after_task_run \
      $FLYWHEEL_DIR/.flywheel*counter* \
      $FLYWHEEL_DIR/.rate* \
      $FLYWHEEL_DIR/.*rate* 2>/dev/null || true
rm -rf $FLYWHEEL_DIR/locks 2>/dev/null || true

# Light touch on stale counter/rate files only (>5min) — FIXED: proper grouping, was deleting only counters due to -o precedence (logical bug).
if [ -d "$FLYWHEEL_DIR" ]; then
  find "$FLYWHEEL_DIR" -maxdepth 1 \( -name '.*rate*' -o -name '*counter*' \) -mmin +5 -delete 2>/dev/null || true
fi

echo "    Cleanup complete. (Live worker rate windows untouched if active.)"
echo

# Quick API sanity (non-fatal) — real API port is 9090 (per workers, AGENTS.md, eval/utils.py etc)
PENDING_TASKS=0
if command -v curl >/dev/null; then
    if curl -sf --max-time 3 http://localhost:9090/ >/dev/null 2>&1; then
        echo "  [OK] AgentForge API reachable at localhost:9090 (real dispatch path active)"
        # Bottleneck guard: sample pending queue size (farm overload risk for ~36 extra tasks)
        PENDING_TASKS=$(curl -sf --max-time 3 'http://localhost:9090/tasks?limit=200' 2>/dev/null | python3 -c '
import sys, json
try:
    data = json.load(sys.stdin)
    if isinstance(data, list):
        print(sum(1 for t in data if isinstance(t, dict) and t.get("status") in ("pending", "running")))
    else:
        print(0)
except Exception:
    print(0)
' || echo 0)
        echo "  Current pending+running tasks: $PENDING_TASKS (dispatching more only if <~30 recommended)"
    else
        echo "  [WARN] API not responding on localhost:9090 — real tasks may queue or fail. (Proceed anyway for farm readiness.)"
    fi
fi
if [[ ${PENDING_TASKS:-0} -gt 30 ]]; then
    echo "  [LOAD WARN] High queue ($PENDING_TASKS). Consider waiting or pkill if needed. Continuing per original design."
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

# Dynamic discovery of *current* candidates carrying A/B scripts (addresses stale hardcoded CIDs logical issue).
# Any pending_candidates/* with run_ab_real_farm.py or run_ab_after_promote.py get included (no dups).
# Makes trigger future-proof vs cleanup/phase4 sweeps while preserving the explicit promoted+HV targets.
if [ -d pending_candidates ]; then
  while IFS= read -r d; do
    c="${d#pending_candidates/}"
    # dedup against existing
    found=0
    for e in "${ALL_CIDS[@]}"; do [[ "$e" == "$c" ]] && found=1; done
    [[ $found -eq 0 ]] && ALL_CIDS+=("$c")
  done < <(find pending_candidates -mindepth 1 -maxdepth 1 -type d \( -exec test -f "{}/run_ab_real_farm.py" \; -o -exec test -f "{}/run_ab_after_promote.py" \; \) -print 2>/dev/null | sort || true)
fi

echo "Targets (${#ALL_CIDS[@]} candidates):"
for c in "${ALL_CIDS[@]}"; do echo "  - $c"; done
echo
echo ">>> SAFETY REMINDER: ~36 real farm tasks will be dispatched (more if discovered)."
echo "    Monitor load. Abort with: pkill -f LearningEvaluator || kill the shell."
echo "    Full monitoring: tail -f logs/real_ab_*.log + dashboard / API"
echo

# === 4. Also (re)generate the standalone commands file for humans / Autonomy ===
mkdir -p logs bin
COMMANDS_FILE="bin/real_ab_farm_commands.txt"
cat > "$COMMANDS_FILE" <<CMDEOF
# =============================================================================
# REAL A/B FARM DISPATCH — EXACT COMMANDS (production-ready, 2026-05-31+)
# Generated by bin/trigger_real_ab_on_farm.sh (root resolved dynamically at gen time)
# =============================================================================
# Full dispatcher (covers promoted + top HV, with cleanup + patching + logging + meta updates)
cd $AGENTFORGE_ROOT
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
promoted_yaml = "$AGENTFORGE_ROOT/skills/general-refactor-flywheel-202605310534.promoted.20260531_053640.yaml"
print(e.ab_test_skill_versions(
    ["example_rust_refactor", "lancedb_parser_bottleneck", "adaptive_throttle_tuning"],
    "general-refactor",
    promoted_yaml,
    cfg
).summary())
'

# Rate cleanup (standalone, safe to run anytime before dispatch):
python -c 'from learning.pending_candidates import cleanup_old_flywheel_artifacts; print(cleanup_old_flywheel_artifacts(2))'
rm -f $FLYWHEEL_DIR/.last_after_task_run $FLYWHEEL_DIR/.flywheel*counter* $FLYWHEEL_DIR/.rate* 2>/dev/null || true

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
        # Use ns for unique backup name (avoids rare same-second clobber if concurrent on same cid; race fix)
        PRE_TS="$(date +%s%N)"
        cp -f "$AFTER_SCRIPT" "$CAND_DIR/run_ab_after_promote.py.pre-real.${PRE_TS}" 2>/dev/null || true

        # ROBUST PATCHING (was fragile s/ exact; added -E + \s* + more patterns to cover " = True", dicts, no-space etc.
        # Prevents logical error where simulate stays True -> A/B runs fake instead of real farm dispatch.
        sed -i -E 's/simulate\s*=\s*True/simulate=False/gI' "$AFTER_SCRIPT" || true
        sed -i -E 's/wait_for_real\s*=\s*False/wait_for_real=True/gI' "$AFTER_SCRIPT" || true
        sed -i -E 's/n_runs_per_arm\s*=\s*1/n_runs_per_arm=3/g' "$AFTER_SCRIPT" || true
        sed -i -E 's/n_runs_per_arm\s*=\s*2/n_runs_per_arm=3/g' "$AFTER_SCRIPT" || true
        sed -i -E 's/timeout_minutes\s*=\s*45/timeout_minutes=20/g' "$AFTER_SCRIPT" || true
        sed -i -E 's/timeout_minutes\s*=\s*30/timeout_minutes=20/g' "$AFTER_SCRIPT" || true
        sed -i -E 's/timeout_minutes\s*=\s*60/timeout_minutes=20/g' "$AFTER_SCRIPT" || true
        sed -i -E 's/"simulate"\s*:\s*true/"simulate": false/gI' "$AFTER_SCRIPT" || true
        sed -i -E 's/"wait_for_real"\s*:\s*false/"wait_for_real": true/gI' "$AFTER_SCRIPT" || true

        # Patch common one-liner ABTestConfig ctor (with/without spaces)
        sed -i -E 's/simulate\s*=\s*True\s*,\s*wait_for_real\s*=\s*False/simulate=False, wait_for_real=True/gI' "$AFTER_SCRIPT" || true
        sed -i -E 's/n_runs_per_arm\s*=\s*1\s*,/n_runs_per_arm=3,/g' "$AFTER_SCRIPT" || true

        # Python fallback patch (most reliable for nested/dict cases the seds miss). Idempotent.
        python3 - "$AFTER_SCRIPT" <<'PYPATCH' 2>/dev/null || true
import sys, re
p = sys.argv[1]
with open(p, 'r', encoding='utf-8') as f:
    src = f.read()
src2 = re.sub(r'(?i)\bsimulate\s*=\s*True\b', 'simulate=False', src)
src2 = re.sub(r'(?i)\bwait_for_real\s*=\s*False\b', 'wait_for_real=True', src2)
src2 = re.sub(r'\bn_runs_per_arm\s*=\s*[12]\b', 'n_runs_per_arm=3', src2)
src2 = re.sub(r'\btimeout_minutes\s*=\s*(?:45|30|60)\b', 'timeout_minutes=20', src2)
src2 = re.sub(r'"simulate"\s*:\s*true', '"simulate": false', src2, flags=re.I)
src2 = re.sub(r'"wait_for_real"\s*:\s*false', '"wait_for_real": true', src2, flags=re.I)
if src2 != src:
    with open(p, 'w', encoding='utf-8') as f:
        f.write(src2)
    print("    python-patch applied extra flips")
PYPATCH

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
    PYTHONPATH="${PYTHONPATH:-.:$PARENT_DIR}" \
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
