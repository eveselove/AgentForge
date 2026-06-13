"""
Phase 3: Hierarchical Planner + Dependency Graph + Execution Engine + Checkpointing.

Pragmatic, production-oriented skeleton that integrates with:
- Long-running tasks (via long_horizon)
- Eval benchmarks (plan a benchmark task, execute steps with verification hooks)
- Task queue checkpoints (serialize Plan state to JSON for /checkpoint endpoints)
- Worktree execution (subtasks can target specific worktrees or skills)

Core features (working now, no external deps):
- Subtask with dependencies
- DependencyGraph with Kahn topo-sort + parallel wave scheduling
- HierarchicalPlanner with stub decomposition (ready for LLM hook)
- ExecutionEngine: sequential or parallel (ThreadPool) execution, skips completed on resume
- Full checkpoint / resume: to_dict/from_dict + JSON save/load
- Simple progress + failure recovery (mark failed, continue on dependents? policy decides)

Usage skeleton:
    from agentforge.planning import HierarchicalPlanner, ExecutionEngine, PlanCheckpoint

    planner = HierarchicalPlanner()
    plan = planner.decompose("Refactor the entire proxy rotation layer for 10x scale")

    engine = ExecutionEngine()
    # executor is a callable(subtask) -> result; it can use skills, call into worktree, etc.
    final_plan = engine.execute(plan, executor=my_executor, parallel=True, max_workers=2)

    # Later / on crash:
    PlanCheckpoint.save(plan, "/tmp/myplan.json")
    restored = PlanCheckpoint.load("/tmp/myplan.json")
    engine.resume(restored, executor=..., from_last_checkpoint=True)
"""

from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional, Callable, Set, Tuple
from datetime import datetime
import json
import uuid
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor, as_completed


@dataclass
class Subtask:
    id: str
    description: str
    dependencies: List[str] = field(default_factory=list)
    status: str = "pending"  # pending, ready, running, done, failed, skipped
    result: Optional[Any] = None
    error: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    metadata: Dict[str, Any] = field(
        default_factory=dict
    )  # tags, estimated_min, risk, skill_hint, worktree etc.

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Subtask":
        return cls(**data)


@dataclass
class Plan:
    goal: str
    subtasks: List[Subtask]
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    metadata: Dict[str, Any] = field(
        default_factory=dict
    )  # source, version, estimated_total_min etc.

    def get_subtask(self, sid: str) -> Optional[Subtask]:
        for st in self.subtasks:
            if st.id == sid:
                return st
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "goal": self.goal,
            "created_at": self.created_at,
            "metadata": self.metadata,
            "subtasks": [s.to_dict() for s in self.subtasks],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Plan":
        subtasks = [Subtask.from_dict(sd) for sd in data.get("subtasks", [])]
        return cls(
            goal=data["goal"],
            subtasks=subtasks,
            id=data.get("id", str(uuid.uuid4())[:8]),
            created_at=data.get("created_at", datetime.utcnow().isoformat()),
            metadata=data.get("metadata", {}),
        )


class DependencyGraph:
    """Lightweight dependency graph + scheduler. No external deps. Supports cycles detection (MVP: assumes acyclic or raises)."""

    def __init__(self, subtasks: List[Subtask]):
        self.subtasks = {s.id: s for s in subtasks}
        self.adj: Dict[str, List[str]] = defaultdict(list)  # id -> dependents
        self.indeg: Dict[str, int] = defaultdict(int)

        for s in subtasks:
            for dep in s.dependencies:
                if dep not in self.subtasks:
                    # tolerate missing for robustness in skeleton
                    continue
                self.adj[dep].append(s.id)
                self.indeg[s.id] += 1
            if s.id not in self.indeg:
                self.indeg[s.id] = 0

    def topological_sort(self) -> List[str]:
        """Kahn's algorithm. Returns ordered list of ids."""
        indeg = self.indeg.copy()
        q = deque([nid for nid, d in indeg.items() if d == 0])
        order: List[str] = []

        while q:
            node = q.popleft()
            order.append(node)
            for neigh in self.adj[node]:
                indeg[neigh] -= 1
                if indeg[neigh] == 0:
                    q.append(neigh)

        if len(order) != len(self.subtasks):
            raise ValueError("Cycle detected in plan dependencies (or orphan nodes)")
        return order

    def get_parallel_schedule(self) -> List[List[str]]:
        """Returns waves (lists) of task ids that can run in parallel within each wave."""
        indeg = self.indeg.copy()
        q: List[str] = [nid for nid, d in indeg.items() if d == 0]
        waves: List[List[str]] = []

        while q:
            wave = list(q)
            waves.append(wave)
            next_q: List[str] = []
            for node in wave:
                for neigh in self.adj[node]:
                    indeg[neigh] -= 1
                    if indeg[neigh] == 0:
                        next_q.append(neigh)
            q = next_q
        return waves

    def get_ready_now(self, completed: Set[str], failed: Set[str] = None) -> List[str]:
        """Given completed set, which pending tasks have all deps satisfied?"""
        failed = failed or set()
        ready = []
        for sid, s in self.subtasks.items():
            if s.status in ("done", "skipped") or sid in completed:
                continue
            if all(
                d in completed
                or self.subtasks.get(d, Subtask(d, "")).status in ("done", "skipped")
                for d in s.dependencies
            ):
                ready.append(sid)
        return ready


