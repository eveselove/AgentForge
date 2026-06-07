#!/bin/bash
# jules-watch.sh — Automatic watcher for Jules sessions
#
# Purpose: Make Jules work fully automatic.
# - Periodically checks for completed / awaiting-user Jules sessions
# - Creates tasks in the local AgentForge task queue for automatic acceptance
# - Designed to run in background (tmux, systemd, or nohup)
#
# Usage:
#   ./bin/jules-watch.sh                    # run once
#   ./bin/jules-watch.sh --loop             # run forever (every 60s)
#   ./bin/jules-watch.sh --loop --daemon    # background mode
#
# Environment:
#   JULES_WATCH_INTERVAL=60                 # seconds between checks
#   JULES_WATCH_STATE_DIR=~/.config/jules   # where to store processed sessions
#   JULES_WATCH_TASK_QUEUE=http://localhost:8080
#
# This is part of automatic "Jules → accept → apply → release" loop
# for self-improving agent development (Code Management Professionalization).

set -euo pipefail

INTERVAL="${JULES_WATCH_INTERVAL:-20}"  # Faster polling for maximum speed (default 20s)
STATE_DIR="${JULES_WATCH_STATE_DIR:-$HOME/.config/jules}"
TASK_QUEUE="${JULES_WATCH_TASK_QUEUE:-http://localhost:8080}"
PROCESSED_FILE="$STATE_DIR/processed_jules_sessions.txt"
LOG_FILE="$STATE_DIR/jules-watch.log"

mkdir -p "$STATE_DIR"
touch "$PROCESSED_FILE"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

is_processed() {
    grep -q "^$1$" "$PROCESSED_FILE" 2>/dev/null
}

mark_processed() {
    echo "$1" >> "$PROCESSED_FILE"
}

create_task() {
    local session_id="$1"
    local description="$2"
    local repo="$3"
    local status="$4"

    local title="Accept Jules work: $session_id — ${description:0:80}"
    local full_desc
    full_desc=$(cat <<EOF
Jules session completed and ready for automatic acceptance.

**Session ID:** $session_id
**Repo:** $repo
**Status:** $status
**Description:** $description

Actions needed (automatic or agent-driven):
1. Review the changes Jules produced.
2. Run: jules remote pull --session $session_id --apply (or fix conflicts).
3. Code review + tests.
4. Commit with attribution to the Jules session.
5. Prepare for release / publish.

This task was created automatically by jules-watch.sh.
EOF
)

    local json
    json=$(jq -n \
        --arg title "$title" \
        --arg desc "$full_desc" \
        --arg priority "high" \
        --arg preferred "grok" \
        --argjson tags '["jules", "auto-accept", "jules-session"]' \
        '{
            title: $title,
            description: $desc,
            priority: $priority,
            preferred_agent: $preferred,
            tags: $tags,
            jules_session_id: "'"$session_id"'",
            jules_repo: "'"$repo"'",
            jules_status: "'"$status"'"
        }')

    if curl -s -X POST "$TASK_QUEUE/tasks" \
        -H "Content-Type: application/json" \
        -d "$json" >/dev/null 2>&1; then
        log "✅ Created task for Jules session $session_id"
        mark_processed "$session_id"
    else
        log "❌ Failed to create task for $session_id"
    fi
}

check_sessions() {
    log "Checking Jules sessions..."

    local output
    output=$(/home/eveselove/.nvm/versions/node/v20.20.1/bin/jules remote list --session 2>/dev/null || true)

    # Robust parsing for Jules text output
    # Lines look like:
    # 16129745224700243524    Напиши ... agentforg…  eveselove/planlytasksko  3s ago   In Progress
    echo "$output" | awk '
        /^[0-9]{15,}/ {
            id = $1
            # Find the repo (user/repo pattern) — usually near the end
            repo = "unknown"
            for (i=1; i<=NF; i++) {
                if ($i ~ /^[a-zA-Z0-9_-]+\/[a-zA-Z0-9_.-]+$/) {
                    repo = $i
                    break
                }
            }
            # Status is the last field
            status = $(NF)
            # Description is everything between ID and repo
            desc = ""
            for (i=2; i< NF; i++) {
                if ($i ~ /^[a-zA-Z0-9_-]+\/[a-zA-Z0-9_.-]+$/) break
                desc = desc " " $i
            }
            gsub(/^[ \t]+|[ \t]+$/, "", desc)
            gsub(/…/, "...", desc)

            printf "%s|%s|%s|%s\n", id, repo, status, desc
        }
    ' | while IFS='|' read -r session_id repo status desc; do
        if [[ -z "$session_id" ]]; then continue; fi

        if is_processed "$session_id"; then
            continue
        fi

        # We only auto-create tasks for sessions that are ready for human/system acceptance
        if [[ "$status" == "Completed" || "$status" == "Awaiting User" || "$status" == "Awaiting User F" ]]; then
            log "Found ready Jules session: $session_id ($status) repo=$repo"
            create_task "$session_id" "$desc" "$repo" "$status"

            # Aggressive speed-up: auto-apply safe sessions immediately (max velocity mode)
            if [[ "$AUTO_APPLY" == "all" ]] || [[ "$AUTO_APPLY" == "safe" && " ${SAFE_REPOS[*]} " =~ " ${repo} " ]]; then
                log "⚡ AUTO-APPLY enabled for $session_id (mode=$AUTO_APPLY)"
                (
                    cd /home/eveselove/planlytasksko 2>/dev/null || cd /home/eveselove/agentforge 2>/dev/null || true
                    /home/eveselove/.nvm/versions/node/v20.20.1/bin/jules remote pull --session "$session_id" --apply 2>&1 | tee -a "$LOG_FILE"
                ) || true
            fi
        fi
    done
}

main() {
    log "=== jules-watch.sh started ==="

    if [[ "${1:-}" == "--loop" || "${1:-}" == "--daemon" ]]; then
        log "Running in loop mode (interval ${INTERVAL}s)"
        while true; do
            check_sessions
            sleep "$INTERVAL"
        done
    else
        check_sessions
    fi
}

main "$@"
# === Multi-account support (the two keys you provided) ===
# Export these for the watcher to potentially use different accounts:
#   export JULES_KEYS="AQ.Ab8RN6IFsDJ4i14SOBRcCdbrkiJYow5aqqxDHbZCJaeRzDUP6w,AQ.Ab8RN6Ln3bE-Z_c0VxwEQ29FhkH4fAdHooEF1WmDcHdTL6QxKQ"
#
# The watcher currently uses the logged-in CLI session.
# For true parallel: use bin/launch-jules-parallel.sh with the keys.

# Auto-apply policy (CAREFUL - only for trusted sessions)
AUTO_APPLY="${JULES_WATCH_AUTO_APPLY:-false}"  # Set to "safe" or "all" to enable auto-apply
SAFE_REPOS=("planlytasksko" "agentforge")       # Only auto-apply for these repos if "safe" mode
