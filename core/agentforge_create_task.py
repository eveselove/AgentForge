#!/usr/bin/env python3
"""
agentforge_create_task.py — CLI tool for agents (esp. Architect) to create tasks and subtasks.

Enables HIERARCHICAL DELEGATION: agents now have first-class rights to spawn subtasks
by calling this from terminal / tool use. Complements the LLM auto-decompose in gateway.

Primary use: Architect (or Manager) agent decomposes a large complex task by issuing
multiple calls (or scripted batch) to create concrete child tasks under a parent.

Tags: delegation,hierarchy,orchestration,agent-tools,cli

Gateway integration:
- POSTs to $PLANLY_GATEWAY/api/tasks (default http://localhost:3000)
- Supports the full CreateTaskPayload including new `parent_id` for subtask linking.
- When parent_id given: gateway auto-appends to parent.subtask_ids and sets is_complex=true.

Usage examples (from agent shell / tool calling context):
    # Basic top-level task
    python scripts/agentforge_create_task.py \
        --title "Implement user auth" \
        --description "Add JWT + session handling with tests" \
        --repo "https://github.com/agx/planlytasksko" \
        --priority high

    # Create SUBTASK under parent (the key delegation primitive)
    python scripts/agentforge_create_task.py \
        --parent t123456 \
        --title "Design / architecture for solution" \
        --description "Break down technical approach, identify risks and dependencies." \
        --priority high

    # Used by Architect for full decomposition (multiple sequential or parallel calls)
    # Agent can emit several of these based on its own reasoning / plan.

    # With custom gateway (e.g. in container / remote)
    PLANLY_GATEWAY=http://gateway:3000 python scripts/agentforge_create_task.py --parent t7 ...

    # Dry run (no network) for prompt rehearsal
    python scripts/agentforge_create_task.py --title Test --dry-run --json

Advanced (for scripted decomposition):
    echo '[{"title":"Sub1","description":"...","priority":"high"},{"title":"Sub2",...}]' > /tmp/subs.json
    # (future: --batch-from-json support; for now agent loops over calls)

Returns: JSON with "ok", "id", "task" on success. Exit code 0 = success, nonzero on failure.

Integrates with:
- planly_gateway (parent_id support added for agent subtask creation)
- task_queue.py / task_checkpoints.py (orchestration + blackboard)
- grok_worker.py (agents that run full pipelines can now delegate)

See also: POST /api/tasks , POST /tasks/{id}/decompose (LLM path), docs on A2A delegation.
"""

import argparse
import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime
from typing import Any, Dict, Optional


def post_create_task(base_url: str, payload: Dict[str, Any], dry_run: bool = False) -> Dict[str, Any]:
    """POST to gateway /api/tasks (or /tasks). Returns parsed response or error dict."""
    url = base_url.rstrip("/") + "/api/tasks"
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "agentforge_create_task/1.0",
        "Accept": "application/json",
    }

    if dry_run:
        print("[DRY-RUN] Would POST to:", url)
        print("[DRY-RUN] Payload:", json.dumps(payload, indent=2, ensure_ascii=False))
        return {"ok": True, "dry_run": True, "would_post_to": url, "payload": payload}

    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            try:
                return json.loads(body)
            except Exception:
                return {"ok": True, "raw": body, "status": resp.status}
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")
        return {"ok": False, "error": f"HTTP {e.code}", "detail": err}
    except urllib.error.URLError as e:
        return {"ok": False, "error": f"URL error: {e.reason}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="AgentForge task/subtask creator for hierarchical delegation (Architect + peers). Tags: delegation,hierarchy,orchestration"
    )
    parser.add_argument("--title", "-t", required=True, help="Task title (required)")
    parser.add_argument("--description", "-d", default=None, help="Detailed description / acceptance criteria")
    parser.add_argument("--parent", "-p", dest="parent_id", default=None,
                        help="Parent task ID to create this as a SUBTASK (enables delegation/hierarchy)")
    parser.add_argument("--repo", default=None, help="Target repo URL (multi-repo support)")
    parser.add_argument("--priority", choices=["high", "medium", "low"], default=None)
    parser.add_argument("--critical", action="store_true", help="Mark as critical (requires HITL attention)")
    parser.add_argument("--deadline", default=None, help="SLA deadline (YYYY-MM-DD or ISO)")
    parser.add_argument("--is-complex", dest="is_complex", action="store_true",
                        help="Mark for auto LLM decomposition on create (rarely needed with manual agent delegation)")
    parser.add_argument("--a2a-reviewer", dest="a2a_reviewer", default=None,
                        help="Auto peer reviewer after completion (jules|grok|grok-2)")
    parser.add_argument("--experiment-id", dest="experiment_id", default=None)
    parser.add_argument("--variant-id", dest="variant_id", default=None)

    parser.add_argument("--gateway", default=os.environ.get("PLANLY_GATEWAY", "http://localhost:3000"),
                        help="Gateway base URL (env PLANLY_GATEWAY overrides)")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be sent, do not POST")
    parser.add_argument("--json", action="store_true", help="Output full JSON response (default pretty)")
    parser.add_argument("--silent", action="store_true", help="Minimal output (only the new task id on success)")

    args = parser.parse_args()

    payload: Dict[str, Any] = {
        "title": args.title,
        "description": args.description,
    }
    if args.parent_id:
        payload["parent_id"] = args.parent_id
    if args.repo:
        payload["repo"] = args.repo
    if args.priority:
        payload["priority"] = args.priority
    if args.critical:
        payload["critical"] = True
    if args.deadline:
        payload["deadline"] = args.deadline
    if args.is_complex:
        payload["is_complex"] = True
    if args.a2a_reviewer:
        payload["a2a_reviewer"] = args.a2a_reviewer
    if args.experiment_id:
        payload["experiment_id"] = args.experiment_id
    if args.variant_id:
        payload["variant_id"] = args.variant_id

    resp = post_create_task(args.gateway, payload, dry_run=args.dry_run)

    if args.silent:
        if resp.get("ok") and "id" in resp:
            print(resp["id"])
        elif resp.get("ok") and resp.get("dry_run"):
            print("dry-run-ok")
        else:
            print("error", file=sys.stderr)
            return 1
        return 0

    if args.json:
        print(json.dumps(resp, indent=2, ensure_ascii=False))
    else:
        if resp.get("ok"):
            tid = resp.get("id") or (resp.get("task", {}) or {}).get("id", "unknown")
            print(f"✅ Created task: {tid}")
            if args.parent_id:
                print(f"   (subtask of parent {args.parent_id} — hierarchical delegation recorded)")
            if not args.dry_run:
                print(f"   Gateway: {args.gateway}")
                print(f"   Title: {args.title}")
        else:
            print("❌ Failed to create task:")
            print(json.dumps(resp, indent=2, ensure_ascii=False))
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
