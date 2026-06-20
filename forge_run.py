#!/usr/bin/env python3
"""
forge_run.py — the foreground, bounded, commit-preserving claim-loop.

This is forge's OWN thin claim-loop. It reuses the stock antigravity_worker's
exact agy invocation contract (same flags, same PROJECT_DIR cwd where the OAuth
token lives, same worktree-per-task scheme) but adds the three things the stock
worker is missing for gating + merge:

  1. it COMMITS the agy work (the stock worker never commits),
  2. it PRESERVES the branch as forge/<batch_id>/<task_id> (the stock worker
     force-deletes branch + worktree in its finally block),
  3. it runs per-repo quality GATES against the still-live worktree.

It claims with a distinct agent id (forge-<batch_id>) and a matching `preferred`
filter so the stock antigravity_worker pool — which claims with no `preferred`
and only matches empty/auto/grok/antigravity — never contends for forge tasks.

Robustness vs the gateway zombie reclaimer: a forge task stays in_progress for
the WHOLE agy run AND the gate run. The gateway resets any in_progress task
older than ZOMBIE_TIMEOUT_MINUTES (default 25) back to pending. To prevent it
re-handing a still-running task to ourselves (double-execution / worktree
collision), forge_run (a) heartbeats the gateway every HEARTBEAT_INTERVAL_S to
refresh updated_at, (b) CAPS the agy stage so agy+gate budget stays under the
reclaimer threshold, and (c) detects a task it believes is in-flight being
reset to pending and treats it as a terminal 'reclaimed' attempt rather than
blindly re-claiming.

NO DAEMON: this process runs in the FOREGROUND as a child of Claude's held-open
ssh Bash (launched via run_in_background). On erbox `loginctl` shows Linger=yes
so a detached child also survives ssh teardown via the user manager.

Usage:
  forge_run.py <batch_id> [--parallel N] [--gate on|off]

stdlib only.
"""

import argparse
import os
import signal
import subprocess
import sys
import threading
import time

import forge_lib as F

_shutdown = threading.Event()
_worktree_add_lock = threading.Lock()  # serialize `git worktree add` per repo
_auth_stop = threading.Event()


def _handle_signal(signum, frame):
    _shutdown.set()
    F.eprint("forge_run: shutdown signal received, draining in-flight tasks...")


signal.signal(signal.SIGTERM, _handle_signal)
signal.signal(signal.SIGINT, _handle_signal)


# ----------------------------------------------------------------------------
# Manifest reconciliation (cross-process locked via forge_lib.update_manifest_node)
# ----------------------------------------------------------------------------


def update_node(batch_id, task_id, **fields):
    F.update_manifest_node(batch_id, task_id, lambda n: n.update(fields))


def update_gate(batch_id, task_id, gate):
    F.update_manifest_node(batch_id, task_id, lambda n: n.__setitem__("gate", gate))


def get_status(batch_id, task_id):
    m = F.load_manifest(batch_id)
    if not m:
        return None
    node = m["tasks"].get(task_id)
    return node.get("status") if node else None


# ----------------------------------------------------------------------------
# agy invocation (reuses the stock worker contract exactly)
# ----------------------------------------------------------------------------


def build_agy_cmd(model, worktree_dir, prompt):
    flags = ["--dangerously-skip-permissions", "--model", model]
    full_prompt = f"WORKING DIRECTORY: {worktree_dir}\n\n{prompt}"
    return [F.AGY_BIN, *flags, "--add-dir", worktree_dir, "--print", full_prompt]


def select_model_for(node, manifest):
    """
    Mirror the stock worker's model preference (without its rate-limit state):
    complex/critical/complex-tags => complex model, else simple model. The
    actual model strings come from the manifest 'models' field (defaulting to
    the stock-worker MODEL_GROUPS values) so we never hardcode an invented
    version into the dispatch path.
    """
    models = manifest.get("models") or {}
    m_complex = models.get("complex", F.DEFAULT_MODEL_COMPLEX)
    m_simple = models.get("simple", F.DEFAULT_MODEL_SIMPLE)
    complexity = (node.get("complexity") or "").lower()
    tags = [str(t).lower() for t in (node.get("tags") or [])]
    COMPLEX_TAGS = {"architecture", "analysis", "refactor", "complex",
                    "security", "perf", "performance", "design", "protocol"}
    if complexity == "complex" or any(t in COMPLEX_TAGS for t in tags):
        return m_complex
    return m_simple


