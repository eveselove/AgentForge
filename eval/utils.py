"""
Utility functions for the Evaluation Framework.

Currently light. Will grow as we move from Phase 0 to Phase 1.
"""
import urllib.request
import json
from typing import Optional


AGENTFORGE_API = "http://localhost:9090"


def create_evaluation_task_in_agentforge(
    title: str,
    description: str,
    tags: list[str] = None,
    preferred_agent: str = "auto",
) -> Optional[str]:
    """
    Helper to create a real task in AgentForge marked as evaluation.
    Useful when we want to run real agents instead of simulation.
    """
    tags = tags or ["evaluation", "benchmark"]
    payload = {
        "title": f"[EVAL] {title}",
        "description": description,
        "priority": "medium",
        "complexity": "medium",
        "tags": tags,
        "preferred_agent": preferred_agent,
    }

    try:
        req = urllib.request.Request(
            f"{AGENTFORGE_API}/tasks",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read().decode())
        task_id = data.get("id")
        print(f"[Eval Utils] Created task in AgentForge: {task_id}")
        return task_id
    except Exception as e:
        print(f"[Eval Utils] Failed to create task in AgentForge: {e}")
        return None


if __name__ == "__main__":
    create_evaluation_task_in_agentforge(
        title="Test evaluation task creation",
        description="This is a test task created from the evaluation framework.",
        tags=["evaluation", "test"]
    )