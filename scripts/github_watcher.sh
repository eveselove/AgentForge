#!/bin/bash
#
# github_watcher.sh — Auto-Discovery: GitHub Issues → Planly Tasks (agentforge label)
#
# Purpose:
#   Periodically scans GitHub for open issues labeled 'agentforge' (via gh CLI).
#   For every *new* (previously unseen) issue, creates a corresponding task in the
#   Planly HITL queue using POST /api/tasks (or /tasks).
#
#   This powers "Auto-Discovery" for AgentForge: GitHub becomes a source of work items
#   that autonomous agents (grok_worker, jules, etc.) can pick up.
#
# Usage:
#   ./scripts/github_watcher.sh                  # run once (for testing)
#   ./scripts/github_watcher.sh --dry-run        # show what would be created, no POST
#   ./scripts/github_watcher.sh --install-cron   # safely add */5 cron entry (idempotent)
#   ./scripts/github_watcher.sh --help
#
# Cron (every 5 minutes, as requested):
#   */5 * * * * /home/agx/planlytasksko/scripts/github_watcher.sh >> /home/agx/planlytasksko/logs/github_watcher.log 2>&1
#
#   Recommended (with env overrides):
#   */5 * * * * GATEWAY=http://localhost:3000 GH_REPO=agx/planlytasksko /home/agx/planlytasksko/scripts/github_watcher.sh >> /home/agx/planlytasksko/logs/github_watcher.log 2>&1
#
# Requirements:
#   - gh CLI installed and authenticated (`gh auth login` or GITHUB_TOKEN)
#   - curl (for POST to gateway)
#   - python3 (always) or jq (preferred for speed) for JSON handling
#   - Planly gateway reachable at $GATEWAY (default http://localhost:3000)
#
# Behavior:
#   - Only processes *open* issues with label 'agentforge'
#   - Deduplicates using stable keys stored in data/seen_agentforge_issues.txt
#     Key format: "owner/repo#123"
#   - Creates task with:
#       title: "[agentforge] <issue title> (GitHub #N)"
#       description: link + full issue body + metadata
#       repo: https://github.com/owner/repo  (extracted from issue URL; enables multi-repo)
#       priority: "medium"
#   - Safe: never re-creates for the same issue. Closed-then-reopened issues stay deduped
#     (manual intervention via deleting the seen key if truly desired).
#   - Logs everything. Exits gracefully on missing tools / transient gh errors.
#
# Environment variables (all optional):
#   GATEWAY          Gateway base (default: http://localhost:3000)
#   GH_REPO          "owner/repo" slug. If unset, auto-detected via `gh repo view`
#   SEEN_FILE        Path to dedup file (default: $REPO_ROOT/data/seen_agentforge_issues.txt)
#   LOG_FILE         (default: $REPO_ROOT/logs/github_watcher.log)
#   DRY_RUN          1 = do not POST, only log (also triggered by --dry-run)
#   REPO_ROOT        (default: /home/agx/planlytasksko)
#
# Integration notes (AgentForge):
#   - Created tasks appear in /api/tasks and the dashboard as "pending".
#   - Workers (grok_worker.py --gateway-task, jules_runner, etc.) will pick them up.
#   - The `repo` field on the task tells agents which repository to clone/edit.
#   - You can further tag issues with a2a_reviewer or is_complex hints via future extensions
#     (e.g. issue body frontmatter or custom labels).
#
# Tags: agentforge, auto-discovery, github, hitl, cron, gh-cli
#

set -euo pipefail

# ====================== CONFIG ======================
REPO_ROOT="${REPO_ROOT:-/home/eveselove/planlytasksko}"
GATEWAY="${GATEWAY:-http://localhost:3000}"
GH_REPO="${GH_REPO:-}"
SEEN_FILE="${SEEN_FILE:-${REPO_ROOT}/data/seen_agentforge_issues.txt}"
LOG_FILE="${LOG_FILE:-${REPO_ROOT}/logs/github_watcher.log}"
DRY_RUN="${DRY_RUN:-0}"

# ====================== HELPERS ======================
log() {
    local level="$1"; shift
    local msg="$*"
    local ts
    ts=$(date -Iseconds)
    local line="[$ts] [$level] $msg"
    echo "$line" | tee -a "$LOG_FILE" >&2
}

die() {
    log "ERROR" "$@"
    exit 1
}

require_cmd() {
    local cmd="$1"
    if ! command -v "$cmd" >/dev/null 2>&1; then
        die "Required command not found: $cmd (install it and re-run)"
    fi
}

# Safe mkdir for logs + data
ensure_dirs() {
    mkdir -p "${REPO_ROOT}/data" "${REPO_ROOT}/logs"
    touch "$SEEN_FILE" "$LOG_FILE" 2>/dev/null || true
}

# Detect current gh repo slug if not provided
detect_repo_slug() {
    if [[ -n "$GH_REPO" ]]; then
        echo "$GH_REPO"
        return 0
    fi
    # Try gh repo view (works inside a clone or with GH_REPO env for gh)
    local slug
    if slug=$(gh repo view --json nameWithOwner -q '.nameWithOwner' 2>/dev/null); then
        echo "$slug"
        return 0
    fi
    # Fallback to this repo (the one containing the watcher)
    echo "agx/planlytasksko"
}

