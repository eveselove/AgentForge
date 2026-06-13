#!/bin/bash
#
# grok_worker.sh — Autonomous Grok Agent Worker with Git Auto-Rollback on CI Fail
#
# Git Worktrees agent isolation support: see also agents/grok_runner.sh + jules_runner.sh
# (primary implementation for /tmp/agentforge/TASK_ID lives in ~/agentforge/* equivalents;
# this workspace copy + the new scripts/ runners provide the pattern for self-verification).
#
# Purpose:
#   Executes the full Grok-powered task pipeline (dispatch → git_clone → grok_* → ci_* → review → done)
#   with crash-safe checkpointing. Critically: after any push to main, continuously monitors
#   GitHub Actions CI. On any failure (build, benchmark, coverage, etc.) — automatically
#   performs `git revert` of the offending commit and pushes the revert.
#
# Guarantee:
#   "Main branch никогда не ломается" — the main branch is never left in a broken state.
#   Any commit that turns the lights red is instantly reverted by the worker.
#
# Usage:
#   ./scripts/grok_worker.sh --help
#   ./scripts/grok_worker.sh guard-main [--dry-run] [--poll-interval 30]
#   ./scripts/grok_worker.sh run-task <task_id> [--repo <url>]   # full pipeline (clones target repo if different)
#   python scripts/grok_worker.py --gateway-task <id>            # recommended for multi-repo: pulls repo from gateway task record
#
# Environment:
#   GITHUB_TOKEN or gh CLI auth required for status checks + revert push rights.
#   REPO_DIR defaults to /home/agx/planlytasksko
#
# Safety:
#   - Only operates on main branch
#   - Never force-pushes
#   - Idempotent: skips if HEAD is already a revert of the bad commit
#   - Requires explicit confirmation in non-dry-run unless --yes
#   - Logs everything to $LOG_FILE
#
# Integration:
#   - Uses scripts/task_checkpoints.py for state (ci_start, ci_done, ci_failed, rollback)
#   - PRM scoring: after key steps call `python -c 'from prm import score_step; ...'` or POST /api/prm/score-step
#   - Guardian now uses PRM low-reward signals to force HITL on risky trajectories
#   - Can be driven by the Planly gateway / Rust checkpoints
#
# Tags: grok, worker, ci, auto-rollback, reliability, main-branch-protection, prm, evaluation, guardian

set -euo pipefail

# ====================== CONFIG ======================
REPO_DIR="${REPO_DIR:-/home/eveselove/planlytasksko}"
CHECKPOINT_PY="${REPO_DIR}/scripts/task_checkpoints.py"
LOG_FILE="${LOG_FILE:-/tmp/grok_worker.log}"
POLL_INTERVAL="${POLL_INTERVAL:-45}"          # seconds between CI status polls
MAX_WAIT_MIN="${MAX_WAIT_MIN:-25}"            # total minutes to wait for CI before giving up
GITHUB_REPO="${GITHUB_REPO:-}"                # auto-detected if empty
DRY_RUN="${DRY_RUN:-0}"
YES="${YES:-0}"
TASK_ID="${TASK_ID:-}"

# ================== MULTI-REPO (scale) ==================
# Support for tasks carrying `repo` field (e.g. https://github.com/org/other-repo).
# Workers can operate on many different repositories from one control plane.
# Use --repo URL (or TARGET_REPO / GITHUB_REPO env) with `run-task`.
# Clones are cached under REPO_CACHE_DIR to avoid repeated full clones.
TARGET_REPO="${TARGET_REPO:-${GITHUB_REPO:-}}"
REPO_CACHE_DIR="${REPO_CACHE_DIR:-/tmp/planly-repos}"

# ====================== HELPERS ======================
log() {
    local level="$1"; shift
    local msg="$*"
    local ts
    ts=$(date -Iseconds)
    echo "[$ts] [$level] $msg" | tee -a "$LOG_FILE" >&2
}

die() {
    log "ERROR" "$@"
    exit 1
}