# ----------------------------------------------------------------------------
# Gateway heartbeat (defeats the zombie reclaimer for long in-flight tasks)
# ----------------------------------------------------------------------------


def _heartbeat_loop(task_id, agent_id, stop_evt):
    """
    Periodically PATCH the gateway task in_progress->in_progress (same agent) to
    refresh updated_at, so the zombie reclaimer never resets a task we are still
    actively running. The gateway CAS accepts in_progress->in_progress from the
    same agent (returns 200, not 409). Runs until stop_evt is set. stderr-only,
    zero Claude context cost.
    """
    # First heartbeat after one interval (the claim already set updated_at=now).
    while not stop_evt.wait(F.HEARTBEAT_INTERVAL_S):
        F.api_request("PATCH", f"/tasks/{task_id}",
                      {"status": "in_progress", "assigned_agent": agent_id})


# ----------------------------------------------------------------------------
# Per-task execution
# ----------------------------------------------------------------------------


def execute_task(manifest, task_id, agent_id, gate_on):
    batch_id = manifest["batch_id"]
    repo = manifest["repo_path"]
    base_ref = manifest.get("base_sha") or manifest["base_branch"]
    gate_profile = manifest["gate_profile"]

    node = manifest["tasks"][task_id]
    title = node.get("short_title", "")
    desc = node.get("full_description", "")
    # Per-task agy timeout, capped so agy + gate budget < zombie threshold.
    raw_ptt = node.get("per_task_timeout_s") or F.DEFAULT_PER_TASK_TIMEOUT
    agy_timeout, gate_budget = F.effective_caps(raw_ptt)
    model = select_model_for(node, manifest)

    forge_branch = node["branch"]  # forge/<batch_id>/<task_id>
    proj_name = os.path.basename(repo)
    worktree_dir = os.path.join(
        os.path.dirname(repo), f"{proj_name}_{task_id}"
    )
    task_log = F.task_log_path(task_id)

    update_node(batch_id, task_id, status="running", model_used=model,
                started_at=F.now_iso())

    # --- start the gateway heartbeat for this task ---
    hb_stop = threading.Event()
    hb_thread = threading.Thread(
        target=_heartbeat_loop, args=(task_id, agent_id, hb_stop), daemon=True)
    hb_thread.start()

    try:
        _execute_task_inner(manifest, batch_id, repo, base_ref, gate_profile,
                            task_id, node, title, desc, model, agy_timeout,
                            gate_budget, forge_branch, worktree_dir, task_log,
                            agent_id, gate_on)
    finally:
        hb_stop.set()