# Build a stable dedup key: "owner/repo#123"
make_key() {
    local slug="$1"
    local number="$2"
    echo "${slug}#${number}"
}

# Check if key already seen
is_seen() {
    local key="$1"
    grep -Fxq "$key" "$SEEN_FILE" 2>/dev/null
}

# Record a key as processed (append only, no dups)
mark_seen() {
    local key="$1"
    if ! is_seen "$key"; then
        echo "$key" >> "$SEEN_FILE"
        log "INFO" "Marked seen: $key"
    fi
}

# Truncate long text safely (for description)
truncate() {
    local text="$1"
    local max="${2:-8000}"
    if [[ ${#text} -gt $max ]]; then
        echo "${text:0:$max}... [truncated]"
    else
        echo "$text"
    fi
}

# ====================== JSON (jq preferred, python3 fallback) ======================
# The project already uses Python heavily; this makes the watcher usable even
# if jq is not installed (common in minimal containers).

have_jq() { command -v jq >/dev/null 2>&1; }

json_get() {
    # json_get <json> <jq-expr-or-python-key> [default]
    local json="$1" expr="$2" default="${3:-}"
    if have_jq; then
        echo "$json" | jq -r "$expr" 2>/dev/null || echo "$default"
    else
        python3 - "$json" "$expr" "$default" 2>/dev/null <<'PYEOF' || echo "$default"
import sys, json
data = json.loads(sys.argv[1])
keys = sys.argv[2].lstrip('.').split('.')
val = data
for k in keys:
    if isinstance(val, dict):
        val = val.get(k)
    elif isinstance(val, list):
        try:
            val = val[int(k)]
        except Exception:
            val = None
    else:
        val = None
    if val is None:
        break
print(val if val is not None else sys.argv[3])
PYEOF
    fi
}

json_array_each() {
    # json_array_each <json_array>   -> prints one JSON object per line (compact)
    local json="$1"
    if have_jq; then
        echo "$json" | jq -c '.[]' 2>/dev/null
    else
        python3 - "$json" 2>/dev/null <<'PYEOF'
import sys, json
arr = json.loads(sys.argv[1])
if isinstance(arr, list):
    for item in arr:
        print(json.dumps(item, ensure_ascii=False, separators=(',', ':')))
PYEOF
    fi
}

json_length() {
    local json="$1"
    if have_jq; then
        echo "$json" | jq 'length' 2>/dev/null || echo 0
    else
        python3 - "$json" 2>/dev/null <<'PYEOF' || echo 0
import sys, json
arr = json.loads(sys.argv[1])
print(len(arr) if isinstance(arr, list) else 0)
PYEOF
    fi
}

# ====================== CORE ======================
fetch_agentforge_issues() {
    local slug="$1"
    # Use exactly the command style requested by the task.
    # We add -R for explicitness and reliability.
    gh issue list \
        --label agentforge \
        --state open \
        --json number,title,body,url,createdAt,updatedAt \
        -R "$slug" 2>/dev/null || echo '[]'
}

create_task_from_issue() {
    local slug="$1"
    local number="$2"
    local title="$3"
    local body="$4"
    local url="$5"
    local created_at="$6"

    local repo_url="https://github.com/${slug}"
    local task_title="[agentforge] ${title} (GitHub #${number})"

    local desc
    desc=$(cat <<EOF
GitHub Issue #${number}
URL: ${url}
Repository: ${repo_url}
Label: agentforge
State: open
Created: ${created_at}

---
${body}
EOF
)
    desc=$(truncate "$desc" 12000)

    local payload
    if have_jq; then
        payload=$(jq -n \
            --arg t "$task_title" \
            --arg d "$desc" \
            --arg r "$repo_url" \
            --arg p "medium" \
            '{
                title: $t,
                description: $d,
                repo: $r,
                priority: $p,
                critical: false,
                is_complex: false
            }')
    else
        payload=$(python3 - "$task_title" "$desc" "$repo_url" <<'PYEOF'
import sys, json
print(json.dumps({
    "title": sys.argv[1],
    "description": sys.argv[2],
    "repo": sys.argv[3],
    "priority": "medium",
    "critical": False,
    "is_complex": False
}, ensure_ascii=False))
PYEOF
)
    fi

    local endpoint="${GATEWAY%/}/api/tasks"

    if [[ "$DRY_RUN" == "1" ]]; then
        log "DRY" "Would POST task for #${number}:"
        log "DRY" "  title: ${task_title}"
        log "DRY" "  repo:  ${repo_url}"
        log "DRY" "  endpoint: ${endpoint}"
        log "DRY" "  payload (first 300 chars): ${payload:0:300}..."
        return 0
    fi

    log "INFO" "Creating task for GitHub #${number} (${slug}) ..."

    local resp
    local http_code
    resp=$(curl -sS -w "\n%{http_code}" -X POST "$endpoint" \
        -H "Content-Type: application/json" \
        -H "Accept: application/json" \
        -d "$payload" 2>&1) || true

    # curl -w puts status on last line
    http_code=$(echo "$resp" | tail -n1)
    local body_resp
    body_resp=$(echo "$resp" | sed '$d')

    if [[ "$http_code" =~ ^2 ]]; then
        local new_id
        new_id=$(json_get "$body_resp" '.id' '')
        if [[ -z "$new_id" || "$new_id" == "null" ]]; then
            new_id=$(json_get "$body_resp" '.task.id' 'unknown')
        fi
        [[ -z "$new_id" || "$new_id" == "null" ]] && new_id="unknown"
        log "SUCCESS" "Created task id=${new_id} from GitHub #${number}"
        return 0
    else
        log "ERROR" "POST /api/tasks failed (HTTP $http_code) for #${number}: ${body_resp:0:400}"
        return 1
    fi
}

process_issues() {
    local slug
    slug=$(detect_repo_slug)
    log "INFO" "Starting scan for label=agentforge, state=open in ${slug} (gateway=${GATEWAY})"

    require_cmd gh
    require_cmd curl
    # python3 is used as jq fallback for JSON processing; required for full functionality
    if ! command -v python3 >/dev/null 2>&1; then
        die "python3 is required (used for JSON when jq is absent)"
    fi
    if ! have_jq; then
        log "INFO" "jq not found — using python3 fallback for JSON parsing (slower but functional)"
    fi

    ensure_dirs

    local issues_json
    issues_json=$(fetch_agentforge_issues "$slug")

    # Validate it's a JSON array (works with or without jq)
    if ! (have_jq && echo "$issues_json" | jq -e 'type == "array"' >/dev/null 2>&1) && \
       ! python3 -c "
import sys, json
try:
    data = json.loads(sys.stdin.read())
    sys.exit(0 if isinstance(data, list) else 1)
except Exception:
    sys.exit(1)
" <<< "$issues_json" 2>/dev/null; then
        log "WARN" "gh returned non-array (possible auth / network issue). Raw: ${issues_json:0:200}"
        return 0
    fi

    local count
    count=$(json_length "$issues_json")

    if [[ "$count" -eq 0 ]]; then
        log "INFO" "No open agentforge issues found in ${slug}"
        return 0
    fi

    log "INFO" "Found ${count} open agentforge issue(s) in ${slug}"

    # Iterate using our json helper (jq or python fallback)
    json_array_each "$issues_json" | while IFS= read -r issue; do
        local number title body url created_at
        number=$(json_get "$issue" '.number' '0')
        title=$(json_get "$issue" '.title' 'Untitled issue')
        body=$(json_get "$issue" '.body' '')
        url=$(json_get "$issue" '.url' '')
        created_at=$(json_get "$issue" '.createdAt' '')

        local key
        key=$(make_key "$slug" "$number")

        if is_seen "$key"; then
            log "DEBUG" "Skipping already seen: $key"
            continue
        fi

        if create_task_from_issue "$slug" "$number" "$title" "$body" "$url" "$created_at"; then
            mark_seen "$key"
        else
            log "WARN" "Task creation failed for $key — will retry on next run (not marked seen)"
        fi
    done

    log "INFO" "Scan complete for ${slug}"
}

show_help() {
    sed -n '2,/^#$/p' "$0" | sed 's/^# \{0,1\}//'
    echo
    echo "Current config:"
    echo "  REPO_ROOT=$REPO_ROOT"
    echo "  GATEWAY=$GATEWAY"
    echo "  GH_REPO=${GH_REPO:-<auto>}"
    echo "  SEEN_FILE=$SEEN_FILE"
    echo "  LOG_FILE=$LOG_FILE"
    echo "  DRY_RUN=$DRY_RUN"
}

install_cron() {
    local cron_line
    cron_line="*/5 * * * * GATEWAY=${GATEWAY} GH_REPO=${GH_REPO:-agx/planlytasksko} ${REPO_ROOT}/scripts/github_watcher.sh >> ${REPO_ROOT}/logs/github_watcher.log 2>&1"

    if crontab -l 2>/dev/null | grep -Fq "${REPO_ROOT}/scripts/github_watcher.sh"; then
        log "INFO" "Cron entry for github_watcher.sh already exists — skipping"
        echo "Existing crontab entry found. Current crontab:"
        crontab -l | grep -F github_watcher.sh || true
        return 0
    fi

    log "INFO" "Installing 5-minute cron entry..."
    (crontab -l 2>/dev/null; echo "$cron_line") | crontab -
    log "SUCCESS" "Cron installed:"
    echo "  $cron_line"
    echo
    echo "Verify with:  crontab -l | grep github_watcher"
    echo "Logs will appear in: $LOG_FILE"
}

# ====================== MAIN ======================
main() {
    case "${1:-}" in
        --help|-h)
            show_help
            exit 0
            ;;
        --install-cron|--cron)
            ensure_dirs
            install_cron
            exit 0
            ;;
        --dry-run)
            DRY_RUN=1
            process_issues
            exit 0
            ;;
        "")
            process_issues
            exit 0
            ;;
        *)
            echo "Unknown argument: $1"
            show_help
            exit 1
            ;;
    esac
}

main "$@"
