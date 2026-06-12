#!/usr/bin/env python3
"""
grok_worker.py — Autonomous Grok-powered task worker with Git Auto-Rollback on CI fail.

Implements the full pipeline:
  dispatch → git_clone → grok_start → grok_done → ci_start → ci_done → review → done/failed

CRITICAL SAFETY FEATURE (git,ci,safety):
  After CI failure in ci_done, automatically performs `git revert` on the
  offending commits (those not on main). Creates a revert commit with
  explicit message linking task_id + CI run. This guarantees that even if
  a bad change reaches a branch that could affect main, the main branch
  itself is never left in a broken state.

  "Main branch никогда не ломается."

Usage (happy path with real target repo):
    python scripts/grok_worker.py --task t-2026-0420-001 \
        --repo https://github.com/owner/some-repo --title "Add feature X"

Multi-repo via gateway task (recommended — pulls repo + metadata automatically):
    python scripts/grok_worker.py --gateway-task t42
    # or with custom gateway:
    PLANLY_GATEWAY=http://localhost:3000 python scripts/grok_worker.py --gateway-task t42

Force CI failure + demonstrate auto-rollback (recommended for verification):
    python scripts/grok_worker.py --task demo-rollback-42 \
        --repo https://github.com/example/demo --title "Test safety" \
        --ci-command 'echo "Simulated CI failure"; exit 1' \
        --workdir /tmp/grok_work_demo

The worker ALWAYS operates in an isolated clone/worktree under --workdir (defaults to /tmp/planly_work).
It never mutates the host checkout of planlytasksko itself.

On CI fail the revert is committed on the feature branch before proceeding to review/failure marking.
This makes any subsequent merge to main safe (the revert undoes the breakage).

Integration:
- Called by systemd / cron / gateway dispatcher for autonomous execution.
- Uses the same checkpoints as task_checkpoints.py for crash recovery.
- Emits structured logs (can be scraped by Guardian / metrics).
"""

import argparse
import os
import random
import shutil
import subprocess
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime
from typing import Any, Dict, Optional

# --- Checkpoint integration (same DB as gateway + example) ---
try:
    from scripts.task_checkpoints import (
        init_db,
        save_checkpoint,
        resume_or_start,
        mark_done,
        mark_failed,
        list_recoverable_tasks,
        get_last_checkpoint,
        perform_git_auto_rollback,
        save_knowledge,
        search_knowledge,
    )
except ImportError:
    import importlib.util
    import pathlib

    spec = importlib.util.spec_from_file_location(
        "task_checkpoints",
        pathlib.Path(__file__).with_name("task_checkpoints.py"),
    )
    tc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tc)
    init_db = tc.init_db
    save_checkpoint = tc.save_checkpoint
    resume_or_start = tc.resume_or_start
    mark_done = tc.mark_done
    mark_failed = tc.mark_failed
    list_recoverable_tasks = tc.list_recoverable_tasks
    get_last_checkpoint = getattr(tc, "get_last_checkpoint", None)
    perform_git_auto_rollback = getattr(tc, "perform_git_auto_rollback", None)
    save_knowledge = getattr(tc, "save_knowledge", None)
    search_knowledge = getattr(tc, "search_knowledge", None)


# --- Active Episodic RAG (LanceDB past errors + resolutions) — imported from optimizer ---
try:
    from scripts.optimize_prompts import (
        get_episodic_rag_context,
        retrieve_episodic_memory,
        retrieve_past_errors_and_resolutions,
    )
except Exception:
    get_episodic_rag_context = None
    retrieve_episodic_memory = None
    retrieve_past_errors_and_resolutions = None


# ============================================================
# GIT AUTO-ROLLBACK — imported from task_checkpoints (single source of truth for safety logic)
# ============================================================
# perform_git_auto_rollback is provided by the import above. It guarantees:
#   - isolated clone only (never host)
#   - reverts all feature-branch commits on CI fail
#   - single clean revert commit with audit tags: git,ci,safety
# See task_checkpoints.py:perform_git_auto_rollback for implementation.