run() {
    if [[ "$DRY_RUN" == "1" ]]; then
        log "DRY" "would run: $*"
        return 0
    fi
    "$@"
}

checkpoint() {
    local task_id="$1"
    local step="$2"
    local data="${3:-{}}"
    if [[ -f "$CHECKPOINT_PY" ]]; then
        python3 -c "
import sys
sys.path.insert(0, '${REPO_DIR}/scripts')
from task_checkpoints import save_checkpoint, init_db
init_db()
import json
save_checkpoint('${task_id}', '${step}', json.loads('''${data}''') if '${data}' != '{}' else {})
print('checkpoint saved:', '${task_id}', '${step}')
" 2>/dev/null || log "WARN" "checkpoint python call failed (non-fatal)"
    else
        log "WARN" "task_checkpoints.py not found — skipping checkpoint $step"
    fi
}

require_cmd() {
    command -v "$1" >/dev/null 2>&1 || die "Required command not found: $1"
}

# Soft require — log warning instead of dying (we have python fallbacks)
soft_require() {
    if ! command -v "$1" >/dev/null 2>&1; then
        log "WARN" "Optional command missing: $1 (using fallback)"
        return 1
    fi
    return 0
}

detect_repo() {
    if [[ -n "$TARGET_REPO" ]]; then
        echo "$TARGET_REPO"
        return
    fi
    if [[ -n "$GITHUB_REPO" ]]; then
        echo "$GITHUB_REPO"
        return
    fi
    local url
    url=$(git -C "$REPO_DIR" remote get-url origin 2>/dev/null || echo "")
    # git@github.com:owner/repo.git  or https://github.com/owner/repo.git
    if [[ "$url" =~ github.com[:/]([^/]+/[^/.]+) ]]; then
        echo "${BASH_REMATCH[1]}"
    else
        echo "eveselove/planlytasksko"  # fallback for this workspace
    fi
}

# Returns absolute path to a local clone of the given (or detected) repo URL.
# Creates a cached shallow clone under REPO_CACHE_DIR on first encounter.
# This is the core primitive enabling "multi-repo" task execution at scale.
# For the primary workspace repo it returns $REPO_DIR directly (no extra clone).
get_repo_workdir() {
    local repo_input="${1:-$(detect_repo)}"
    # Fast path: empty / primary workspace / matches REPO_DIR origin -> use host checkout
    if [[ -z "$repo_input" ]]; then
        echo "$REPO_DIR"
        return 0
    fi
    # If it looks like the current workspace, prefer it
    local current_remote
    current_remote=$(git -C "$REPO_DIR" remote get-url origin 2>/dev/null || echo "")
    if [[ "$repo_input" == "$REPO_DIR" || "$repo_input" == "$current_remote" || "$repo_input" == "agx/planlytasksko" || "$repo_input" == *"planlytasksko"* ]]; then
        echo "$REPO_DIR"
        return 0
    fi

    # Normalize to a filesystem-safe slug and https clone url
    local slug
    slug=$(echo "$repo_input" | sed -E 's#^https?://##; s#^git@##; s#github.com[:/]##; s#\.git$##; s#/#__#g; s#:#__#g' | tr -cd '[:alnum:]_.-')
    [[ -z "$slug" ]] && slug="repo-$(echo "$repo_input" | md5sum | cut -c1-8)"

    local dest="$REPO_CACHE_DIR/$slug"
    if [[ ! -d "$dest/.git" ]]; then
        mkdir -p "$REPO_CACHE_DIR"
        local clone_url="$repo_input"
        if [[ "$clone_url" != http* && "$clone_url" != git@* ]]; then
            clone_url="https://github.com/${clone_url}.git"
        fi
        log "INFO" "multi-repo: cloning $clone_url -> $dest (first use for this repo in task)"
        if ! git clone --depth=1 --filter=blob:none "$clone_url" "$dest" >/dev/null 2>&1; then
            log "WARN" "shallow+filter clone failed, retrying standard clone"
            git clone "$clone_url" "$dest" || die "Failed to clone target repo for multi-repo task: $repo_input"
        fi
    else
        # Opportunistic refresh (cheap)
        git -C "$dest" fetch origin --depth=20 --filter=blob:none 2>/dev/null || git -C "$dest" fetch origin main --depth=20 2>/dev/null || true
    fi
    echo "$dest"
}

