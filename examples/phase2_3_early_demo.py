"""
Early demonstration of the emerging Phase 2 + Phase 3 architecture.

This script shows the intended future usage pattern once the modules mature.

!!! AGGRESSIVE FINAL DEPRECATION SWEEP (RUST_FULL_MIGRATION_PLAN.md + PHASE4_REMOVAL_PLAN.md) !!!
!!! Python orchestration demo (TrajectoryDataset + Phase2/3 refs) marked for Phase 4 !!!
- TrajectoryDataset flywheel paths are deprecated orchestration glue (Tier 2/conditional).
- Parity harness references are historical (Tier 1 removal post-soak).
- planning/safety/long_horizon core is EXEMPT (independent value; not flywheel orchestration).
MIGRATE ANY FLYWHEEL USAGE TO: agentforge-runner flywheel-step / candidate / continuous
Guard exclusively: from agentforge.learning.utils import is_pure_rust_flywheel
Full removal order, risks (low for demo), rollback strategy in PHASE4_REMOVAL_PLAN.md + CHECKLIST.
See learning/utils.py for complete deprecated file inventory.
"""

from agentforge.learning import TrajectoryDataset
from agentforge.planning import HierarchicalPlanner
from agentforge.safety import PolicyEngine
from agentforge.long_horizon import LongTaskManager
from agentforge.observability import create_spans_from_trajectory

# Example future usage (much of this is still early skeleton)

def example_workflow():
    print("=== Phase 2/3 Early Architecture Demo ===\n")

    # 1. Build high-quality dataset from past work (Phase 2)
    # dataset = TrajectoryDataset.from_eval_results(...)  # once integration is complete

    # 2. Plan a complex goal (Phase 3)
    planner = HierarchicalPlanner()
    plan = planner.decompose("Refactor the entire authentication system with proper rate limiting and audit logs")
    print(f"Created plan with {len(plan.subtasks)} subtasks")

    # 3. Apply safety policies (Phase 3)
    policy = PolicyEngine()
    policy.add_rule(PolicyEngine.no_dangerous_commands)
    decision = policy.evaluate("shell_command", {"command": "rm -rf /tmp/test"})
    print(f"Policy decision for dangerous command: {decision.decision.value}")

    # 4. Start a long-running task (Phase 3)
    task_manager = LongTaskManager()
    task = task_manager.start_task("Migrate legacy monolith to modular services")
    print(f"Started long task: {task.id}")

    # 5. Get observability view (Phase 1+)
    # spans = create_spans_from_trajectory("some_previous_task")
    # print(summarize_spans(spans))

    print("\nThis is the direction the architecture is heading.")
    print("Most modules are still early skeletons but the structure is now in place.")

    # Phase 2 shadow (FURTHER ENRICHED v4 + max farm usability): easiest comparisons
    #   python -m agentforge.learning.flywheel_parity.parity_harness --shadow-compare-latest --json
    #   (auto smart pair + v4 diffs: numeric, bigram, title_overlap, pass/score gates etc)
    # Writes rich shadow_fidelity_*.json + latest + aggregate.
    print("\n[Phase 2 shadow v4] Easiest CLI for Rust+Python fidelity (auto-paired):")
    print("  PYTHONPATH=. python -m agentforge.learning.flywheel_parity.parity_harness --shadow-compare-latest --json")


if __name__ == "__main__":
    example_workflow()
