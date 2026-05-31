"""
Phase 3: Long-running Task Manager (heartbeats, checkpoints, pause/resume, progress, multi-day support).

This is the orchestration layer for tasks that span hours to weeks.
It composes:
- HierarchicalPlanner + ExecutionEngine (from agentforge.planning)
- ActionApprovalLayer (from agentforge.safety) for every significant action
- Persistence (JSON files + optional tie-in to task_queue checkpoints)
- Heartbeats, progress aggregation, resumability across restarts

Typical flow for a 12-hour autonomous refactor:
    manager = LongTaskManager()
    task = manager.start_long_task("Large-scale proxy + throttling refactor", use_planning=True)

    # Inside the executor you call safety checks + manager.heartbeat(...)
    # The engine runs subtasks with full dep graph + parallel waves when safe

    manager.pause(task.id)
    # ... days later ...
    restored = manager.resume(task.id)
"""

from dataclasses import dataclass, field
from typing import Dict, Any, Optional, Callable, List
from datetime import datetime, timedelta
import json
import uuid
import os
from pathlib import Path

# Cross-module imports (Phase 3 integration)
from agentforge.planning import (
    HierarchicalPlanner, ExecutionEngine, Plan, Subtask, PlanCheckpoint,
)
from agentforge.safety import (
    ActionApprovalLayer, create_default_approval_layer, Decision,
)


PERSISTENCE_DIR = Path(os.path.expanduser("~/.agentforge/long_horizon"))
PERSISTENCE_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class Progress:
    percent: float = 0.0          # 0-100
    completed_steps: int = 0
    total_steps: int = 1
    eta_seconds: Optional[int] = None
    last_message: str = ""
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "percent": round(self.percent, 1),
            "completed_steps": self.completed_steps,
            "total_steps": self.total_steps,
            "eta_seconds": self.eta_seconds,
            "last_message": self.last_message,
            "updated_at": self.updated_at,
        }


@dataclass
class LongTask:
    id: str
    goal: str
    status: str = "running"   # running, paused, completed, failed, cancelled
    plan: Optional[Plan] = None
    progress: Progress = field(default_factory=Progress)
    checkpoints: List[Dict[str, Any]] = field(default_factory=list)
    heartbeats: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    started_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    last_heartbeat_at: Optional[str] = None
    last_checkpoint_at: Optional[str] = None
    paused_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "id": self.id,
            "goal": self.goal,
            "status": self.status,
            "progress": self.progress.to_dict(),
            "checkpoints": self.checkpoints[-50:],   # keep last 50 for size
            "heartbeats": self.heartbeats[-100:],
            "metadata": self.metadata,
            "started_at": self.started_at,
            "last_heartbeat_at": self.last_heartbeat_at,
            "last_checkpoint_at": self.last_checkpoint_at,
            "paused_at": self.paused_at,
        }
        if self.plan:
            d["plan"] = self.plan.to_dict()
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LongTask":
        prog = Progress(**data.get("progress", {})) if data.get("progress") else Progress()
        plan = Plan.from_dict(data["plan"]) if data.get("plan") else None
        task = cls(
            id=data["id"],
            goal=data["goal"],
            status=data.get("status", "running"),
            plan=plan,
            progress=prog,
            checkpoints=data.get("checkpoints", []),
            heartbeats=data.get("heartbeats", []),
            metadata=data.get("metadata", {}),
            started_at=data.get("started_at", datetime.utcnow().isoformat()),
            last_heartbeat_at=data.get("last_heartbeat_at"),
            last_checkpoint_at=data.get("last_checkpoint_at"),
            paused_at=data.get("paused_at"),
        )
        return task