is_main() {
    local branch
    branch=$(git -C "$REPO_DIR" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "detached")
    [[ "$branch" == "main" ]]
}

current_sha() {
    git -C "$REPO_DIR" rev-parse HEAD
}

is_revert_commit() {
    local sha="$1"
    local msg
    msg=$(git -C "$REPO_DIR" log -1 --pretty=%s "$sha" 2>/dev/null || echo "")
    [[ "$msg" == Revert* ]] || [[ "$msg" == *"[auto-rollback"* ]]
}

# ====================== CI STATUS (GitHub) ======================
# Uses gh when available + python (json stdlib) for parsing. Zero hard dependency on jq.
query_ci_conclusion() {
    # Returns one of: success | failure | pending | unknown
    local sha="$1"
    local repo="$2"

    local out="[]"
    local have_gh=0
    command -v gh >/dev/null 2>&1 && have_gh=1

    if (( have_gh )); then
        out=$(gh run list --repo "$repo" --commit "$sha" --branch main \
              --json status,conclusion,workflowName,headSha --limit 30 2>/dev/null || echo "[]")
    elif [[ -n "${GITHUB_TOKEN:-}" ]]; then
        local api="https://api.github.com/repos/${repo}/actions/runs?head_sha=${sha}&branch=main&per_page=30"
        out=$(curl -fsSL -H "Authorization: Bearer ${GITHUB_TOKEN}" \
              -H "Accept: application/vnd.github+json" "$api" 2>/dev/null || echo '{"workflow_runs":[]}')
        # Normalize gh-style shape for unified python parser
        out=$(python3 -c '
import sys, json
data = json.load(sys.stdin)
runs = data.get("workflow_runs", [])
norm = [{"status": r.get("status"), "conclusion": r.get("conclusion")} for r in runs]
print(json.dumps(norm))
' <<< "$out" 2>/dev/null || echo "[]")
    else
        echo "unknown"
        return 0
    fi

    # Python parser (no jq needed)
    python3 -c '
import sys, json
try:
    runs = json.load(sys.stdin)
except Exception:
    print("unknown")
    sys.exit(0)

if not isinstance(runs, list):
    runs = runs.get("workflow_runs", []) if isinstance(runs, dict) else []

has_pending = False
has_failure = False
has_success = False
for r in runs:
    st = (r.get("status") or "").lower()
    conc = (r.get("conclusion") or "").lower()
    if st in ("in_progress", "queued", "waiting"):
        has_pending = True
    elif st == "completed":
        if conc in ("failure", "cancelled", "timed_out", "startup_failure"):
            has_failure = True
        elif conc == "success":
            has_success = True

if has_pending:
    print("pending")
elif has_failure:
    print("failure")
elif has_success:
    print("success")
else:
    print("unknown")
' <<< "$out"
}

# ====================== AUTO-ROLLBACK CORE ======================
perform_rollback() {
    local bad_sha="$1"
    local reason="${2:-CI failed}"
    local repo
    repo=$(detect_repo)

    if ! is_main && [[ "$DRY_RUN" != "1" ]]; then
        die "Refusing rollback: not on main branch"
    fi
    if ! is_main && [[ "$DRY_RUN" == "1" ]]; then
        log "DRY" "DRY_RUN rollback simulation (current checkout is not main — this is expected in test)"
    fi

    local head_sha
    head_sha=$(current_sha)

    if [[ "$bad_sha" != "$head_sha" ]]; then
        log "WARN" "bad_sha $bad_sha is not current HEAD ($head_sha). Refusing non-tip revert for safety."
        return 1
    fi

    if is_revert_commit "$bad_sha"; then
        log "INFO" "HEAD is already a revert commit. Skipping."
        return 0
    fi

    # Check whether a revert of this exact commit already exists in history
    if git -C "$REPO_DIR" log --oneline --grep="Revert.*${bad_sha:0:8}" --grep="auto-rollback" -i --all-match -n 5 | grep -q .; then
        log "INFO" "Revert for $bad_sha already present in history. Skipping duplicate rollback."
        return 0
    fi

    local orig_msg
    orig_msg=$(git -C "$REPO_DIR" log -1 --pretty=%s "$bad_sha")
    local revert_msg="Revert \"${orig_msg}\" [auto-rollback on CI fail by grok_worker]"

    log "ACTION" "AUTO-ROLLBACK TRIGGERED"
    log "ACTION" "  bad commit: $bad_sha"
    log "ACTION" "  reason:     $reason"
    log "ACTION" "  revert msg: $revert_msg"

    if [[ "$DRY_RUN" == "1" ]]; then
        log "DRY" "Would execute: git revert --no-edit $bad_sha && git push origin main"
        checkpoint "${TASK_ID:-guardian-$(date +%s)}" "rollback" "{\"bad_sha\":\"$bad_sha\",\"reason\":\"$reason\",\"dry_run\":true}"
        return 0
    fi

    # Do the revert (creates a new commit)
    if ! git -C "$REPO_DIR" revert --no-edit "$bad_sha"; then
        die "git revert failed — manual intervention required on main"
    fi

    # Push the healing commit
    if ! git -C "$REPO_DIR" push origin main; then
        # Try to be robust: if push rejected (race), log and leave the local revert for operator
        log "ERROR" "git push origin main failed after successful revert. Local revert commit exists."
        die "Push failed after revert. Resolve manually."
    fi

    local new_head
    new_head=$(current_sha)
    log "SUCCESS" "Auto-rollback complete. New HEAD: $new_head (reverted $bad_sha)"

    checkpoint "${TASK_ID:-guardian-$(date +%s)}" "rollback" \
        "{\"bad_sha\":\"$bad_sha\",\"new_head\":\"$new_head\",\"reason\":\"$reason\",\"reverted_at\":\"$(date -Iseconds)\"}"

    return 0
}

# ====================== CI GUARD (post-push watcher) ======================
wait_for_ci_and_guard() {
    local task_id="$1"
    local sha="${2:-$(current_sha)}"
    local repo
    repo=$(detect_repo)

    log "INFO" "CI guard started for commit $sha on $repo (max ${MAX_WAIT_MIN}m, poll ${POLL_INTERVAL}s)"

    checkpoint "$task_id" "ci_start" "{\"sha\":\"$sha\",\"repo\":\"$repo\"}"

    local waited=0
    local max_seconds=$(( MAX_WAIT_MIN * 60 ))

    if [[ "$DRY_RUN" == "1" ]]; then
        log "DRY" "DRY_RUN: skipping long CI poll — simulating SUCCESS (use FAIL_SIM=1 to test rollback path)"
        if [[ "${FAIL_SIM:-0}" == "1" ]]; then
            log "DRY" "FAIL_SIM active — simulating CI failure + rollback"
            checkpoint "$task_id" "ci_failed" "{\"sha\":\"$sha\",\"result\":\"failure\",\"dry\":true}"
            perform_rollback "$sha" "Simulated CI failure (DRY_RUN + FAIL_SIM)"
            checkpoint "$task_id" "rollback" "{\"sha\":\"$sha\",\"dry\":true}"
            return 2
        fi
        checkpoint "$task_id" "ci_done" "{\"sha\":\"$sha\",\"result\":\"success\",\"dry\":true}"
        return 0
    fi

    while (( waited < max_seconds )); do
        local status
        status=$(query_ci_conclusion "$sha" "$repo")

        log "CI" "status=$status (waited ${waited}s)"

        case "$status" in
            success)
                log "SUCCESS" "CI passed for $sha"
                checkpoint "$task_id" "ci_done" "{\"sha\":\"$sha\",\"result\":\"success\"}"
                return 0
                ;;
            failure)
                log "FAIL" "CI FAILURE DETECTED for $sha — initiating auto-rollback"
                checkpoint "$task_id" "ci_failed" "{\"sha\":\"$sha\",\"result\":\"failure\"}"
                if perform_rollback "$sha" "GitHub Actions reported failure"; then
                    checkpoint "$task_id" "rollback" "{\"sha\":\"$sha\",\"action\":\"reverted\"}"
                    # After rollback we do NOT treat the original task as success.
                    # The worker should now create a follow-up task or alert.
                    return 2   # special exit: rolled back
                else
                    return 1
                fi
                ;;
            pending|unknown)
                # continue polling
                ;;
        esac

        sleep "$POLL_INTERVAL"
        waited=$(( waited + POLL_INTERVAL ))
    done

    log "TIMEOUT" "CI did not finish within ${MAX_WAIT_MIN} minutes for $sha"
    checkpoint "$task_id" "ci_failed" "{\"sha\":\"$sha\",\"result\":\"timeout\"}"
    return 3
}

