"""
Early composition example: running a goal with planning + safety + automatic observability.

This is the kind of high-level API we want to expose once Phase 2/3 mature.

!!! AGGRESSIVE FINAL DEPRECATION SWEEP (RUST_FULL_MIGRATION_PLAN.md + PHASE4_REMOVAL_PLAN.md) !!!
!!! Python example with historical flywheel_parity reference marked !!!
- planning/safety/observability core modules are EXEMPT from flywheel Phase 4 removal.
- The parity harness comment at bottom is legacy (flywheel_parity/ is Tier 1 deletion target post validation).
- No direct flywheel orchestration in this file; kept for reference only.
See PHASE4_REMOVAL_PLAN.md (exemptions section + Tier 1) + learning/utils.py (guard + list).
"""

from agentforge.planning import HierarchicalPlanner
from agentforge.safety import PolicyEngine
from agentforge.observability import create_spans_from_trajectory


def run_goal_with_planning_and_safety(goal: str, executor):
    """
    High-level entry point (very early prototype).

    1. Plans the goal hierarchically
    2. Applies safety policies before executing subtasks
    3. Executes (via provided executor)
    4. Collects observability data
    """
    planner = HierarchicalPlanner()
    policy = PolicyEngine()
    policy.add_rule(PolicyEngine.no_dangerous_commands)

    plan = planner.decompose(goal)

    for subtask in planner.get_execution_order(plan):
        decision = policy.evaluate("subtask_execution", {"description": subtask.description})
        if decision.decision.value == "block":
            print(f"[Safety] Blocked subtask: {subtask.description} — {decision.reason}")
            continue

        print(f"[Executor] Running: {subtask.description}")
        try:
            result = executor(subtask)
            subtask.result = result
            subtask.status = "done"
        except Exception as e:
            subtask.status = "failed"
            subtask.result = str(e)

    # After execution, one could do:
    # spans = create_spans_from_trajectory(...)
    # print("Observability collected.")

    return plan


if __name__ == "__main__":
    def dummy_executor(subtask):
        print(f"   (simulated work on: {subtask.description})")
        return "success"

    plan = run_goal_with_planning_and_safety(
        "Add comprehensive rate limiting and audit logging to the auth service",
        dummy_executor
    )
    print("\nFinal plan status:", [s.status for s in plan.subtasks])

# Phase 2 shadow FURTHER ENRICHED (v4 more diffs + smart pairing + farm usability):
#   PYTHONPATH=. python -m agentforge.learning.flywheel_parity.parity_harness --shadow-compare-latest --json
#   (auto-pairs + v4 expanded diffs + fidelity_pass/composite etc)
#   ... --shadow-aggregate --json   # easiest zero-cost health
# Writes enriched shadow_fidelity_* + _latest + _aggregate under /tmp/agentforge_rust_flywheel/ (detailed diffs, fidelity_pass etc)