def _execute_task_inner(manifest, batch_id, repo, base_ref, gate_profile,
                        task_id, node, title, desc, model, agy_timeout,
                        gate_budget, forge_branch, worktree_dir, task_log,
                        agent_id, gate_on):
    # --- create the worktree off the PINNED base commit (serialized add) ---
    with _worktree_add_lock:
        if os.path.exists(worktree_dir):
            F.git(repo, "worktree", "remove", "-f", worktree_dir)
        F.git(repo, "branch", "-D", forge_branch)  # ignore if absent
        rc, _, err = F.git(repo, "worktree", "add", "-b", forge_branch,
                           worktree_dir, base_ref)
        if rc != 0:
            update_node(batch_id, task_id, status="failed",
                        summary=f"worktree add failed: {F.truncate(err,120)}")
            reconcile_gateway(task_id, "failed", "forge: worktree add failed",
                              0, agent_id)
            return

    # --- run agy from PROJECT_DIR (where OAuth lives), same as stock worker ---
    cmd = build_agy_cmd(model, worktree_dir, _build_prompt(title, desc, node))
    start = time.time()
    exit_code = 0
    try:
        with open(task_log, "w", encoding="utf-8") as logf:
            logf.write(f"[forge] Task: {task_id}\n")
            logf.write(f"[forge] Batch: {batch_id}\n")
            logf.write(f"[forge] Model: {model}\n")
            logf.write(f"[forge] Worktree: {worktree_dir}\n")
            logf.write(f"[forge] Branch: {forge_branch}\n")
            logf.write(f"[forge] Base: {base_ref}\n")
            logf.write(f"[forge] Start: {F.now_iso()}\n\n")
            logf.flush()
            try:
                proc = subprocess.run(
                    cmd,
                    stdout=logf,
                    stderr=subprocess.STDOUT,
                    cwd=repo,  # PROJECT_DIR — OAuth token lives here
                    env={
                        **os.environ,
                        "HOME": os.path.expanduser("~"),
                        "SSH_TTY": os.environ.get("SSH_TTY", "/dev/pts/0"),
                    },
                    timeout=agy_timeout,
                )
                exit_code = proc.returncode
            except subprocess.TimeoutExpired:
                exit_code = -9
    except Exception as e:
        duration = time.time() - start
        update_node(batch_id, task_id, status="failed", duration_s=round(duration, 1),
                    summary=f"launch error: {F.truncate(str(e),120)}")
        reconcile_gateway(task_id, "failed",
                          f"forge: launch error — {str(e)[:160]}", duration, agent_id)
        _cleanup_worktree_only(repo, worktree_dir)
        return

    duration = time.time() - start

    # --- classify failure types BEFORE committing ---
    if exit_code == -9 or duration >= agy_timeout:
        update_node(batch_id, task_id, status="timeout",
                    duration_s=round(duration, 1),
                    summary=f"timeout after {int(duration)}s")
        reconcile_gateway(task_id, "failed",
                          f"forge: timeout ({int(duration)}s, model={model})",
                          duration, agent_id)
        _cleanup_worktree_only(repo, worktree_dir)
        return

    # Rate-limit can occur even on exit 0 (markers in log). Check markers first.
    rate_limited = F.log_has_rate_limit(task_id)

    if exit_code != 0:
        if F.detect_auth_failure(task_id, exit_code, duration):
            _auth_stop.set()
            update_node(batch_id, task_id, status="auth",
                        duration_s=round(duration, 1),
                        summary="agy auth failure — batch halted")
            reconcile_gateway(task_id, "failed",
                              f"forge: auth failure (exit={exit_code})",
                              duration, agent_id)
            _cleanup_worktree_only(repo, worktree_dir)
            return
        if rate_limited:
            _handle_rate_limit(batch_id, task_id, node, model, duration,
                               repo, worktree_dir)
            return
        update_node(batch_id, task_id, status="failed",
                    duration_s=round(duration, 1),
                    summary=f"agy exit={exit_code} after {int(duration)}s")
        reconcile_gateway(task_id, "failed",
                          f"forge: exit={exit_code}, {int(duration)}s, model={model}",
                          duration, agent_id)
        _cleanup_worktree_only(repo, worktree_dir)
        return

    # exit 0 but rate-limit markers present => treat as rate-limited, not success.
    if rate_limited:
        _handle_rate_limit(batch_id, task_id, node, model, duration,
                           repo, worktree_dir)
        return

    # --- SUCCESS path: COMMIT, then GATE ---
    commit_sha = _commit_work(worktree_dir, task_id, title)
    files, add, rem = F.numstat(repo, base_ref, forge_branch)

    summary = F.extract_summary(task_id) or _synth_summary(files, add, rem)

    update_node(batch_id, task_id, status="review", duration_s=round(duration, 1),
                commit_sha=commit_sha, files_changed_count=files,
                lines_added=add, lines_removed=rem, summary=summary)

    # --- gates against the live worktree, under an overall budget ---
    if gate_on:
        gate = F.run_gates(worktree_dir, gate_profile, budget_s=gate_budget)
    else:
        gate = {"verdict": "n/a", "first_failing_check": None,
                "first_error_line": None, "gates_run": [], "dur_s": 0.0,
                "ran_at": F.now_iso(), "gates_disabled": True}
    update_gate(batch_id, task_id, gate)

    verdict = gate["verdict"]
    if verdict == "pass":
        update_node(batch_id, task_id, status="done")
        reconcile_gateway(task_id, "review",
                          f"AntigravityWorker: {int(duration)}s (model={model}) ✅ | forge:gate ok",
                          duration, agent_id)
        F.api_request("POST", f"/tasks/{task_id}/review")
    elif verdict == "n/a":
        # No runnable gate: keep as review. accept treats n/a as not-mergeable
        # by default, but `accept --allow-nagate` (and gates-off batches) accept it.
        update_node(batch_id, task_id, status="review")
        reconcile_gateway(task_id, "review",
                          f"AntigravityWorker: {int(duration)}s (model={model}) ✅ | forge:gate n/a",
                          duration, agent_id)
    elif verdict == "gate_timeout":
        update_node(batch_id, task_id, status="gate_timeout")
        reconcile_gateway(task_id, "failed",
                          f"forge:gate TIMEOUT check={gate['first_failing_check']}",
                          duration, agent_id)
    else:  # fail
        update_node(batch_id, task_id, status="gatefail")
        reconcile_gateway(task_id, "failed",
                          f"forge:gate FAIL check={gate['first_failing_check']}",
                          duration, agent_id)
    # NOTE: worktree + branch are PRESERVED for gating/diff/accept. Removed by
    # `forge teardown` / `forge reject`, never here.