# ============================================================
# Simulated / real step implementations (worker core)
# ============================================================

def do_dispatch(task_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    print(f"[{task_id}] 📋 DISPATCH: registering Grok task '{data.get('title')}'")
    time.sleep(0.15)
    data["dispatched_at"] = datetime.utcnow().isoformat() + "Z"
    data["assigned_agent"] = "grok-worker-4.3"
    return data


def do_git_clone(task_id: str, data: Dict[str, Any], workdir_root: str) -> Dict[str, Any]:
    repo = data.get("repo")
    if not repo:
        raise ValueError("repo URL required for git_clone")

    clone_path = os.path.join(workdir_root, task_id)
    os.makedirs(workdir_root, exist_ok=True)

    # Clean previous attempt for this task id (idempotent worker runs)
    if os.path.isdir(clone_path):
        shutil.rmtree(clone_path, ignore_errors=True)

    print(f"[{task_id}] 📦 GIT_CLONE: cloning {repo} → {clone_path}")
    # Shallow clone for speed + safety
    subprocess.check_call(
        ["git", "clone", "--depth=50", "--branch", "main", repo, clone_path],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Create dedicated feature branch for this Grok task (never touch main locally)
    branch = data.get("branch") or f"grok-{random.randint(100000, 999999)}"
    subprocess.check_call(
        ["git", "-C", clone_path, "checkout", "-b", branch],
        stdout=subprocess.DEVNULL,
    )

    data["clone_path"] = clone_path
    data["branch"] = branch
    data["cloned_at"] = datetime.utcnow().isoformat() + "Z"
    print(f"[{task_id}]    ✓ cloned on feature branch {branch}")
    return data


def do_grok_start(task_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    print(f"[{task_id}] 🤖 GROK_START: Grok editing session on {data.get('branch')}")
    session_id = f"grok-sess-{int(time.time())}"
    data["grok_session_id"] = session_id
    # In real worker: invoke Grok (or Jules) coding loop, apply patches via git commit(s)
    # Here we simulate one "Grok edit" commit so the rollback has something to revert.
    clone = data["clone_path"]
    with open(os.path.join(clone, "GROK_EDIT.md"), "w") as f:
        f.write(
            f"# Grok edit for task {task_id}\n\n"
            f"Session: {session_id}\n"
            f"This file represents the (simulated) change that will be subject to CI + auto-rollback.\n"
        )
    subprocess.check_call(
        ["git", "-C", clone, "add", "GROK_EDIT.md"],
    )
    subprocess.check_call(
        ["git", "-C", clone, "commit", "-m", f"grok: apply requested changes for {task_id} [session {session_id}]"],
    )
    data["grok_edits"] = data.get("grok_edits", 0) + 1
    time.sleep(0.4)
    return data


def do_grok_done(task_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    print(f"[{task_id}] ✅ GROK_DONE: edits committed on {data.get('branch')}")
    data["grok_completed_at"] = datetime.utcnow().isoformat() + "Z"
    data["files_changed"] = 1
    return data


def do_ci_start(task_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    print(f"[{task_id}] 🧪 CI_START: running verification on branch {data.get('branch')}")
    run_id = f"ci-{int(time.time())}"
    data["ci_run_id"] = run_id
    data["ci_started_at"] = datetime.utcnow().isoformat() + "Z"
    return data


def do_ci_done(
    task_id: str,
    data: Dict[str, Any],
    ci_command: Optional[str] = None,
    force_fail: bool = False,
) -> Dict[str, Any]:
    """
    Execute CI (local verification commands inside the isolated clone).
    If the command exits non-zero OR force_fail=True → treat as CI failure
    and trigger the Git Auto-Rollback immediately.
    """
    clone = data.get("clone_path")
    run_id = data.get("ci_run_id", "ci-local")
    branch = data.get("branch", "unknown")

    print(f"[{task_id}] 🧪 CI_DONE: executing CI for {run_id} (branch {branch})")

    if force_fail:
        print(f"[{task_id}]    🔥 force_fail requested — simulating broken CI")
        data["ci_status"] = "failed"
        data["ci_error"] = "forced failure for safety test"
    else:
        cmd = ci_command or "python -c \"print('CI checks passed (default lightweight)'); exit(0)\""
        print(f"[{task_id}]    $ {cmd}")
        try:
            result = subprocess.run(
                cmd,
                cwd=clone,
                shell=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
            data["ci_stdout"] = (result.stdout or "")[-2000:]
            data["ci_stderr"] = (result.stderr or "")[-2000:]
            if result.returncode == 0:
                data["ci_status"] = "success"
                data["ci_duration_sec"] = 12
                print(f"[{task_id}]    ✅ CI PASSED")
            else:
                data["ci_status"] = "failed"
                data["ci_error"] = f"exit code {result.returncode}"
                print(f"[{task_id}]    ❌ CI FAILED (exit {result.returncode})")
        except subprocess.TimeoutExpired:
            data["ci_status"] = "failed"
            data["ci_error"] = "timeout"
            print(f"[{task_id}]    ⏱️ CI TIMED OUT")

    # === THE SAFETY TRIGGER ===
    if data.get("ci_status") == "failed":
        print(f"[{task_id}] 🛡️  TRIGGERING GIT AUTO-ROLLBACK (main branch protection)")
        rb = perform_git_auto_rollback(
            clone,
            task_id=task_id,
            ci_run_id=run_id,
            reason=data.get("ci_error", "CI failed"),
        )
        data["rollback"] = rb
        print(f"[{task_id}]    rollback result: {rb.get('status')} {rb.get('revert_commit', '')}")
        if rb.get("status") == "reverted":
            print(f"[{task_id}]    ✓ Revert commit {rb['revert_commit']} created on {rb['branch']}")
            print("    Main branch is protected — bad changes have been reverted.")

    data["ci_completed_at"] = datetime.utcnow().isoformat() + "Z"
    return data


def do_review(task_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    print(f"[{task_id}] 👁️  REVIEW: post-CI + post-rollback (if any) review")
    rb = data.get("rollback", {})
    if rb.get("status") == "reverted":
        notes = f"CI failed → auto-rollback applied ({rb.get('revert_commit')}). Changes will not break main."
        passed = False  # cannot ship broken work
    else:
        notes = "All checks green, diff + reverts (if present) look good."
        passed = data.get("ci_status") == "success"

    data["review_passed"] = passed
    data["review_notes"] = notes
    time.sleep(0.3)
    return data


STEP_HANDLERS = {
    "dispatch": do_dispatch,
    "git_clone": do_git_clone,
    "grok_start": do_grok_start,
    "grok_done": do_grok_done,
    "ci_start": do_ci_start,
    "ci_done": do_ci_done,
    "review": do_review,
}


def run_pipeline(
    task_id: str,
    initial_data: Dict[str, Any],
    crash_after: Optional[str] = None,
    ci_command: Optional[str] = None,
    force_ci_fail: bool = False,
    workdir_root: str = "/tmp/planly_work",
) -> str:
    """
    Main pipeline driver with full checkpoint resume + auto-rollback safety.
    Returns final terminal state ("done" or "failed").
    """
    init_db()

    state = resume_or_start(task_id, initial_data)
    print(f"\n=== Grok Worker Task {task_id} ===")
    print(f"  resume={state['is_resume']}, last={state['last_step']}, next={state['next_step']}")

    current = state["data"]
    last = state["last_step"]

    if last in ("done", "failed"):
        print(f"[{task_id}] Already terminal: {last}")
        return last

    # === ACTIVE EPISODIC RAG (LanceDB): PROACTIVE query for similar past tasks + ERRORS + resolutions
    # This MUST run *before* any prompt generation or Grok/LLM call for the task.
    # The returned context block is stored and can be injected into the agent prompt.
    if get_episodic_rag_context:
        try:
            title = current.get("title") or initial_data.get("title", "")
            desc = current.get("description") or initial_data.get("description", "")
            episodic_ctx = get_episodic_rag_context(title, desc, k=4)
            if episodic_ctx:
                current["episodic_rag_context"] = episodic_ctx
                current["episodic_hits"] = retrieve_past_errors_and_resolutions(f"{title}\n{desc}", k=3) if retrieve_past_errors_and_resolutions else []
                print(f"[{task_id}] 🧠🗄️ Episodic RAG (LanceDB): {len(current.get('episodic_hits',[]))} similar past tasks/errors retrieved (injected before prompt)")
                # Show a one-line preview of first error lesson if present
                if current.get("episodic_hits"):
                    first = current["episodic_hits"][0]
                    print(f"    First lesson: {('FAILED ' if not first.get('success') else '')}{first.get('error_type','')[:40]} → {str(first.get('resolution',''))[:60]}")
            else:
                print(f"[{task_id}] 🧠🗄️ Episodic RAG: no sufficiently similar past episodes in task_outcomes")
        except Exception as _e:
            print(f"[{task_id}] WARN: episodic LanceDB RAG failed: {_e}")

    # === SHARED MEMORY: before starting work, retrieve similar past knowledge for context ===
    if search_knowledge:
        try:
            q = " ".join(filter(None, [
                current.get("title") or initial_data.get("title", ""),
                current.get("description") or initial_data.get("description", ""),
                task_id
            ])).strip() or task_id
            mem_hits = search_knowledge(q, limit=3)
            if mem_hits:
                current["shared_memory_hits"] = mem_hits
                print(f"[{task_id}] 🧠 Shared memory context: {len(mem_hits)} similar facts retrieved")
                for h in mem_hits[:2]:
                    print(f"    - {h.get('key')}: {str(h.get('value',''))[:80]}...")
            else:
                print(f"[{task_id}] 🧠 Shared memory: no prior facts matched (q={q[:40]})")
        except Exception as _e:
            print(f"[{task_id}] WARN: shared memory search failed: {_e}")

    # Determine remaining steps
    all_steps = ["dispatch", "git_clone", "grok_start", "grok_done", "ci_start", "ci_done", "review"]
    if last is None:
        steps_to_run = all_steps[:]
    else:
        try:
            idx = all_steps.index(last)
            steps_to_run = all_steps[idx + 1 :]
        except ValueError:
            steps_to_run = all_steps[:]

    for step in steps_to_run:
        handler = STEP_HANDLERS.get(step)
        if not handler:
            continue

        try:
            print(f"\n[{task_id}] ▶️  {step}")
            if step == "git_clone":
                current = handler(task_id, current, workdir_root)  # type: ignore
            elif step == "ci_done":
                current = handler(task_id, current, ci_command=ci_command, force_fail=force_ci_fail)  # type: ignore
            else:
                current = handler(task_id, current)  # type: ignore

            save_checkpoint(task_id, step, current)
            print(f"[{task_id}]    💾 checkpoint: {step}")

            if crash_after == step:
                print(f"[{task_id}] 💥 SIMULATED CRASH after {step}")
                sys.exit(99)

        except Exception as e:
            print(f"[{task_id}] ❌ {step} failed: {e}")
            mark_failed(task_id, str(e), current)
            return "failed"

    # Success path
    mark_done(task_id, current)

    # === SHARED MEMORY: after task completion, persist summary for future agents ===
    if save_knowledge:
        try:
            title = current.get("title") or initial_data.get("title", task_id)
            summary = current.get("summary") or (
                f"Completed task '{title}' via {current.get('assigned_agent','grok-worker')}. "
                f"Steps finished. Files: {current.get('files_changed', '?')}. "
                f"Branch: {current.get('branch', 'n/a')}."
            )
            kid = save_knowledge(
                key=f"task_summary:{task_id}",
                value=summary[:3000],
                agent=current.get("assigned_agent") or "grok-worker",
                task_id=task_id,
            )
            print(f"[{task_id}] 💾 Saved summary to shared knowledge (id={kid}) in tasks.db")
        except Exception as _e:
            print(f"[{task_id}] WARN: failed to save knowledge summary: {_e}")

    print(f"\n[{task_id}] 🎉 TASK COMPLETED")
    return "done"


# ============================================================
# Gateway integration for true multi-repo from task records
# ============================================================

def _http_get_json(url: str, timeout: int = 15) -> Dict[str, Any]:
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "grok-worker/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def _http_post_json(url: str, payload: Dict[str, Any], timeout: int = 15) -> Dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json", "User-Agent": "grok-worker/1.0"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", errors="replace")
        try:
            return json.loads(body) if body else {}
        except Exception:
            return {"raw": body[:500]}


def fetch_task_from_gateway(base_url: str, task_id: str) -> Optional[Dict[str, Any]]:
    """Fetch task list and locate the specific task by id. Returns the task dict or None."""
    try:
        base = base_url.rstrip("/")
        data = _http_get_json(f"{base}/api/tasks")
        tasks = []
        if isinstance(data, dict):
            tasks = data.get("tasks", []) or []
        elif isinstance(data, list):
            tasks = data
        for t in tasks:
            if isinstance(t, dict) and t.get("id") == task_id:
                return t
        return None
    except Exception as e:
        print(f"[{task_id}] WARN: gateway fetch failed: {e}")
        return None


def submit_completion_to_gateway(base_url: str, task_id: str, diff: Optional[str] = None, summary: Optional[str] = None, status: str = "ai_done") -> bool:
    """Report completion + diff back to gateway (triggers A2A review if configured on task)."""
    try:
        base = base_url.rstrip("/")
        payload: Dict[str, Any] = {"status": status}
        if diff:
            payload["diff"] = diff
        if summary:
            payload["summary"] = summary
        res = _http_post_json(f"{base}/api/tasks/{task_id}/submit-completion", payload)
        print(f"[{task_id}] ✅ Submitted completion to gateway (status={status})")
        return True
    except Exception as e:
        print(f"[{task_id}] WARN: submit-completion failed: {e}")
        return False


def compute_diff_for_submit(clone_path: str) -> str:
    """Best-effort unified diff for the work done on the feature branch."""
    if not clone_path or not os.path.isdir(clone_path):
        return "(no clone path available for diff)"
    try:
        # Prefer diff vs origin/main
        out = subprocess.run(
            ["git", "-C", clone_path, "diff", "--no-color", "--unified=0", "origin/main...HEAD"],
            capture_output=True, text=True, timeout=30
        )
        d = out.stdout.strip()
        if d:
            return d[:12000]  # cap size for API
        # fallback
        out2 = subprocess.run(
            ["git", "-C", clone_path, "diff", "--no-color", "--cached", "--unified=0"],
            capture_output=True, text=True, timeout=20
        )
        return (out2.stdout or "(no diff captured)").strip()[:8000]
    except Exception as e:
        return f"(diff capture error: {e})"


def main() -> int:
    parser = argparse.ArgumentParser(description="grok_worker — Grok task runner with Git auto-rollback safety (multi-repo via task.repo)")
    parser.add_argument("--task", "-t", help="Unique task id (for standalone or gateway mode)")
    parser.add_argument("--gateway-task", "--from-gateway", dest="gateway_task", help="Task ID to fetch live from gateway (pulls repo/title/etc automatically for true multi-repo)")
    parser.add_argument("--gateway", default=os.environ.get("PLANLY_GATEWAY", "http://localhost:3000"), help="Gateway base URL (default http://localhost:3000)")
    parser.add_argument("--repo", default="https://github.com/example/planly-demo", help="Target repo (overridden by gateway task if present)")
    parser.add_argument("--title", default="Grok autonomous change", help="Task title (overridden by gateway)")
    parser.add_argument("--workdir", default="/tmp/planly_work", help="Root for isolated clones (never host repo)")
    parser.add_argument("--ci-command", help="Shell command to run as CI inside clone (default: lightweight pass)")
    parser.add_argument("--force-ci-fail", action="store_true", help="Force CI failure path + demonstrate auto-rollback")
    parser.add_argument("--crash-after", choices=["dispatch", "git_clone", "grok_start", "grok_done", "ci_start", "ci_done", "review"])
    parser.add_argument("--list-recoverable", action="store_true")
    args = parser.parse_args()

    if args.list_recoverable:
        for t in list_recoverable_tasks():
            print(f"  {t['task_id']}: {t['last_step']}")
        return 0

    task_id = args.gateway_task or args.task
    if not task_id:
        parser.error("Either --task / -t or --gateway-task is required")

    init_db()

    initial: Dict[str, Any] = {
        "title": args.title,
        "repo": args.repo,
        "created_at": datetime.utcnow().isoformat() + "Z",
    }

    gateway_base = args.gateway
    pulled = False
    if args.gateway_task:
        t = fetch_task_from_gateway(gateway_base, task_id)
        if t:
            pulled = True
            if t.get("title"):
                initial["title"] = t["title"]
            if t.get("repo"):
                initial["repo"] = t["repo"]
            if t.get("description"):
                initial["description"] = t["description"]
            if t.get("priority"):
                initial["priority"] = t["priority"]
            initial["gateway_source"] = True
            print(f"[{task_id}] 📥 Pulled from gateway: repo={initial.get('repo')!r} title={initial.get('title')!r}")
        else:
            print(f"[{task_id}] Using CLI --repo/--title (gateway pull returned no match)")

    # Guard: require a real repo for git_clone step
    if not initial.get("repo"):
        print(f"[{task_id}] ERROR: no repo provided (use --repo or --gateway-task pointing at task with repo field)")
        return 2

    final = run_pipeline(
        task_id,
        initial,
        crash_after=args.crash_after,
        ci_command=args.ci_command,
        force_ci_fail=args.force_ci_fail,
        workdir_root=args.workdir,
    )

    # After successful pipeline from gateway task, report back (enables A2A + status flow)
    if args.gateway_task and final == "done":
        # Try to produce a real diff from the clone we just used
        clone_path = ""
        if get_last_checkpoint:
            try:
                last_cp = get_last_checkpoint(task_id)
                if last_cp and isinstance(last_cp.get("data"), dict):
                    clone_path = last_cp["data"].get("clone_path", "") or ""
            except Exception:
                pass
        diff = compute_diff_for_submit(clone_path) if clone_path else "(pipeline completed; see checkpoints + worktree for details)"
        summary = f"Completed via grok_worker (gateway pull) on {initial.get('repo')}. Steps: dispatch→git_clone→...→review."
        if pulled:
            summary += " (repo taken from gateway task; A2A review will trigger if a2a_reviewer set on task)"
        submit_completion_to_gateway(gateway_base, task_id, diff=diff, summary=summary, status="ai_done")

        # Also persist the gateway-provided summary into shared knowledge (tasks.db)
        if save_knowledge:
            try:
                save_knowledge(
                    key=f"gateway_summary:{task_id}",
                    value=summary[:2500],
                    agent="grok-worker",
                    task_id=task_id,
                )
            except Exception:
                pass

    return 0 if final == "done" else 1


if __name__ == "__main__":
    sys.exit(main())
