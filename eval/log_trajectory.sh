#!/bin/bash
# Structured Trajectory Logger for AgentForge (Phase 1 - robust & unified)
#
# Usage:
#   source /home/eveselove/agentforge/eval/log_trajectory.sh
#   log_event "task_start" '{"title":"..."}'
#   log_llm_call "grok" 1200 850 0.0023
#
# Produces CLEAN JSONL (one valid object/line, canonical shape with "data" wrapper):
#   {"ts":"...","type":"llm_call","task_id":"...","agent":"grok","data":{...}}
#
# This is the single source of truth for bash-side tracing. Fully compatible with
# trajectory.load_trajectory(), PRM, post_process, runner auto-attach, etc.
# Python construction used for 100% safe escaping (fallback printf kept).

TRAJECTORY_DIR="/home/eveselove/agentforge/eval/trajectories"
mkdir -p "$TRAJECTORY_DIR" 2>/dev/null || true

log_event() {
    local event_type="$1"
    local data_json="${2:-{}}"
    local task_id="${TASK_ID:-${task_id:-unknown}}"
    local agent="${AGENT:-${agent:-grok}}"

    local timestamp
    timestamp=$(date -u +"%Y-%m-%dT%H:%M:%S.%3NZ" 2>/dev/null || date -u +"%Y-%m-%dT%H:%M:%SZ")

    local log_file="$TRAJECTORY_DIR/${task_id}_${agent}.jsonl"

    # Validate/repair using single-quoted -c (avoids nesting hell) + stdin
    if ! printf "%s" "$data_json" | python3 -c '
import json, sys
raw = sys.stdin.read()
try:
    json.loads(raw or "{}")
    sys.exit(0)
except Exception:
    sys.exit(1)
' 2>/dev/null; then
        # repair: put original (possibly stringified) payload safely under raw
        esc=$(printf "%s" "$data_json" | python3 -c '
import json,sys
print(json.dumps(sys.stdin.read().strip()[:2000]))
' 2>/dev/null || echo '"unparsable"')
        data_json="{\"raw\":$esc}"
    fi

    # Main writer: single-quoted -c , robust argv passing + auto-unwrap of raw-if-stringified-json
    python3 -c '
import json, sys
ts, etype, tid, ag, djson, logfile = sys.argv[1:7]
data = {}
if djson and djson.strip():
    try:
        data = json.loads(djson)
    except Exception:
        raw = str(djson).strip()
        try:
            # helper calls sometimes arrive as json-text; unwrap
            inner = json.loads(raw)
            if isinstance(inner, dict):
                data = inner
            else:
                data = {"raw": raw[:2000]}
        except Exception:
            data = {"raw": raw[:2000]}
event = {"ts": ts, "type": etype, "task_id": tid, "agent": ag, "data": data}
line = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
with open(logfile, "a", encoding="utf-8") as f:
    f.write(line + "\n")
' "$timestamp" "$event_type" "$task_id" "$agent" "$data_json" "$log_file" 2>/dev/null || \
    printf "{\"ts\":\"%s\",\"type\":\"%s\",\"task_id\":\"%s\",\"agent\":\"%s\",\"data\":%s}\n" \
        "$timestamp" "$event_type" "$task_id" "$agent" "$data_json" \
        >> "$log_file" 2>/dev/null || true
}

# === Core helpers (backwards compatible) ===
log_task_start() {
    log_event "task_start" "{\"title\":\"$1\",\"priority\":\"$2\",\"tags\":\"$3\"}"
}

log_skill_loaded() {
    log_event "skill_loaded" "{\"skill\":\"$1\"}"
}

log_command() {
    log_event "command" "{\"cmd\":\"$1\"}"
}

log_completion() {
    local status="$1"
    local duration="${2:-0}"
    local cost="${3:-0.0}"
    log_event "task_completed" "{\"status\":\"$status\",\"duration_seconds\":$duration,\"cost_usd\":$cost}"
    _trigger_trajectory_callback "$status" "$duration"
}

# === Phase 1 rich structured events ===
log_llm_call() {
    # Usage: log_llm_call model tokens_in tokens_out cost_usd
    local model="${1:-grok}"
    local ti="${2:-0}"
    local to="${3:-0}"
    local cost="${4:-0.0}"
    log_event "llm_call" "{\"model\":\"$model\",\"tokens_in\":${ti},\"tokens_out\":${to},\"cost_usd\":${cost}}"
}

log_tool_call() {
    # Usage: log_tool_call tool_name duration_ms "result_preview"
    local tool="${1:-unknown}"
    local dur="${2:-0}"
    local res="${3:-}"
    local safe_res
    safe_res=$(printf '%s' "$res" | head -c 480 | python3 -c '
import json,sys
s = sys.stdin.read().strip().replace("\n", " ")
print(json.dumps(s)[1:-1])
' 2>/dev/null || echo "")
    log_event "tool_call" "{\"tool\":\"$tool\",\"duration_ms\":$dur,\"result_preview\":\"$safe_res\"}"
}

log_reasoning() {
    local thought="${1:-}"
    local safe
    safe=$(printf '%s' "$thought" | head -c 320 | python3 -c '
import json,sys
s = sys.stdin.read().strip().replace("\n", " ")
print(json.dumps(s)[1:-1])
' 2>/dev/null || echo "")
    log_event "reasoning" "{\"thought\":\"$safe\"}"
}

log_error_recovery() {
    local context="${1:-error observed}"
    local detail="${2:-}"
    log_event "error_recovery" "{\"context\":\"$context\",\"detail\":\"$detail\"}"
}

log_decision() {
    local decision="${1:-proceed}"
    local rationale="${2:-}"
    log_event "decision" "{\"decision\":\"$decision\",\"rationale\":\"$rationale\"}"
}

# === Optional Python callback support at end of task (auto-called by log_completion) ===
# Set TRAJECTORY_CALLBACK=/abs/path/to/my_hook.py  (or TRAJECTORY_POST_HOOK)
# Or rely on default: python -m agentforge.eval.post_process (when AUTO_PRM=1 or EVAL_AUTO_POSTPROCESS=1)
_trigger_trajectory_callback() {
    local status="$1"
    local duration="$2"
    local task_id="${TASK_ID:-unknown}"
    local agent="${AGENT:-grok}"
    local traj_file="$TRAJECTORY_DIR/${task_id}_${agent}.jsonl"

    # Explicit callback
    local cb="${TRAJECTORY_CALLBACK:-${TRAJECTORY_POST_HOOK:-}}"
    if [ -n "$cb" ] && [ -f "$cb" ]; then
        echo "[Trajectory] Triggering explicit callback: $cb ($task_id)" >&2
        ( python3 "$cb" --task-id "$task_id" --trajectory "$traj_file" --status "$status" --agent "$agent" 2>/dev/null || \
          bash -c "$cb $task_id $traj_file" 2>/dev/null || true ) &
        return 0
    fi

    # Default unified post-process hook (computes PRM + updates artifacts)
    if [ -f "$traj_file" ]; then
        if [ "${EVAL_AUTO_POSTPROCESS:-0}" = "1" ] || [ "${AUTO_PRM:-1}" = "1" ]; then
            if python3 -c "import agentforge.eval.post_process" >/dev/null 2>&1; then
                ( python3 -m agentforge.eval.post_process \
                    --task-id "$task_id" \
                    --trajectory "$traj_file" \
                    --agent "$agent" \
                    --status "$status" \
                    --update-mapping \
                    2>&1 | tail -6 >> "$TRAJECTORY_DIR/postprocess_${task_id}.log" 2>/dev/null ) &
            fi
        fi
    fi
}

log_task_end() {
    log_completion "${1:-done}" "${2:-0}" "${3:-0.0}"
}

export -f log_event log_task_start log_skill_loaded log_command log_completion \
    log_llm_call log_tool_call log_reasoning log_error_recovery log_decision \
    log_task_end _trigger_trajectory_callback