def _handle_rate_limit(batch_id, task_id, node, model, duration, repo,
                       worktree_dir):
    """
    Rate-limit handling with an attempt cap so an RL storm drains to a terminal
    state instead of looping forever. Below the cap: return the gateway task to
    pending (assigned_agent null) for a future forge claim. At/over the cap:
    mark terminal rate_limited so the batch can drain.
    """
    attempts = (node.get("rl_attempts") or 0) + 1
    if attempts >= F.MAX_RL_ATTEMPTS:
        update_node(batch_id, task_id, status="rate_limited",
                    rl_attempts=attempts, duration_s=round(duration, 1),
                    summary=f"rate-limited {attempts}x (cap reached); terminal")
        reconcile_gateway(task_id, "failed",
                          f"forge: rate-limited {attempts}x (cap), model={model}",
                          duration, None)
    else:
        update_node(batch_id, task_id, status="pending",
                    rl_attempts=attempts,
                    summary=f"rate-limited (attempt {attempts}); requeued")
        reconcile_gateway(task_id, "pending",
                          f"rate_limit:{model}:{int(duration)}s", duration, None)
    _cleanup_worktree_only(repo, worktree_dir)


def _build_prompt(title, desc, node):
    prompt = title
    if desc:
        prompt += f". {desc}"
    tags = node.get("tags") or []
    if tags:
        prompt += f". Tags: {','.join(tags)}"
    return prompt


def _commit_work(worktree_dir, task_id, title):
    """
    git add -A && commit with forge identity. Returns commit sha or ''.

    The commit message MUST satisfy the agentforge repo's mandatory
    traceability check (bin/validate-commit-msg PATTERN
    'task[[:space:]/:._-]*[0-9a-fA-F]{6,}' AND the pre-commit fallback
    'task[[:space:]]*[0-9a-f]{6,}'). We therefore include a 'task <8hex>'
    trailer with a SPACE separator and lowercase hex so BOTH patterns match.
    """
    # gateway ids look like 'task-8fbad4cc'; extract the hex part for the trailer.
    hexpart = task_id.split("-")[-1][:8].lower()
    trailer = f"task {hexpart}"
    F.git(worktree_dir, "add", "-A")
    rc, out, _ = F.git(worktree_dir, "status", "--porcelain")
    base_args = ["-c", "user.email=forge@agentforge", "-c", "user.name=forge",
                 "commit"]
    if rc == 0 and not out.strip():
        # nothing changed; empty commit so the branch is real & diffable
        msg = f"forge {F.truncate(title,55)} (no file changes)\n\n{trailer}"
        F.git(worktree_dir, *base_args, "--allow-empty", "-m", msg)
    else:
        msg = f"forge {F.truncate(title,55)}\n\n{trailer}"
        F.git(worktree_dir, *base_args, "-m", msg)
    rc, sha, _ = F.git(worktree_dir, "rev-parse", "HEAD")
    return sha.strip() if rc == 0 else ""


def _synth_summary(files, add, rem):
    if files == 0 and add == 0 and rem == 0:
        return "no file changes detected"
    return f"edited {files} file(s), +{add}/-{rem}"


def _cleanup_worktree_only(repo, worktree_dir):
    """On failure we drop the worktree (no work worth preserving). The forge
    branch (if created) is left for retry/teardown."""
    if os.path.exists(worktree_dir):
        F.git(repo, "worktree", "remove", "-f", worktree_dir)


def reconcile_gateway(task_id, status, result, duration, agent_id):
    """PATCH gateway task state to mirror forge's verdict. Best-effort."""
    payload = {"status": status, "result": result}
    payload["assigned_agent"] = agent_id  # may be None to clear
    if duration:
        payload["duration_seconds"] = round(duration, 1)
    F.api_request("PATCH", f"/tasks/{task_id}", payload)