class HierarchicalPlanner:
    """Hierarchical task decomposition + plan management.

    MVP decomposition is rule-based + template. Production version should call an LLM
    (via agentforge.eval or direct grok call) with the goal + repo map + existing skills.
    """

    def __init__(self):
        self._decompose_hook: Optional[Callable[[str, Optional[Dict]], Plan]] = None

    def set_decompose_hook(self, hook: Callable[[str, Optional[Dict[str, Any]]], Plan]):
        """Inject a real decomposer (LLM-powered or skill-based)."""
        self._decompose_hook = hook

    def decompose(self, goal: str, context: Optional[Dict[str, Any]] = None) -> Plan:
        """Decompose goal. Falls back to smart template when no hook registered."""
        if self._decompose_hook:
            return self._decompose_hook(goal, context)

        ctx = context or {}
        # Pragmatic template decomposition (good enough for skeleton + many real tasks)
        base = [
            Subtask(
                id="S1",
                description=f"Analyze goal and gather context: {goal}",
                metadata={"phase": "analysis", "tags": ["understand"]},
            ),
            Subtask(
                id="S2",
                description="Design / plan concrete steps and identify affected files + risks",
                dependencies=["S1"],
                metadata={"phase": "design"},
            ),
            Subtask(
                id="S3",
                description="Implement core changes (edits, new modules, refactors)",
                dependencies=["S2"],
                metadata={
                    "phase": "implement",
                    "skill_hint": "rust-fix or tool-creation",
                },
            ),
            Subtask(
                id="S4",
                description="Add / update tests and verification",
                dependencies=["S3"],
                metadata={"phase": "verify"},
            ),
            Subtask(
                id="S5",
                description="Run CI + self-checks + final validation inside worktree",
                dependencies=["S4"],
                metadata={"phase": "ci"},
            ),
        ]
        # Simple heuristic extensions (robust id-based wiring)
        if (
            "refactor" in goal.lower()
            or "large" in str(ctx.get("complexity", "")).lower()
        ):
            migration = Subtask(
                id="S2b",
                description="Create incremental migration plan + rollback strategy",
                dependencies=["S2"],
                metadata={"risk": "high"},
            )
            base.insert(2, migration)
            # Rewire S4 (now at index 4 after insert) and S5
            for st in base:
                if st.id == "S4":
                    st.dependencies = ["S3", "S2b"]
                if st.id == "S5":
                    st.dependencies = ["S4"]
        if "crawler" in goal.lower() or "proxy" in goal.lower():
            base.append(
                Subtask(
                    id="S6",
                    description="Benchmark + adaptive tuning + load test",
                    dependencies=["S5"],
                    metadata={"category": "perf"},
                )
            )

        plan = Plan(
            goal=goal,
            subtasks=base,
            metadata={"decomposer": "template-v1", "context": ctx},
        )
        return plan

    def build_graph(self, plan: Plan) -> DependencyGraph:
        return DependencyGraph(plan.subtasks)

    def get_execution_order(self, plan: Plan) -> List[Subtask]:
        graph = self.build_graph(plan)
        order_ids = graph.topological_sort()
        return [plan.get_subtask(sid) for sid in order_ids if plan.get_subtask(sid)]

    def visualize_ascii(self, plan: Plan) -> str:
        """Simple text visualization of waves for humans / logs."""
        graph = self.build_graph(plan)
        waves = graph.get_parallel_schedule()
        lines = [f"Plan {plan.id}: {plan.goal}"]
        for i, wave in enumerate(waves, 1):
            lines.append(f"  Wave {i} (parallelizable): {', '.join(wave)}")
        return "\n".join(lines)


