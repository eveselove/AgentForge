"""
!!! AGGRESSIVE FINAL DEPRECATION + PHASE 4 CLEANUP PREP (RUST_FULL_MIGRATION_PLAN.md) !!!
Evaluation Runner for AgentForge (Phase 0 → Phase 1 transition).

Goal: Reliable, repeatable execution of benchmark tasks with good signal.

DEPRECATION NOTE (Phase 3/4 FINAL, RUST_FULL_MIGRATION_PLAN.md + PHASE4_REMOVAL_PLAN.md):
    The FLYWHEEL_REMOVED_TIER2 (use runner) orchestration layer (proposal/candidate/continuous/A/B glue) is AGGRESSIVELY DEPRECATED
    in favor of pure Rust (agentforge-runner FLYWHEEL_REMOVED_TIER2 (use runner)-step / continuous / candidate).
    This runner participates indirectly via post_process (FLYWHEEL_REMOVED_TIER2 (use runner) glue paths deprecated).
    When is_pure_rust_FLYWHEEL_REMOVED_TIER2 (use runner)() (Phase 4 EVEN STRONGER hardened guard from utils),
    Python FLYWHEEL_REMOVED_TIER2 (use runner) orchestration is short-circuited.
    USE DIRECT: agentforge-runner FLYWHEEL_REMOVED_TIER2 (use runner)-step --real-data --ingest
    See learning/utils.py (full list + strengthened guards) + PHASE4_REMOVAL_PLAN.md
"""
import json
import subprocess
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

from .schemas import BenchmarkTask, EvaluationResult, TaskOutcome
from .utils import create_evaluation_task_in_agentforge
from .mappings import save_mapping, update_status, get_real_task_id
from .history import record_run
from .prm import ProcessRewardModel
from .trajectory import find_trajectory_file, load_trajectory
from pathlib import Path
import json
import os

_DEFAULT_RESULTS_DIR = Path(__file__).parent / "results"
EVAL_RESULTS_DIR = Path(
    os.environ.get("AGENTFORGE_EVAL_RESULTS_DIR", str(_DEFAULT_RESULTS_DIR))
)
EVAL_RESULTS_DIR.mkdir(parents=True, exist_ok=True)

AGENTFORGE_API = "http://localhost:9090"


def _wait_for_agentforge_task(real_task_id: str, timeout_minutes: int = 90, poll_interval: int = 20) -> Dict[str, Any]:
    """
    Poll the AgentForge API with nice progress output until the task finishes or times out.
    """
    import urllib.request

    deadline = time.time() + (timeout_minutes * 60)
    start_time = time.time()
    print(f"[Eval] Waiting for real task {real_task_id} (timeout: {timeout_minutes}m)...")

    current_interval = poll_interval
    attempt = 0

    while time.time() < deadline:
        attempt += 1
        elapsed = int(time.time() - start_time)

        try:
            req = urllib.request.Request(f"{AGENTFORGE_API}/tasks/{real_task_id}")
            with urllib.request.urlopen(req, timeout=8) as resp:
                task_data = json.loads(resp.read().decode())

            status = task_data.get("status", "unknown")
            print(f"[Eval]   [{elapsed}s] Status: {status}")

            if status in ("done", "review", "failed"):
                update_status(task_data.get("id") or real_task_id, status)
                return task_data

        except Exception as e:
            print(f"[Eval]   [{elapsed}s] Polling warning: {e}")

        time.sleep(current_interval)
        current_interval = min(current_interval + 3, 45)  # gentle backoff

    print(f"[Eval]   Timeout after {timeout_minutes}m for task {real_task_id}")
    update_status(real_task_id, "timeout")
    return {"status": "timeout", "id": real_task_id}


def _run_command(cmd: str, cwd: str, timeout: int = 300) -> tuple[int, str, str]:
    """Run shell command safely with timeout."""
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return 124, "", "Command timed out after timeout"
    except Exception as e:
        return 1, "", str(e)