# ----------------------------------------------------------------------------
# Claim loop (bounded parallelism, wave-gated, watchdog + reclaim-aware)
# ----------------------------------------------------------------------------


def claim_one(agent_id):
    """
    POST /claim with a forge-specific preferred filter so the stock worker pool
    (which passes no `preferred`) cannot match our tasks. Returns the claimed
    task dict, None if empty (204)/neterr, or None after a 409 backoff.
    """
    r = F.api_request("POST", "/claim",
                      {"agent": agent_id, "preferred": agent_id})
    if r is None:
        return None
    if isinstance(r, tuple) and r[0] == "http_error":
        time.sleep(1.5)
        return None
    if isinstance(r, list):
        return r[0] if r else None
    return r


def wave_ready(manifest, wave_idx):
    """A wave releases only after all parent tasks reached 'done'.
    Returns (ready_task_ids, blocked_task_ids)."""
    ready, blocked = [], []
    for tid, node in manifest["tasks"].items():
        if node.get("wave") != wave_idx:
            continue
        if node.get("status") != "pending":
            continue
        deps_tN = node.get("depends_on") or []
        ok = True
        dep_failed = False
        for dep in deps_tN:
            dep_node = _node_by_tN(manifest, dep)
            if dep_node is None:
                continue
            dst = dep_node.get("status")
            if dst == "done":
                continue
            if dst in F.TERMINAL_BAD:
                dep_failed = True
                ok = False
                break
            ok = False  # dep not done yet
        if dep_failed:
            blocked.append(tid)
        elif ok:
            ready.append(tid)
    return ready, blocked


def _node_by_tN(manifest, tN):
    for node in manifest["tasks"].values():
        if node.get("tN") == tN:
            return node
    return None


def mark_blocked(batch_id, task_id):
    update_node(batch_id, task_id, status="blocked",
                summary="blocked: a dependency failed")
    reconcile_gateway(task_id, "failed", "forge: blocked (dependency failed)",
                      0, None)


def mark_unclaimable(batch_id, task_id):
    update_node(batch_id, task_id, status="unclaimable",
                summary="unclaimable (build/compile tag excluded or starved)")
    reconcile_gateway(task_id, "failed", "forge: unclaimable (never offered by /claim)",
                      0, None)


def all_terminal(manifest):
    return all(F.is_terminal(n.get("status", "pending"))
               for n in manifest["tasks"].values())