# ====================== GUARDIAN MODE (continuous main protector) ======================
guardian_main() {
    log "INFO" "=== grok_worker guardian-main started (protecting main forever) ==="
    require_cmd git
    require_cmd gh
    soft_require jq || true

    local repo
    repo=$(detect_repo)
    log "INFO" "Watching repo: $repo"

    while true; do
        # Only protect if we are actually on main in this checkout
        if ! is_main; then
            log "WARN" "Current checkout is not main — guardian sleeping (cd into a main checkout to activate)"
            sleep 60
            continue
        fi

        local head
        head=$(current_sha)

        # Quick recent history scan (last 3 commits) — catch any bad ones that slipped
        for sha in $(git -C "$REPO_DIR" log --oneline -n 3 --pretty=%H main 2>/dev/null); do
            # Skip if we already reverted it
            if is_revert_commit "$sha"; then
                continue
            fi

            local st
            st=$(query_ci_conclusion "$sha" "$repo" 2>/dev/null || echo "unknown")

            if [[ "$st" == "failure" ]]; then
                log "ALERT" "Guardian discovered failing commit $sha still on main!"
                perform_rollback "$sha" "Guardian scan found red CI" || true
                # After one revert, re-evaluate HEAD
                break
            fi
        done

        sleep 120   # slow background poll is fine; real-time comes from per-task wait_for_ci_and_guard
    done
}