def run_benchmark_task(
    task: BenchmarkTask,
    agent: str = "grok",
    timeout_minutes: int = 90,
    simulate: bool = True,
    wait: bool = False,
) -> EvaluationResult:
    """
    Run a single benchmark task and return a rich EvaluationResult.

    Parameters:
        simulate: If True, runs in fast simulation mode.
        wait:     If True and simulate=False, will wait for the real task to finish
                  (using polling) and then attempt verification automatically.
    """
    start_time = time.time()
    run_id = f"eval-{uuid.uuid4().hex[:8]}"

    print(f"\n[Eval] ▶ Starting benchmark: {task.id}")
    print(f"[Eval]    Title     : {task.title}")
    print(f"[Eval]    Agent     : {agent}")
    print(f"[Eval]    Difficulty: {task.difficulty} | Category: {task.category}")

    real_task_id = None
    verification_passed = False
    verification_output = ""
    error_msg = None
    task_data = None

    if simulate:
        print("[Eval]    Running in SIMULATION mode")
        time.sleep(1.2)
        verification_passed = False
        verification_output = "Simulation mode — no real execution performed."
    else:
        print("[Eval]    Dispatching real task to AgentForge...")
        real_task_id = create_evaluation_task_in_agentforge(
            title=task.title,
            description=task.to_prompt_context(),
            tags=["evaluation", "benchmark", task.category] + task.tags,
            preferred_agent=agent,
        )
        if real_task_id:
            save_mapping(task.id, real_task_id, agent)
            print(f"[Eval]    → Real AgentForge task created: {real_task_id}")

            if wait:
                task_data = _wait_for_agentforge_task(real_task_id, timeout_minutes=timeout_minutes)
                print(f"[Eval]    Task finished with status: {task_data.get('status')}")
            else:
                print("[Eval]    Task is running. Use wait=True to block until completion.")
                print("[Eval]    Trajectory is being captured automatically.")
        else:
            print("[Eval]    Failed to create real task. Falling back to simulation-like behavior.")
            verification_output = "Failed to dispatch real task."

    # Real task handling + verification
    real_result_text = ""
    if not simulate and wait and task_data:
        real_result_text = task_data.get("result", "") or ""
        real_status = task_data.get("status", "")

        # If the real task failed, we can use that as a signal
        if real_status == "failed" and not verification_passed:
            error_msg = (error_msg or "") + f"\n[Real Task Failed] {real_result_text[:500]}"

        print(f"[Eval]    Real task status: {real_status}")

    if task.verification_command:
        print(f"[Eval]    Running verification command...")
        code, stdout, stderr = _run_command(
            task.verification_command,
            cwd=task.repo_path,
            timeout=timeout_minutes * 60,
        )
        verification_passed = (code == 0)
        verification_output = (stdout + "\n" + stderr).strip()
        if not verification_passed:
            error_msg = (error_msg or "") + "\n" + verification_output[:1200]
    else:
        if task.verification == "manual_review":
            verification_passed = False
            verification_output = "Manual review required."

    duration = time.time() - start_time
    outcome = TaskOutcome.SUCCESS if verification_passed else TaskOutcome.FAILED

    result = EvaluationResult(
        task_id=task.id,
        agent=agent,
        outcome=outcome,
        duration_seconds=round(duration, 1),
        steps_taken=1,
        tool_calls=0,
        cost_usd=0.0,
        error_message=error_msg,
        real_task_id=real_task_id,
    )

    # === Phase 1: Auto-attach trajectory + PRM scores (now uses canonical loader + find_trajectory_file) ===
    try:
        traj_path = None
        # Prefer real_task_id (from dispatched AgentForge task) then benchmark id
        if real_task_id:
            p = find_trajectory_file(real_task_id)
            if not p:
                p = find_trajectory_file(str(real_task_id)[:8])
            if p:
                traj_path = str(p)
        if not traj_path:
            p = find_trajectory_file(task.id)
            if p:
                traj_path = str(p)

        if traj_path:
            result.trajectory_path = traj_path
            # load_trajectory normalizes + optionally computes PRM in one shot
            # PRM (heuristic or LLM-judge via AGENTFORGE_PRM_USE_LLM_JUDGE=1 env)
            loaded = load_trajectory(traj_path, include_prm=True)
            pr = loaded.get("prm_result") or {}
            if pr and "overall_prm_score" in pr:
                result.prm_overall_score = pr.get("overall_prm_score")
                result.prm_high_quality_steps = pr.get("num_high_quality_steps")
                result.prm_low_quality_steps = pr.get("num_low_quality_steps")
                result.prm_suggestions = pr.get("suggestions_for_improvement", [])[:3]
            # Also enrich basic counts from trajectory if missing
            evs = loaded.get("events", [])
            if result.steps_taken in (0, 1):
                result.steps_taken = len(evs)
            if result.tool_calls == 0:
                result.tool_calls = sum(1 for e in evs if (e.get("type") or (e.get("data") or {}).get("type")) == "tool_call")
    except Exception:
        pass  # Never break runs for observability

    # Persist result
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    result_path = EVAL_RESULTS_DIR / f"{task.id}_{agent}_{timestamp}.json"
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(result.__dict__, f, indent=2, default=str)

    # Update mapping with final outcome if this was a real run
    if real_task_id:
        update_status(real_task_id, outcome.value, {
            "evaluation_result_path": str(result_path)
        })

    # Record to longitudinal history (this is key for tracking improvement over time)
    # Phase 1: include PRM fields via extra for longitudinal process quality tracking
    extra = {}
    if result.prm_overall_score is not None:
        extra = {
            "prm_overall_score": result.prm_overall_score,
            "prm_high_quality_steps": result.prm_high_quality_steps,
            "prm_low_quality_steps": result.prm_low_quality_steps,
        }
    record_run(
        benchmark_id=task.id,
        agent=agent,
        outcome=outcome.value,
        duration_seconds=duration,
        real_task_id=real_task_id,
        mode="real" if real_task_id else "simulated",
        extra=extra if extra else None,
    )

    print(f"[Eval]    Result    : {outcome.value} (took {duration:.1f}s)")
    print(f"[Eval]    Saved to  : {result_path}")

    # Phase 1: Optional post-process hook for full enrichment (trajectory + PRM + mapping)
    try:
        from .post_process import post_process_task
        if real_task_id:
            post_process_task(real_task_id)
    except Exception:
        pass

    # TODO(Phase 1 Deprecation Expander): per RUST_FULL_MIGRATION_PLAN.md
    # The post_process_task call above can trigger FLYWHEEL_REMOVED_TIER2 (use runner) orchestration (Python path).
    # When is_pure_rust_FLYWHEEL_REMOVED_TIER2 (use runner)(), post_process already short-circuits some glue
    # (see eval/post_process.py + phase2_3_integration). Future expansions may
    # add explicit deprecation warning here for FLYWHEEL_REMOVED_TIER2 (use runner)-related benchmark runs.
    # eval/runner remains supported (hybrid) while orchestration layer migrates.

    return result