class LongTaskManager:
    """
    Central manager for long-horizon autonomous work.

    Features implemented and working:
    - start_long_task (with optional auto-planning)
    - heartbeat (with progress + message; written to disk)
    - checkpoint (manual or automatic; integrates PlanCheckpoint + task_queue shape)
    - pause / resume (state survives process restarts)
    - get_status + list_active
    - execute_with_safety (wraps planning.ExecutionEngine + safety.ActionApprovalLayer)
    - Persistence to ~/.agentforge/long_horizon/*.json (cross-reboot / days-weeks survival)
    """

    def __init__(
        self,
        planner: Optional[HierarchicalPlanner] = None,
        approval_layer: Optional[ActionApprovalLayer] = None,
        persist_dir: Path = PERSISTENCE_DIR,
    ):
        self.planner = planner or HierarchicalPlanner()
        self.approval = approval_layer or create_default_approval_layer()
        self.persist_dir = persist_dir
        self.tasks: Dict[str, LongTask] = {}
        self._load_all()

    # ---------------- Persistence ----------------
    def _task_path(self, task_id: str) -> Path:
        return self.persist_dir / f"{task_id}.json"

    def _save(self, task: LongTask):
        path = self._task_path(task.id)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(task.to_dict(), f, indent=2, ensure_ascii=False)

    def _load_all(self):
        self.tasks.clear()
        for p in self.persist_dir.glob("*.json"):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                task = LongTask.from_dict(data)
                self.tasks[task.id] = task
            except Exception:
                continue  # corrupt file — skip, don't crash manager

    # ---------------- Core lifecycle ----------------
    def start_long_task(
        self,
        goal: str,
        *,
        use_planning: bool = True,
        metadata: Optional[Dict] = None,
    ) -> LongTask:
        task_id = str(uuid.uuid4())[:8]
        task = LongTask(
            id=task_id,
            goal=goal,
            metadata=metadata or {},
        )
        if use_planning:
            task.plan = self.planner.decompose(goal, context={"long_horizon": True, "task_id": task_id})
            task.progress.total_steps = max(1, len(task.plan.subtasks))
            task.progress.percent = 0.0

        self.tasks[task_id] = task
        self._save(task)
        self.heartbeat(task_id, "Task started", 0.0)
        return task

    def heartbeat(self, task_id: str, message: str = "", progress_pct: Optional[float] = None):
        if task_id not in self.tasks:
            raise ValueError(f"Unknown long task {task_id}")
        task = self.tasks[task_id]
        now = datetime.utcnow().isoformat()

        if progress_pct is not None:
            task.progress.percent = max(0.0, min(100.0, progress_pct))
        elif task.plan:
            done = sum(1 for s in task.plan.subtasks if s.status == "done")
            task.progress.percent = round(100.0 * done / max(1, len(task.plan.subtasks)), 1)
            task.progress.completed_steps = done
            task.progress.total_steps = len(task.plan.subtasks)

        task.progress.last_message = message[:300]
        task.progress.updated_at = now
        task.last_heartbeat_at = now
        task.heartbeats.append({"ts": now, "msg": message, "pct": task.progress.percent})

        # Auto checkpoint every ~5 heartbeats or on significant progress jumps
        if len(task.heartbeats) % 5 == 0 or (progress_pct and progress_pct % 25 < 1):
            self._auto_checkpoint(task)

        self._save(task)

    def checkpoint(self, task_id: str, state: Dict[str, Any], message: str = ""):
        if task_id not in self.tasks:
            raise ValueError(f"Unknown long task {task_id}")
        task = self.tasks[task_id]
        now = datetime.utcnow().isoformat()

        cp = {
            "id": str(uuid.uuid4())[:8],
            "timestamp": now,
            "message": message,
            "state": state,
        }
        if task.plan:
            cp["plan_state"] = PlanCheckpoint.to_task_checkpoint_state(task.plan)

        task.checkpoints.append(cp)
        task.last_checkpoint_at = now
        self._save(task)

        # Also emit in the shape expected by AgentForge task_queue /checkpoint endpoint
        return {
            "task_id": task_id,
            "checkpoint_id": cp["id"],
            "state": state,
            "plan_progress": cp.get("plan_state"),
        }

    def _auto_checkpoint(self, task: LongTask):
        state = {"auto": True, "progress": task.progress.to_dict()}
        if task.plan:
            state["plan_summary"] = PlanCheckpoint.to_task_checkpoint_state(task.plan)
        self.checkpoint(task.id, state, "auto from heartbeat")

    def pause(self, task_id: str):
        if task_id not in self.tasks:
            return
        task = self.tasks[task_id]
        task.status = "paused"
        task.paused_at = datetime.utcnow().isoformat()
        self._save(task)

    def resume(self, task_id: str) -> Optional[LongTask]:
        if task_id not in self.tasks:
            # Try reload from disk (cross-process / reboot)
            path = self._task_path(task_id)
            if path.exists():
                with open(path) as f:
                    self.tasks[task_id] = LongTask.from_dict(json.load(f))
        task = self.tasks.get(task_id)
        if task and task.status == "paused":
            task.status = "running"
            task.paused_at = None
            self._save(task)
            self.heartbeat(task_id, "Resumed after pause")
        return task

    def get_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        task = self.tasks.get(task_id)
        if not task:
            return None
        d = task.to_dict()
        d["age_hours"] = round((datetime.utcnow() - datetime.fromisoformat(task.started_at)).total_seconds() / 3600, 1)
        return d

    def list_active(self) -> List[Dict[str, Any]]:
        return [self.get_status(tid) for tid in self.tasks if self.tasks[tid].status in ("running", "paused")]

    # ---------------- High-value integration: safe execution ----------------
    def execute_with_safety(
        self,
        task_id: str,
        executor: Callable[[Subtask], Any],
        *,
        parallel: bool = False,
        max_workers: int = 2,
    ) -> Optional[Plan]:
        """
        Execute (or resume) the plan attached to the long task using the planning ExecutionEngine
        wrapped with the safety approval layer on every subtask start.
        """
        task = self.tasks.get(task_id)
        if not task or not task.plan:
            return None

        engine = ExecutionEngine(self.planner)

        def safe_executor(sub: Subtask) -> Any:
            # Safety gate before any real work
            ctx = {
                "subtask_id": sub.id,
                "description": sub.description,
                "metadata": sub.metadata,
                "task_id": task_id,
                "long_horizon": True,
            }
            # Use a conventional action_type based on metadata or description
            action_type = sub.metadata.get("action_type", "subtask_execution")
            decision = self.approval.approve(action_type, ctx)
            if decision.decision == Decision.BLOCK:
                raise RuntimeError(f"Safety block: {decision.reason} (risk={decision.risk_score})")
            if decision.decision == Decision.REQUIRE_APPROVAL:
                # In fully autonomous mode we treat this as failure for the subtask (caller can handle HITL)
                raise RuntimeError(f"Human approval required (not granted): {decision.reason}")

            # Heartbeat on subtask start
            self.heartbeat(task_id, f"Starting: {sub.description[:80]}", None)

            result = executor(sub)

            # Record progress after success
            self.heartbeat(task_id, f"Completed: {sub.description[:80]}")
            return result

        if task.status == "paused":
            self.resume(task_id)

        # Use resume path so it skips already-done subtasks automatically
        final_plan = engine.resume(
            task.plan,
            safe_executor,
            parallel=parallel,
            max_workers=max_workers,
            on_progress=lambda p, s: self.heartbeat(
                task_id,
                f"Progress: {s.id} {s.status}",
                None,
            ),
        )

        # Finalize task
        done = sum(1 for s in final_plan.subtasks if s.status == "done")
        if done == len(final_plan.subtasks):
            task.status = "completed"
            task.progress.percent = 100.0
        elif any(s.status == "failed" for s in final_plan.subtasks):
            task.status = "failed"

        self._save(task)
        return final_plan

    def cancel(self, task_id: str):
        if task_id in self.tasks:
            self.tasks[task_id].status = "cancelled"
            self._save(self.tasks[task_id])
