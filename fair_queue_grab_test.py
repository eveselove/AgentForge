#!/usr/bin/env python3
"""
Fair Queue Test 2 — "who grabs first?"
Verifies the atomic CAS claim in AgentForge /tasks PATCH endpoint.

- Creates a fresh auto task
- Two "agents" (threads) concurrently attempt to claim via PATCH in_progress + assigned_agent
- Exactly one must win (rowcount >0 or returned assigned_agent matches), the other must lose (see pre-reject or DB atomic reject)
- Cleans up the test task at the end (marks failed or deletes if possible)

Run:
  python3 fair_queue_grab_test.py

Tags: test, fair-queue, concurrency, cas, who-grabs-first
"""

import json
import os
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

API = os.environ.get("AGENTFORGE_API", "http://localhost:9090")
AGENT_A = "test-grabber-a"
AGENT_B = "test-grabber-b"


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{ts}] {msg}", flush=True)


def api(method, path, data=None, timeout=15):
    url = f"{API}{path}"
    req = urllib.request.Request(url, method=method)
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        req.data = body
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        log(f"HTTP {e.code} {path}: {body[:300]}")
        return {"error": body, "status": e.code}
    except Exception as e:
        log(f"API ERR {path}: {e}")
        return {"error": str(e)}


def create_test_task(title_prefix="Fair queue test 2 — who grabs first?"):
    payload = {
        "title": f"{title_prefix} [concurrency-verification {int(time.time())}]",
        "description": "Automated CAS claim test. preferred=auto. Two grabbers race. Only one must succeed.",
        "priority": "low",
        "preferred_agent": "auto",
        "tags": ["test", "fair-queue", "cas", "concurrency"],
    }
    resp = api("POST", "/tasks", payload)
    if isinstance(resp, dict) and "id" in resp:
        tid = resp["id"]
        log(f"✅ Created test task {tid}")
        return tid
    log(f"❌ Failed to create task: {resp}")
    return None


def claim_task(task_id, agent_name):
    """Simulate one agent trying to grab the task."""
    log(f"[{agent_name}] Attempting claim on {task_id}...")
    resp = api("PATCH", f"/tasks/{task_id}", {
        "status": "in_progress",
        "assigned_agent": agent_name,
    })
    if not resp or "error" in resp:
        log(f"[{agent_name}] Claim failed (no response or error)")
        return {"agent": agent_name, "won": False, "resp": resp}

    status = (resp.get("status") or "").lower()
    assigned = (resp.get("assigned_agent") or "").lower()
    won = (status == "in_progress" and assigned == agent_name.lower())
    log(f"[{agent_name}] Claim result: status={status} assigned={assigned} won={won}")
    return {"agent": agent_name, "won": won, "resp": resp}


def cleanup_task(task_id):
    # Best effort: mark failed so it doesn't pollute real queue (or leave for manual)
    resp = api("PATCH", f"/tasks/{task_id}", {
        "status": "failed",
        "result": "fair_queue_grab_test.py cleanup (verification only)",
        "assigned_agent": "fair-queue-tester",
    })
    log(f"🧹 Cleanup on {task_id}: {resp.get('status') if isinstance(resp, dict) else resp}")


def main():
    log("=== Fair Queue Test 2: who grabs first? (CAS verification) ===")
    log(f"API: {API}")

    task_id = create_test_task()
    if not task_id:
        log("ABORT: no task")
        return 2

    # Give the task a moment to be visible in all lists
    time.sleep(0.2)

    winners = []
    with ThreadPoolExecutor(max_workers=2) as ex:
        futs = [
            ex.submit(claim_task, task_id, AGENT_A),
            ex.submit(claim_task, task_id, AGENT_B),
        ]
        for fut in as_completed(futs):
            res = fut.result()
            if res["won"]:
                winners.append(res["agent"])

    log(f"--- RESULTS ---")
    log(f"Winners: {winners}")
    if len(winners) == 1:
        log("✅ PASS: Exactly one agent grabbed the task (fair first-wins CAS works)")
        outcome = "PASS"
        ret = 0
    elif len(winners) == 0:
        log("❌ FAIL: No one won the claim (both lost the race)")
        outcome = "FAIL (no winner)"
        ret = 1
    else:
        log("❌ FAIL: Multiple winners (double-claim bug, CAS broken)")
        outcome = "FAIL (multiple winners)"
        ret = 1

    # Final state check
    final = api("GET", f"/tasks/{task_id}")  # may 404 or return the obj; try list instead
    tasks = api("GET", "/tasks")
    if isinstance(tasks, list):
        for t in tasks:
            if t.get("id") == task_id:
                final = t
                break
    log(f"Final task state: { {k: final.get(k) for k in ('id','status','assigned_agent','preferred_agent') if isinstance(final, dict)} }")

    cleanup_task(task_id)

    log(f"=== Test {outcome} ===")
    return ret


if __name__ == "__main__":
    import sys
    sys.exit(main())