def counts(manifest):
    tasks = manifest["tasks"].values()
    done = sum(1 for n in tasks if F.is_terminal(n.get("status", "")))
    total = len(manifest["tasks"])
    failed = sum(1 for n in tasks if n.get("status") in F.TERMINAL_BAD)
    inflight = sum(1 for n in tasks if n.get("status") in ("running", "claimed"))
    return done, total, failed, inflight


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("batch_id")
    ap.add_argument("--parallel", type=int, default=None)
    ap.add_argument("--gate", choices=["on", "off"], default="on")
    args = ap.parse_args()

    batch_id = args.batch_id
    manifest = F.load_manifest(batch_id)
    if manifest is None:
        F.eprint(f"forge_run: no such batch {batch_id}")
        sys.exit(2)

    if not F.gateway_healthy():
        F.eprint("forge_run: gateway not healthy at " + F.API_BASE)
        sys.exit(3)

    if not F.acquire_run_lock(batch_id):
        F.eprint(f"forge_run: batch {batch_id} is already being drained "
                 f"(run lock held); abort")
        sys.exit(4)

    agent_id = f"forge-{batch_id}"
    parallel = args.parallel or manifest.get("parallel") or F.DEFAULT_PARALLEL
    parallel = max(1, min(parallel, F.MAX_PARALLEL_CAP))
    gate_on = (args.gate == "on")

    F.eprint(f"forge_run: draining {batch_id} parallel={parallel} gate={args.gate} "
             f"agent={agent_id}")

    inflight = {}  # thread -> task_id
    inflight_started = {}  # task_id -> monotonic start (for reclaim detection)
    pending_first_seen = {}  # task_id -> monotonic first seen pending (watchdog)
    last_heartbeat = 0
    n_waves = len(manifest.get("waves", []))

    try:
        while not _shutdown.is_set():
            if _auth_stop.is_set():
                F.eprint("forge_run: AUTH failure detected — halting batch.")
                break

            manifest = F.load_manifest(batch_id)

            # reap finished threads
            for th in list(inflight.keys()):
                if not th.is_alive():
                    tid = inflight.pop(th, None)
                    inflight_started.pop(tid, None)

            # reclaim detection: a task we believe is running but that the
            # manifest now shows as 'pending' means the gateway zombie reclaimer
            # reset it mid-flight (or our heartbeat failed). Mark it terminal
            # 'reclaimed' so plain `forge status` reflects reality without a
            # --refresh, and so we never double-execute it.
            for th, tid in list(inflight.items()):
                node = manifest["tasks"].get(tid, {})
                if node.get("status") == "pending" and th.is_alive():
                    F.update_manifest_node(
                        batch_id, tid,
                        lambda n: n.update({
                            "status": "reclaimed",
                            "summary": "gateway reclaimed task mid-run; attempt abandoned",
                        }))

            # mark blocked tasks across all waves
            for wave_idx in range(n_waves):
                _, blocked = wave_ready(manifest, wave_idx)
                for tid in blocked:
                    mark_blocked(batch_id, tid)

            manifest = F.load_manifest(batch_id)

            # stuck-pending watchdog: a pending task that is never claimable
            # (e.g. excluded by a build/compile tag, or starved) must not hang
            # the drain. If pending longer than its budget + slack with no
            # inflight progress on it, fail it as unclaimable.
            now_mono = time.monotonic()
            ready_ids_global = set()
            for wave_idx in range(n_waves):
                ready, _ = wave_ready(manifest, wave_idx)
                ready_ids_global.update(ready)
            for tid in ready_ids_global:
                pending_first_seen.setdefault(tid, now_mono)
            for tid in list(pending_first_seen.keys()):
                node = manifest["tasks"].get(tid, {})
                if node.get("status") != "pending":
                    pending_first_seen.pop(tid, None)
                    continue
                if tid not in ready_ids_global:
                    continue  # not ready yet (deps); don't penalize
                if tid in inflight.values():
                    continue
                budget = (node.get("per_task_timeout_s")
                          or F.DEFAULT_PER_TASK_TIMEOUT)
                if now_mono - pending_first_seen[tid] > budget + F.UNCLAIMABLE_SLACK_S:
                    mark_unclaimable(batch_id, tid)
                    pending_first_seen.pop(tid, None)

            if all_terminal(F.load_manifest(batch_id)) and not inflight:
                break

            free = parallel - len(inflight)
            launched = 0
            if free > 0:
                ready_set = set(ready_ids_global)
                ready_set -= set(inflight.values())
                for _ in range(free):
                    if _shutdown.is_set():
                        break
                    if not ready_set:
                        break
                    claimed = claim_one(agent_id)
                    if not claimed:
                        break
                    cid = claimed["id"]
                    if cid not in ready_set:
                        # Not ready (dep pending) — release back to pending.
                        F.api_request("PATCH", f"/tasks/{cid}",
                                      {"status": "pending", "assigned_agent": None})
                        continue
                    m2 = F.load_manifest(batch_id)
                    th = threading.Thread(
                        target=execute_task,
                        args=(m2, cid, agent_id, gate_on),
                        daemon=True,
                    )
                    th.start()
                    inflight[th] = cid
                    inflight_started[cid] = time.monotonic()
                    pending_first_seen.pop(cid, None)
                    launched += 1
                    ready_set.discard(cid)
                    time.sleep(0.5)

            now = time.time()
            if now - last_heartbeat >= 30:
                done, total, failed, infl = counts(F.load_manifest(batch_id))
                F.eprint(f"forge_run[{batch_id}] done={done}/{total} "
                         f"inflight={len(inflight)} failed={failed}")
                last_heartbeat = now

            if launched == 0 and not _shutdown.is_set():
                time.sleep(3)

    finally:
        F.eprint("forge_run: tearing down workers...")
        deadline = time.time() + 60
        for th in list(inflight.keys()):
            remaining = max(1, deadline - time.time())
            th.join(timeout=remaining)
        F.release_run_lock(batch_id)
        done, total, failed, _ = counts(F.load_manifest(batch_id))
        F.eprint(f"forge_run: drained {batch_id} done={done}/{total} failed={failed}")


if __name__ == "__main__":
    main()