class ExecutionEngine:
    """Runs plans. Supports sequential, parallel (threads), resume-from-checkpoint, and progress callbacks."""

    def __init__(self, planner: Optional[HierarchicalPlanner] = None):
        self.planner = planner or HierarchicalPlanner()

    def _mark_ready(self, plan: Plan, graph: DependencyGraph):
        completed = {s.id for s in plan.subtasks if s.status == "done"}
        for sid in graph.get_ready_now(completed):
            st = plan.get_subtask(sid)
            if st and st.status == "pending":
                st.status = "ready"

    def execute(
        self,
        plan: Plan,
        executor: Callable[[Subtask], Any],
        *,
        parallel: bool = False,
        max_workers: int = 4,
        on_progress: Optional[Callable[[Plan, Subtask], None]] = None,
        stop_on_first_failure: bool = True,
    ) -> Plan:
        """Execute the plan. Mutates subtasks in-place with status + result."""
        graph = self.planner.build_graph(plan)
        order = graph.topological_sort()

        completed: Set[str] = {s.id for s in plan.subtasks if s.status == "done"}
        failed: Set[str] = set()

        if parallel:
            # Wave-based parallel execution (true concurrency for independent subtasks)
            waves = graph.get_parallel_schedule()
            for wave in waves:
                wave_tasks = [
                    plan.get_subtask(sid) for sid in wave if sid not in completed
                ]
                wave_tasks = [
                    t
                    for t in wave_tasks
                    if t and t.status not in ("done", "failed", "skipped")
                ]

                if not wave_tasks:
                    continue

                with ThreadPoolExecutor(max_workers=max_workers) as pool:
                    fut_to_sub = {}
                    for sub in wave_tasks:
                        sub.status = "running"
                        sub.started_at = datetime.utcnow().isoformat()
                        fut = pool.submit(self._safe_exec, executor, sub)
                        fut_to_sub[fut] = sub

                    for fut in as_completed(fut_to_sub):
                        sub = fut_to_sub[fut]
                        ok, res, err = fut.result()
                        self._apply_result(sub, ok, res, err)
                        if ok:
                            completed.add(sub.id)
                        else:
                            failed.add(sub.id)
                        if on_progress:
                            on_progress(plan, sub)
                        if not ok and stop_on_first_failure:
                            # Cancel remaining in pool (best effort)
                            break
        else:
            # Strict sequential in topo order (most predictable for agent work)
            for sid in order:
                sub = plan.get_subtask(sid)
                if not sub or sub.status in ("done", "skipped"):
                    continue
                # Check deps still satisfied (in case of prior failures)
                if any(
                    d not in completed
                    and plan.get_subtask(d)
                    and plan.get_subtask(d).status != "done"
                    for d in sub.dependencies
                ):
                    sub.status = "skipped"
                    sub.error = "Dependency not completed"
                    continue

                sub.status = "running"
                sub.started_at = datetime.utcnow().isoformat()
                ok, res, err = self._safe_exec(executor, sub)
                self._apply_result(sub, ok, res, err)
                if ok:
                    completed.add(sid)
                else:
                    failed.add(sid)
                    if stop_on_first_failure:
                        break
                if on_progress:
                    on_progress(plan, sub)

        # Final sweep: mark anything still pending whose deps are done
        self._mark_ready(plan, graph)
        return plan

    def _safe_exec(
        self, executor: Callable[[Subtask], Any], sub: Subtask
    ) -> Tuple[bool, Any, Optional[str]]:
        try:
            result = executor(sub)
            return True, result, None
        except Exception as e:
            return False, None, str(e)[:500]

    def _apply_result(self, sub: Subtask, ok: bool, result: Any, err: Optional[str]):
        sub.completed_at = datetime.utcnow().isoformat()
        if ok:
            sub.status = "done"
            sub.result = result
            sub.error = None
        else:
            sub.status = "failed"
            sub.error = err
            sub.result = None

    def resume(
        self,
        plan: Plan,
        executor: Callable[[Subtask], Any],
        *,
        parallel: bool = False,
        max_workers: int = 4,
        on_progress: Optional[Callable[[Plan, Subtask], None]] = None,
    ) -> Plan:
        """Resume a plan that may have partial completion. Skips done/skipped."""
        # Recompute ready states
        graph = self.planner.build_graph(plan)
        self._mark_ready(plan, graph)
        return self.execute(
            plan,
            executor,
            parallel=parallel,
            max_workers=max_workers,
            on_progress=on_progress,
            stop_on_first_failure=True,
        )


class PlanCheckpoint:
    """Checkpoint / resume helpers. Works great with AgentForge /tasks/{id}/checkpoint JSON state."""

    @staticmethod
    def save(plan: Plan, filepath: str):
        data = plan.to_dict()
        data["_saved_at"] = datetime.utcnow().isoformat()
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    @staticmethod
    def load(filepath: str) -> Plan:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        return Plan.from_dict(data)

    @staticmethod
    def to_task_checkpoint_state(plan: Plan) -> Dict[str, Any]:
        """Produce a compact dict suitable for storing in AgentForge task checkpoints."""
        done = [s.id for s in plan.subtasks if s.status == "done"]
        failed = [s.id for s in plan.subtasks if s.status == "failed"]
        progress = round(100.0 * len(done) / max(1, len(plan.subtasks)), 1)
        return {
            "plan_id": plan.id,
            "goal": plan.goal,
            "completed_subtasks": done,
            "failed_subtasks": failed,
            "progress_pct": progress,
            "last_updated": datetime.utcnow().isoformat(),
            "subtask_status": {s.id: s.status for s in plan.subtasks},
        }


# Convenience re-exports for users of the module
__all__ = [
    "Subtask",
    "Plan",
    "DependencyGraph",
    "HierarchicalPlanner",
    "ExecutionEngine",
    "PlanCheckpoint",
]
