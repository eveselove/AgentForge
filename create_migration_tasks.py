import json
import urllib.request

API_BASE = "http://localhost:9090"

tasks = [
    {
        "title": "Rust Migration Phase 1: Native Rust Worker Pool",
        "description": "Port antigravity_worker.py logic (Model Rate-Limit Rotation, atomic POST /claim, Guardian interaction) to a native Rust worker pool (agentforge-runner). Implement Git worktree isolation in Rust using std::process::Command or git2-rs.",
        "priority": "high",
        "complexity": "complex",
        "preferred_agent": "antigravity",
        "tags": ["rustification", "phase1", "worker"]
    },
    {
        "title": "Rust Migration Phase 1: Rust Supervisor Daemon",
        "description": "Migrate watchdog.py and core/agentforge_watchdog.py into a Rust supervisor daemon. Port MCP server bindings (mcp_server.py) to Rust.",
        "priority": "high",
        "complexity": "complex",
        "preferred_agent": "antigravity",
        "tags": ["rustification", "phase1", "watchdog"]
    },
    {
        "title": "Rust Migration Phase 2: Core Safety and Planning Subsystems",
        "description": "Rewrite safety/policy_engine.py, safety/sandbox.py into a Rust agentforge-safety crate. Port planning/planner.py to Rust, integrating directly with LanceDB.",
        "priority": "medium",
        "complexity": "complex",
        "preferred_agent": "antigravity",
        "tags": ["rustification", "phase2", "safety", "planning"]
    },
    {
        "title": "Rust Migration Phase 3: Rewrite Utilities and Binaries",
        "description": "Rewrite consume-handoff-reviews.py into agentforge-cli review consume. Rewrite swarm-decompose.py into agentforge-cli swarm decompose.",
        "priority": "medium",
        "complexity": "medium",
        "preferred_agent": "antigravity",
        "tags": ["rustification", "phase3", "cli"]
    },
    {
        "title": "Rust Migration Phase 4: Evaluation and Analytics Module",
        "description": "Build agentforge-eval as a dedicated Rust workspace capable of parallelized evaluation against LanceDB. Port eval/runner.py, eval/report.py, and learning/trajectory_dataset.py.",
        "priority": "low",
        "complexity": "complex",
        "preferred_agent": "antigravity",
        "tags": ["rustification", "phase4", "eval"]
    }
]

for task in tasks:
    req = urllib.request.Request(f"{API_BASE}/tasks", method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, data=json.dumps(task).encode("utf-8")) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            print(f"Created: {data['id']} - {data['title']}")
    except Exception as e:
        print(f"Failed to create task: {e}")

