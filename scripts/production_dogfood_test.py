#!/usr/bin/env python3
import time
import requests
import json
import uuid
import sys

API_BASE = "http://localhost:9090/api/tasks"

TASKS_TO_INJECT = [
    "Check AGENTS.md and summarize the Antigravity Orchestration Protocol in one sentence.",
    "Search the repository for any hardcoded localhost:8080 URLs.",
    "Measure the size of the tasks.db file and return it.",
    "Check the last 10 commits for traceability compliance (Task ID or Jules session presence).",
    "Find all TODO comments in gateway/src/main.rs.",
    "Verify the presence of 'grok_worker.sh' in the root directory.",
    "Summarize the CI policy located in docs/CI_POLICY.md.",
    "Count the number of files in the `docs` folder.",
    "Check if there are any `.bak` files in the root directory.",
    "Verify the rust workspace members defined in gateway/Cargo.toml.",
    "Explain the purpose of bin/audit-branch-protection.sh.",
    "Find the largest markdown file in the repository.",
    "Read package.json and return its name and version.",
    "Check the syntax of grok_xai_worker.sh using bash -n.",
    "Find how many occurrences of 'requires_agent_review' exist in the Rust crates.",
    "Read the root README.md and output its first paragraph.",
    "Verify that the 'agents' tmux session is documented in AGENTS.md.",
    "List all shell scripts in the bin/ directory.",
    "Check the status of the GitHub branch protection rules from .github/BRANCH_PROTECTION.md.",
    "Identify the main database used by the Rust gateway (LanceDB)."
]

def create_task(description):
    payload = {
        "title": f"[Dogfood Test] {description[:40]}...",
        "description": description,
        "priority": "medium",
        "tags": ["dogfood", "test", "auto-generated"]
    }
    
    try:
        resp = requests.post(API_BASE, json=payload, timeout=5)
        resp.raise_for_status()
        return resp.json().get("id")
    except Exception as e:
        print(f"Failed to create task: {e}")
        return None

def main():
    print("🚀 Starting AgentForge Production Dogfood Test...")
    print(f"Injecting {len(TASKS_TO_INJECT)} diagnostic tasks into the Gateway...")
    
    task_ids = []
    task_metrics = {}
    
    for desc in TASKS_TO_INJECT:
        tid = create_task(desc)
        if tid:
            task_ids.append(tid)
            task_metrics[tid] = {
                "created_at": time.time(),
                "pickup_time": None,
                "finish_time": None,
                "status": "pending",
                "valid_schema": True
            }
            time.sleep(0.1) # Avoid slamming the API instantly
    
    if not task_ids:
        print("❌ No tasks were created. Exiting.")
        sys.exit(1)
        
    print(f"✅ {len(task_ids)} tasks injected successfully. Monitoring execution...")
    
    start_time = time.time()
    active = True
    
    # Dashboard API consistency check sets
    VALID_STATUSES = {"pending", "in_progress", "review", "done", "failed"}
    VALID_PRIORITIES = {"low", "medium", "high", "critical"}
    
    while active:
        active = False
        try:
            resp = requests.get(API_BASE + "?limit=500", timeout=5)
            resp.raise_for_status()
            all_tasks = resp.json()
            print(f"DEBUG: Fetched {len(all_tasks)} tasks from API")
        except Exception as e:
            print(f"⚠️ Failed to fetch tasks: {e}")
            time.sleep(2)
            active = True
            continue
            
        current_time = time.time()
        
        # Filter to only our tasks
        for task in all_tasks:
            tid = task.get("id")
            if tid in task_metrics:
                m = task_metrics[tid]
                new_status = task.get("status", "pending")
                
                # API Schema Validation (Dashboard Consistency)
                if new_status not in VALID_STATUSES:
                    m["valid_schema"] = False
                if task.get("priority") not in VALID_PRIORITIES:
                    m["valid_schema"] = False
                if "title" not in task or "description" not in task:
                    m["valid_schema"] = False
                
                # State Transitions & Latency
                if new_status == "in_progress" and m["status"] == "pending":
                    m["pickup_time"] = current_time
                    
                if new_status in ["done", "review", "failed"] and m["status"] not in ["done", "review", "failed"]:
                    # If it jumped straight from pending, pickup time = finish time
                    if m["pickup_time"] is None:
                        m["pickup_time"] = current_time
                    m["finish_time"] = current_time
                
                m["status"] = new_status
                
                if new_status in ["pending", "in_progress"]:
                    active = True
        
        # Timeout after 5 minutes (300 seconds)
        if current_time - start_time > 300:
            print("⏳ Timeout reached (5 minutes). Stopping monitor.")
            break
            
        if active:
            time.sleep(2)
            
    print("\n" + "="*50)
    print("📊 DOGFOODING TEST RESULTS")
    print("="*50)
    
    pickup_latencies = []
    completion_latencies = []
    schema_failures = 0
    statuses = {"done": 0, "review": 0, "failed": 0, "pending": 0, "in_progress": 0}
    
    for tid, m in task_metrics.items():
        statuses[m["status"]] = statuses.get(m["status"], 0) + 1
        if not m["valid_schema"]:
            schema_failures += 1
            
        if m["pickup_time"]:
            pickup_latencies.append(m["pickup_time"] - m["created_at"])
            if m["finish_time"]:
                completion_latencies.append(m["finish_time"] - m["pickup_time"])
                
    avg_pickup = sum(pickup_latencies)/len(pickup_latencies) if pickup_latencies else 0
    avg_completion = sum(completion_latencies)/len(completion_latencies) if completion_latencies else 0
    
    print(f"Total Tasks Tracked: {len(task_metrics)}")
    print(f"Status Breakdown: {statuses}")
    print(f"Average Pickup Latency: {avg_pickup:.2f} seconds")
    print(f"Average Execution Latency: {avg_completion:.2f} seconds")
    print(f"Dashboard Schema Validation Failures: {schema_failures}")
    
    if statuses["pending"] > 0 or statuses["in_progress"] > 0:
        print("⚠️ Warning: Some tasks did not finish within the 5 minute window.")
    elif schema_failures > 0:
        print("⚠️ Warning: Some tasks violated the expected Dashboard API schema.")
    else:
        print("✅ SUCCESS: All tasks successfully processed by the agent swarm with 100% schema consistency.")

if __name__ == "__main__":
    main()