# === General post-processing hook (Phase 1 unification) ===
def post_process_run(
    result: EvaluationResult,
    trajectory_path: Optional[str] = None,
    force_prm: bool = True,
) -> EvaluationResult:
    """
    Reusable post-run hook.
    - Attaches/fixes trajectory_path + PRM scores using canonical loader.
    - Can be called from CLI, post_process.py, or after custom runs.
    - Idempotent and safe.
    """
    if not trajectory_path:
        trajectory_path = result.trajectory_path

    if not trajectory_path:
        # Try to discover
        p = find_trajectory_file(result.task_id)
        if not p and result.real_task_id:
            p = find_trajectory_file(result.real_task_id)
        if p:
            trajectory_path = str(p)
            result.trajectory_path = trajectory_path

    if trajectory_path and force_prm:
        try:
            loaded = load_trajectory(trajectory_path, include_prm=True)
            pr = loaded.get("prm_result") or {}
            if "overall_prm_score" in pr:
                result.prm_overall_score = pr.get("overall_prm_score")
                result.prm_high_quality_steps = pr.get("num_high_quality_steps")
                result.prm_low_quality_steps = pr.get("num_low_quality_steps")
                result.prm_suggestions = (pr.get("suggestions_for_improvement") or [])[:3]
            evs = loaded.get("events", [])
            if result.steps_taken <= 1:
                result.steps_taken = len(evs)
            tc = sum(1 for e in evs if (e.get("type") or (e.get("data") or {}).get("type", "")) in ("tool_call", "tool"))
            if result.tool_calls == 0:
                result.tool_calls = tc
        except Exception:
            pass  # best effort
    return result


def load_benchmark_task(path: str) -> BenchmarkTask:
    """Load a benchmark task from JSON file."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return BenchmarkTask(**data)


if __name__ == "__main__":
    # Quick manual test
    example = BenchmarkTask(
        id="example-001",
        title="Simple test task",
        description="Verify that evaluation runner works",
        verification_command="echo 'Verification would run here'",
        difficulty="easy",
        category="test",
    )
    run_benchmark_task(example, agent="grok")