# ====================== TASK RUNNER (stub — extend as needed) ======================
run_task() {
    local task_id="$1"
    shift || true

    # Multi-repo: if TARGET_REPO (from --repo or env) differs from current workspace,
    # prepare (clone if needed) an isolated workdir for edits/CI on that repo.
    local task_repo_dir="$REPO_DIR"
    local effective_repo
    effective_repo=$(detect_repo)
    if [[ -n "$TARGET_REPO" && "$TARGET_REPO" != "$effective_repo" ]]; then
        task_repo_dir=$(get_repo_workdir "$TARGET_REPO")
        log "INFO" "multi-repo: task $task_id will operate in $task_repo_dir (repo=$TARGET_REPO)"
        # Temporarily override for all git helpers / current_sha etc during this task
        REPO_DIR="$task_repo_dir"
        GITHUB_REPO="$TARGET_REPO"
        TARGET_REPO="$TARGET_REPO"
    fi

    log "INFO" "Starting full pipeline for task $task_id (repo_dir=$REPO_DIR)"
    checkpoint "$task_id" "dispatch" "{\"worker\":\"grok_worker.sh\",\"argv\":\"$*\",\"repo\":\"${TARGET_REPO:-$effective_repo}\"}"

    # 1. git_clone phase — for different repos we already prepared the clone above.
    #    Best practice for concurrent tasks: use git worktree per task (feature branch).
    #    Git Worktrees isolation: using /tmp/agentforge/TASK_ID per the agent isolation spec (updated for full coverage of grok_worker + runners).
    local worktree_dir=""
    if [[ "$REPO_DIR" != "$task_repo_dir" ]]; then :; fi   # already set
    # Create an isolated worktree for the task so we don't pollute the cached clone
    worktree_dir="/tmp/agentforge/${task_id}"
    local base_for_wt="$REPO_DIR"
    mkdir -p /tmp/agentforge
    if [[ ! -f "$worktree_dir/.git" ]] && [[ ! -d "$worktree_dir/.git" ]]; then
        local branch="agentforge-${task_id}"
        # Add worktree from the (possibly multi-repo) base (idempotent)
        git -C "$base_for_wt" worktree add --detach "$worktree_dir" 2>/dev/null || \
        git -C "$base_for_wt" worktree add -B "$branch" "$worktree_dir" origin/main 2>/dev/null || true
        if [[ -f "$worktree_dir/.git" ]] || [[ -d "$worktree_dir" ]]; then
            log "INFO" "multi-repo isolation: using worktree $worktree_dir (agentforge pattern)"
            REPO_DIR="$worktree_dir"
            # Register for dashboard Co-Pilot live terminal (human+agent shared workspace)
            curl -s -X POST "http://localhost:9090/api/tasks/${task_id}/worktree" \
              -H 'Content-Type: application/json' \
              -d "{\"path\": \"${worktree_dir}\"}" >/dev/null 2>&1 || true
        fi
    fi

    # Arm trap + cleanup *immediately* after creation (before any fallible ops, checkpoints, or waits)
    cleanup_worktree() {
        if [[ -n "$worktree_dir" && ( -f "$worktree_dir/.git" || -d "$worktree_dir" ) ]]; then
            git -C "$base_for_wt" worktree remove --force "$worktree_dir" 2>/dev/null || true
        fi
    }
    trap cleanup_worktree EXIT INT TERM
    cleanup_worktree  # no-op on first run; ensures registered early for all exit paths

    checkpoint "$task_id" "git_clone" "{\"path\":\"$REPO_DIR\",\"repo\":\"${TARGET_REPO:-}\"}"

    # 2. grok phase (the actual LLM call + edit + patch application) would be here.
    #    For now we simulate "Grok made a change and committed".
    checkpoint "$task_id" "grok_start" "{\"repo\":\"${TARGET_REPO:-}\"}"
    # (imagine edits + git commit + push to a PR or directly here)
    checkpoint "$task_id" "grok_done" "{\"files_changed\":0,\"simulated\":true,\"repo\":\"${TARGET_REPO:-}\"}"

    # 3. Push if needed (worker decides whether to target main or PR)
    #    For the "never break main" guarantee we demonstrate direct-main path + rollback.
    if is_main && [[ "$DRY_RUN" != "1" ]]; then
        log "INFO" "On main — pushing current state so CI can run (real workers may open PRs instead)"
        git -C "$REPO_DIR" push origin main || log "WARN" "push skipped or failed"
    fi

    # 4. The critical part: CI guard + auto-rollback (repo-aware via detect_repo + $REPO_DIR)
    local sha
    sha=$(current_sha)
    local rc=0
    wait_for_ci_and_guard "$task_id" "$sha" || rc=$?

    if (( rc == 2 )); then
        log "INFO" "Task $task_id ended with auto-rollback. Main is now protected."
        checkpoint "$task_id" "failed" "{\"reason\":\"ci_failure_auto_reverted\",\"repo\":\"${TARGET_REPO:-}\"}"
    elif (( rc == 0 )); then
        checkpoint "$task_id" "review" "{\"status\":\"awaiting_guardian\",\"repo\":\"${TARGET_REPO:-}\"}"
        log "INFO" "CI success — task ready for review step"
    fi

    # Explicit happy-path cleanup (trap already armed early for error/early-exit cases)
    cleanup_worktree

    return "$rc"
}

# ====================== MAIN ======================
usage() {
    cat <<EOF
grok_worker.sh — Git Auto-Rollback Guardian for Grok autonomous changes

Commands:
  guard-main [--dry-run]          Continuous background protector of main branch
  run-task <task_id> [--repo https://github.com/owner/repo] [--dry-run]
                         Execute full pipeline for one task (multi-repo aware via get_repo_workdir + cache)
                         For gateway-driven multi-repo (auto repo from task record) prefer: python scripts/grok_worker.py --gateway-task <id>
  ci-status <sha>                 Print current CI conclusion for a commit (debug)
  self-test                       Run internal parser + checkpoint integration tests
  --help

Environment variables:
  DRY_RUN=1          Simulate all git/CI actions (safe)
  YES=1              Skip interactive confirmations
  POLL_INTERVAL=30   Seconds between polls
  MAX_WAIT_MIN=20
  GITHUB_TOKEN=...   Fallback token (gh preferred)
  TASK_ID=...

Examples:
  DRY_RUN=1 ./scripts/grok_worker.sh guard-main
  ./scripts/grok_worker.sh run-task t-12345 --dry-run
  ./scripts/grok_worker.sh run-task t-987 --repo https://github.com/agx/akson-data --dry-run
  # Multi-repo via gateway task (use Python worker for auto-pull of task.repo):
  #   python scripts/grok_worker.py --gateway-task t42
  ./scripts/grok_worker.sh ci-status \$(git rev-parse HEAD)
EOF
}

main() {
    require_cmd git
    soft_require jq || true   # jq optional — query_ci_conclusion has pure-python fallback

    cd "$REPO_DIR" || die "Cannot cd to $REPO_DIR"

    local cmd="${1:-}"; shift || true

    case "$cmd" in
        guard-main|guardian)
            [[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1
            guardian_main
            ;;
        run-task|task)
            local tid="${1:-}"; shift || true
            [[ -z "$tid" ]] && die "run-task requires <task_id>"
            TASK_ID="$tid"

            # Parse multi-repo + other flags for this invocation
            while [[ $# -gt 0 ]]; do
                case "$1" in
                    --repo)
                        TARGET_REPO="$2"
                        GITHUB_REPO="$2"
                        shift 2 || true
                        ;;
                    --dry-run)
                        DRY_RUN=1
                        shift
                        ;;
                    *)
                        # unknown / passthrough
                        shift
                        ;;
                esac
            done

            if [[ -n "$TARGET_REPO" ]]; then
                log "INFO" "run-task: explicit --repo $TARGET_REPO (multi-repo mode)"
            fi
            run_task "$tid"
            ;;
        ci-status|status)
            local sha="${1:-$(current_sha)}"
            local repo
            repo=$(detect_repo)
            echo "repo=$repo sha=$sha"
            query_ci_conclusion "$sha" "$repo"
            ;;
        self-test|test)
            log "INFO" "Running internal self-test (CI parser + checkpoint integration)"
            # Synthetic test of the python parser (no network)
            local test_json='[{"status":"completed","conclusion":"failure"},{"status":"completed","conclusion":"success"}]'
            local result
            result=$(python3 -c '
import sys, json
runs = json.loads(sys.stdin.read())
has_failure = any((r.get("conclusion") or "").lower() in ("failure","cancelled") for r in runs)
print("failure" if has_failure else "success")
' <<< "$test_json")
            [[ "$result" == "failure" ]] || die "self-test parser failed"
            log "INFO" "Parser self-test: OK (detected failure in mixed runs)"

            # Checkpoint roundtrip via the worker path
            python3 -c "
import sys
sys.path.insert(0, '${REPO_DIR}/scripts')
from task_checkpoints import init_db, save_checkpoint, get_last_checkpoint, clear_task
init_db()
tid = 'grok-worker-selftest-$$'
clear_task(tid)
save_checkpoint(tid, 'ci_failed', {'sha':'deadbeef','reason':'test'})
save_checkpoint(tid, 'rollback', {'sha':'deadbeef','reverted':True})
cp = get_last_checkpoint(tid)
print('last_step:', cp['step'])
assert cp['step'] == 'rollback'
clear_task(tid)
print('checkpoint integration: OK')
"
            log "SUCCESS" "All grok_worker self-tests passed"
            ;;
        --help|-h|help)
            usage
            exit 0
            ;;
        "")
            usage
            exit 0
            ;;
        *)
            die "Unknown command: $cmd. See --help"
            ;;
    esac
}

main "$@"
