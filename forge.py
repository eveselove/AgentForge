#!/usr/bin/env python3
"""
forge.py — CLI for the forge orchestrator.

Compact-by-default run-to-drain pipeline over AgentForge. Claude drives this
over ssh/Bash and only ever sees compact structured status + quality verdicts,
never full code unless it runs `forge diff`.

Subcommands:
  submit    decompose a batch.json into N gateway tasks + write manifest (ids only)
  run       drain a batch in a bounded foreground claim-loop (blocking or --detach)
  status    compact one-line-per-task table (manifest read; --refresh hits gateway)
  tree      grouped compact tree (big-task -> wave -> subtasks)
  result    one compact-result object for a task (incl. SUMMARY)
  diff      the ONLY code-emitting command (stat by default, --full for patch)
  gate      re-run gates on a task/batch's preserved worktree
  gates     manage per-repo gate profile registry
  accept    merge gate-passing branches into the integration branch
  reject    discard a task's branch+worktree (or --retry)
  retry     re-queue failed/timed-out tasks (--shrink splits oversized ones)
  teardown  remove non-accepted worktrees/branches for a batch

stdlib only.
"""

import argparse
import json
import os
import re
import subprocess
import sys

import forge_lib as F

HERE = os.path.dirname(os.path.abspath(__file__))
FORGE_RUN = os.path.join(HERE, "forge_run.py")


def out_json(obj):
    print(json.dumps(obj, ensure_ascii=False))


# ----------------------------------------------------------------------------
# submit
# ----------------------------------------------------------------------------


def _topo_waves(tasks):
    """
    Topologically sort tasks by depends_on (batch-local refs) into waves.
    Returns (waves, placed). Raises ValueError on unknown ref or cycle.
    """
    refs = [t["ref"] for t in tasks]
    deps = {t["ref"]: list(t.get("depends_on") or []) for t in tasks}
    for r, ds in deps.items():
        for d in ds:
            if d not in refs:
                raise ValueError(f"task {r} depends on unknown ref {d}")
    waves = []
    placed = {}
    remaining = set(refs)
    wave_idx = 0
    while remaining:
        this_wave = [r for r in refs
                     if r in remaining
                     and all(d in placed for d in deps[r])]
        if not this_wave:
            raise ValueError(f"dependency cycle among: {sorted(remaining)}")
        for r in this_wave:
            placed[r] = wave_idx
            remaining.discard(r)
        waves.append(this_wave)
        wave_idx += 1
    return waves, placed


def cmd_submit(args):
    if args.batch_file == "-":
        raw = sys.stdin.read()
    else:
        with open(args.batch_file, "r", encoding="utf-8") as f:
            raw = f.read()
    try:
        spec = json.loads(raw)
    except json.JSONDecodeError as e:
        out_json({"error": f"invalid batch json: {e}"})
        sys.exit(2)

    tasks = spec.get("tasks") or []
    if not tasks:
        out_json({"error": "batch has no tasks"})
        sys.exit(2)
    for i, t in enumerate(tasks):
        if "ref" not in t or "title" not in t:
            out_json({"error": f"task[{i}] missing ref/title"})
            sys.exit(2)

    repo = spec.get("repo") or "agentforge"
    parallel = spec.get("parallel") or args.parallel or F.DEFAULT_PARALLEL
    big_task = spec.get("big_task") or "(unnamed)"
    override_gates = spec.get("gates")
    repo_path = spec.get("repo_path")
    models = spec.get("models") or {}

    gate_profile = F.resolve_gate_profile(repo, override_gates, repo_path)
    repo_path = gate_profile["repo_path"]

    # Resolve + PIN the base. If the batch omits base_branch we branch off the
    # repo's CURRENT HEAD (live working state), NOT a stale 'main'. We pin to the
    # exact commit SHA so worktree-add and accept use a fixed base.
    requested_base = args.into_base or spec.get("base_branch")
    base_branch, base_sha, base_err = F.resolve_base(repo_path, requested_base)
    if base_err:
        out_json({"error": f"base resolution failed: {base_err}"})
        sys.exit(2)

    warnings = []
    if not requested_base:
        warnings.append(
            f"base_branch not given; using current HEAD '{base_branch}' "
            f"@ {base_sha[:8]} (live working state).")

    # Assert the per-task budget stays under the gateway zombie reclaimer
    # threshold (agy cap + gate budget). effective_caps enforces this; we warn
    # if the requested complex budget would have been clipped.
    per_task_timeout_default = spec.get("per_task_timeout_s")

    # batch id
    h = F.hashlib.sha1(
        (big_task + repo + F.now_iso() + str(os.getpid())).encode()
    ).hexdigest()[:8]
    batch_id = f"bf_{h}"
    # Integration branch must NOT be a prefix of the task branches
    # forge/<batch_id>/<task_id> or git ref hierarchy collides. Sibling leaf:
    integration_branch = (args.into or spec.get("integration_branch")
                          or f"forge/{batch_id}/integration")

    try:
        waves_refs, placed = _topo_waves(tasks)
    except ValueError as e:
        out_json({"error": str(e)})
        sys.exit(2)

    manifest_tasks = {}
    waves_ids = [[] for _ in waves_refs]
    task_ids = []
    ref_to_id = {}
    preferred_agent = f"forge-{batch_id}"

    for idx, t in enumerate(tasks):
        ref = t["ref"]
        tN = f"t{idx+1}"
        title = t["title"]
        complexity = (t.get("complexity") or "medium").lower()
        tags_in = list(t.get("tags") or [])
        # Strip/rename tags the gateway /claim filter silently excludes; such a
        # tag would make the task permanently un-claimable -> drain never ends.
        tags, renamed = F.sanitize_tags(tags_in)
        for orig, new in renamed:
            warnings.append(
                f"{tN}: tag '{orig}' excluded by gateway /claim; renamed to "
                f"'{new}' so the task stays claimable.")

        desc_in = t.get("description") or ""
        if len(desc_in) > 1200 or complexity == "complex":
            warnings.append(
                f"{tN}: description/complexity looks large; ensure it beats "
                f"the per-task timeout (consider splitting).")
        full_desc = desc_in + F.SUMMARY_BOILERPLATE
        forge_tag = f"forge:{batch_id}"
        all_tags = tags + [forge_tag]

        payload = {
            "title": title,
            "description": full_desc,
            "complexity": complexity,
            "tags": all_tags,
            "preferred_agent": preferred_agent,
            "requires_agent_review": False,
        }
        resp = F.api_request("POST", "/tasks", payload, timeout=30)
        if not isinstance(resp, dict) or "id" not in resp:
            out_json({"error": f"failed to create gateway task for {tN}",
                      "detail": str(resp)[:200]})
            sys.exit(3)
        gid = resp["id"]
        ref_to_id[ref] = gid
        task_ids.append(gid)
        wave_idx = placed[ref]
        waves_ids[wave_idx].append(gid)

        if per_task_timeout_default:
            ptt = min(int(per_task_timeout_default), F.GATEWAY_TASK_TIMEOUT)
        else:
            ptt = F.COMPLEXITY_TIMEOUT.get(complexity, F.DEFAULT_PER_TASK_TIMEOUT)

        # Surface the enforced effective cap so Claude can see if it was clipped
        # to fit under the zombie reclaimer threshold.
        agy_cap, gate_budget = F.effective_caps(ptt)
        if agy_cap < ptt:
            warnings.append(
                f"{tN}: agy timeout capped {ptt}s->{agy_cap}s so agy+gate stays "
                f"under the {F.ZOMBIE_TIMEOUT_MINUTES}min gateway reclaimer.")

        manifest_tasks[gid] = {
            "tN": tN,
            "ref": ref,
            "gateway_id": gid,
            "short_title": title[:60],
            "full_description": full_desc,
            "complexity": complexity,
            "tags": all_tags,
            "depends_on": list(t.get("depends_on") or []),
            "wave": wave_idx,
            "status": "pending",
            "model_used": None,
            "duration_s": None,
            "branch": f"forge/{batch_id}/{gid}",
            "commit_sha": None,
            "files_changed_count": 0,
            "lines_added": 0,
            "lines_removed": 0,
            "per_task_timeout_s": ptt,
            "gate": {},
            "summary": None,
            "attempts": 1,
            "rl_attempts": 0,
            "merge": {"status": "none", "into": None, "conflict_files": []},
            "started_at": None,
        }

    big_tasks = [{
        "big_id": "B1",
        "title": big_task,
        "subtasks": task_ids,
    }]

    manifest = {
        "batch_id": batch_id,
        "repo": repo,
        "repo_path": repo_path,
        "base_branch": base_branch,
        "base_sha": base_sha,
        "integration_branch": integration_branch,
        "parallel": parallel,
        "big_task": big_task,
        "created_at": F.now_iso(),
        "gate_profile": gate_profile,
        "models": models,
        "waves": waves_ids,
        "big_tasks": big_tasks,
        "tasks": manifest_tasks,
    }
    with F.manifest_lock(batch_id):
        F.save_manifest(manifest)

    result = {
        "batch_id": batch_id,
        "repo": repo,
        "base_branch": base_branch,
        "base_sha": base_sha[:8],
        "integration_branch": integration_branch,
        "n": len(task_ids),
        "task_ids": task_ids,
        "waves": len(waves_ids),
    }
    if warnings:
        result["warnings"] = warnings
    out_json(result)

    if args.run or args.detach:
        _launch_run(batch_id, parallel, detach=args.detach, gate="on")


# ----------------------------------------------------------------------------
# run
# ----------------------------------------------------------------------------


def _launch_run(batch_id, parallel, detach, gate):
    cmd = [sys.executable, FORGE_RUN, batch_id,
           "--parallel", str(parallel), "--gate", gate]
    if detach:
        # Detached drain. On erbox linger is enabled so the child survives ssh
        # teardown via the user manager; start_new_session makes it independent
        # of the launching shell's process group too.
        proc = subprocess.Popen(
            cmd,
            stdout=open(os.path.join(F.LOG_DIR, f"forge_run_{batch_id}.log"), "a"),
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        # Record the pid so survival never depends on ssh staying open.
        try:
            with open(os.path.join(F.BATCHES_DIR, f"{batch_id}.run.pid"), "w") as f:
                f.write(str(proc.pid))
        except Exception:
            pass
        out_json({"batch_id": batch_id, "pid": proc.pid, "state": "running"})
    else:
        rc = subprocess.call(cmd)
        if rc != 0:
            F.eprint(f"forge run exited rc={rc}")
        m = F.load_manifest(batch_id)
        if m:
            print(F.render_table(m))


def cmd_run(args):
    m = F.load_manifest(args.batch_id)
    if m is None:
        out_json({"error": f"no such batch {args.batch_id}"})
        sys.exit(2)
    parallel = args.parallel or m.get("parallel") or F.DEFAULT_PARALLEL
    _launch_run(args.batch_id, parallel, detach=args.detach,
                gate=("off" if args.gate == "off" else "on"))


# ----------------------------------------------------------------------------
# status / tree / result
# ----------------------------------------------------------------------------


def _refresh_from_gateway(batch_id):
    """
    Reconcile manifest task statuses against the gateway. ONLY runs when no live
    forge_run owns this batch (it is the source of truth while draining). When a
    run IS live we skip the writeback entirely to avoid clobbering its
    freshly-written done/gate results (cross-process data-race fix). All writes
    go through the per-batch manifest lock.
    """
    owner = F.run_lock_owner_pid(batch_id)
    if owner is not None:
        # A live drain owns the manifest; do not write. Read-only refresh of the
        # gateway for display would still risk staleness, so we just signal.
        F.eprint(f"forge: batch {batch_id} is being drained by pid {owner}; "
                 f"--refresh skipped (run loop owns the manifest).")
        return
    # Single list call instead of N GET /tasks/{id} round-trips.
    listing = F.api_request("GET", f"/tasks?status=&limit=2000", timeout=20)
    by_id = {}
    if isinstance(listing, list):
        for t in listing:
            if isinstance(t, dict) and t.get("id"):
                by_id[t["id"]] = t
    with F.manifest_lock(batch_id):
        m = F.load_manifest(batch_id)
        if m is None:
            return
        for tid, node in m["tasks"].items():
            if F.is_terminal(node.get("status", "")):
                continue
            r = by_id.get(tid)
            if r is None:
                r = F.api_request("GET", f"/tasks/{tid}", timeout=15)
            if not isinstance(r, dict):
                continue
            gstatus = r.get("status")
            result = r.get("result")
            dur, model, _kind = F.parse_result_string(result)
            if model:
                node["model_used"] = model
            if dur is not None:
                node["duration_s"] = dur
            if gstatus in ("review", "done") and node.get("status") not in F.TERMINAL:
                node["status"] = "review"
            elif gstatus == "failed":
                node["status"] = "failed"
            elif gstatus == "in_progress":
                node["status"] = "running"
        F.save_manifest(m)


def cmd_status(args):
    m = F.load_manifest(args.batch_id)
    if m is None:
        out_json({"error": f"no such batch {args.batch_id}"})
        sys.exit(2)
    if args.refresh:
        _refresh_from_gateway(args.batch_id)
        m = F.load_manifest(args.batch_id)
    print(F.render_table(m, flt=args.filter, wave=args.wave))


def cmd_tree(args):
    m = F.load_manifest(args.batch_id)
    if m is None:
        out_json({"error": f"no such batch {args.batch_id}"})
        sys.exit(2)
    print(F.render_header(m))
    glyph = {"done": "ok", "review": "rev", "failed": "X", "timeout": "T",
             "gatefail": "X", "gate_timeout": "GT", "rate_limited": "RL",
             "blocked": "BLK", "auth": "AUTH", "reclaimed": "RECL",
             "unclaimable": "UNCL", "running": "~", "pending": "."}
    for bt in m.get("big_tasks", []):
        print(f"* {bt['title']}  [{bt['big_id']}]")
        sub_nodes = [m["tasks"][i] for i in bt["subtasks"] if i in m["tasks"]]
        waves = sorted(set(n.get("wave", 0) for n in sub_nodes))
        for w in waves:
            print(f"  wave {w}:")
            for n in sorted(sub_nodes, key=lambda x: x.get("tN", "")):
                if n.get("wave") != w:
                    continue
                g = glyph.get(n.get("status", "pending"), "?")
                gate = (n.get("gate") or {}).get("verdict") or "-"
                deps = n.get("depends_on") or []
                dep_s = f" <-{','.join(deps)}" if deps else ""
                print(f"    {n['tN']:>3} [{g}] gate={gate} "
                      f"\"{F.truncate(n.get('short_title',''),28)}\"{dep_s}")


def cmd_result(args):
    m, tid, node = F.find_batch_for_task(args.task_id)
    if node is None:
        out_json({"error": f"no such task {args.task_id}"})
        sys.exit(2)
    out_json(F.compact_result_obj(node))


# ----------------------------------------------------------------------------
# diff (the ONLY code-emitting command)
# ----------------------------------------------------------------------------


def cmd_diff(args):
    m, tid, node = F.find_batch_for_task(args.task_id)
    if node is None:
        out_json({"error": f"no such task {args.task_id}"})
        sys.exit(2)
    repo = m["repo_path"]
    base = m.get("base_sha") or m["base_branch"]
    branch = node["branch"]
    if args.full:
        rc, out, err = F.git(repo, "diff", f"{base}...{branch}")
    elif args.files:
        rc, out, err = F.git(repo, "diff", "--name-only", f"{base}...{branch}")
    elif args.name:
        rc, out, err = F.git(repo, "diff", f"{base}...{branch}", "--", args.name)
    else:  # --stat default
        rc, out, err = F.git(repo, "diff", "--stat", f"{base}...{branch}")
    if rc != 0:
        out_json({"error": "git diff failed", "detail": err.strip()[:200],
                  "branch": branch})
        sys.exit(3)
    sys.stdout.write(out)


# ----------------------------------------------------------------------------
# gate
# ----------------------------------------------------------------------------


def _gate_one(m, tid, node, rerun):
    repo = m["repo_path"]
    proj_name = os.path.basename(repo)
    worktree_dir = os.path.join(os.path.dirname(repo),
                                f"{proj_name}_{tid}")
    transient = False
    if not os.path.isdir(worktree_dir):
        branch = node["branch"]
        rc, _, _ = F.git(repo, "worktree", "add", worktree_dir, branch)
        transient = (rc == 0)
        if rc != 0:
            return {"id": F.short_id(tid), "gate_verdict": "n/a",
                    "first_failing_check": None,
                    "first_error_line": "no worktree/branch to gate",
                    "gates_run": [], "gate_dur_s": 0}
    gate = F.run_gates(worktree_dir, m["gate_profile"])
    if transient:
        F.git(repo, "worktree", "remove", "-f", worktree_dir)
    # persist (cross-process locked)
    def _apply(n):
        n["gate"] = gate
        if gate["verdict"] == "pass" and n["status"] in ("gatefail", "gate_timeout"):
            n["status"] = "review"
        elif gate["verdict"] in ("fail", "gate_timeout") and n["status"] in ("done", "review"):
            n["status"] = "gatefail" if gate["verdict"] == "fail" else "gate_timeout"
    F.update_manifest_node(m["batch_id"], tid, _apply)
    return {"id": F.short_id(tid), "gate_verdict": gate["verdict"],
            "first_failing_check": gate["first_failing_check"],
            "first_error_line": gate["first_error_line"],
            "gates_run": gate["gates_run"], "gate_dur_s": gate["dur_s"]}


def cmd_gate(args):
    m = F.load_manifest(args.target)
    if m is not None:
        results = []
        for tid, node in m["tasks"].items():
            if node.get("status") in ("done", "review", "gatefail", "gate_timeout"):
                results.append(_gate_one(m, tid, node, args.rerun))
        for r in results:
            _print_gate_line(r)
        return
    m, tid, node = F.find_batch_for_task(args.target)
    if node is None:
        out_json({"error": f"no such task/batch {args.target}"})
        sys.exit(2)
    r = _gate_one(m, tid, node, args.rerun)
    _print_gate_line(r)


def _print_gate_line(r):
    if r["gate_verdict"] == "pass":
        n = len(r["gates_run"])
        print(f"GATE {r['id']} pass {n}/{n} dur={int(r['gate_dur_s'])}s")
    elif r["gate_verdict"] == "fail":
        print(f"GATE {r['id']} fail check={r['first_failing_check']} "
              f"line=\"{r['first_error_line']}\"")
    elif r["gate_verdict"] == "gate_timeout":
        print(f"GATE {r['id']} timeout check={r['first_failing_check']} "
              f"line=\"{r['first_error_line']}\"")
    else:
        print(f"GATE {r['id']} n/a (no runnable checks)")


# ----------------------------------------------------------------------------
# gates registry management
# ----------------------------------------------------------------------------


def cmd_gates(args):
    if args.list:
        reg = F.load_gates()
        for repo, prof in reg.items():
            names = ",".join(c["name"] for c in prof.get("checks", []))
            cwds = set(c.get("cwd", ".") for c in prof.get("checks", []))
            cwd = list(cwds)[0] if len(cwds) == 1 else "mixed"
            print(f"{repo}: {names} (cwd={cwd})")
        return
    if args.set:
        repo, profile_file = args.set
        with open(profile_file, "r", encoding="utf-8") as f:
            prof = json.load(f)
        reg = F.load_gates()
        reg[repo] = prof
        F.save_gates(reg)
        out_json({"ok": True, "repo": repo,
                  "checks": [c["name"] for c in prof.get("checks", [])]})
        return
    if args.detect:
        prof = F.detect_gate_profile(args.detect)
        out_json(prof)
        return
    out_json({"error": "use --list | --set <repo> <profile.json> | --detect <repo_path>"})


# ----------------------------------------------------------------------------
# accept (merge gate-passing branches into integration branch)
# ----------------------------------------------------------------------------


def _ensure_integration_branch(repo, integration, base):
    rc, _, _ = F.git(repo, "rev-parse", "--verify", integration)
    if rc != 0:
        F.git(repo, "branch", integration, base)


def _mergeable(node, allow_nagate):
    """Precondition: terminal-good AND gate acceptable. Returns (ok, reason)."""
    if node.get("status") not in ("done", "review"):
        return False, "not_done"
    verdict = (node.get("gate") or {}).get("verdict")
    if verdict == "pass":
        return True, None
    if verdict == "n/a":
        # n/a is mergeable only if explicitly allowed (or gates were disabled).
        if allow_nagate or (node.get("gate") or {}).get("gates_disabled"):
            return True, None
        return False, "gate_na"
    return False, "gate_fail"


def _merge_one(repo, integration, task_id, node, allow_nagate):
    """
    Merge node's branch into integration. Returns (status, info).
    status in {merged, noop, skip}. Uses a scratch worktree so we never touch
    the user's checkout. Conflict-safe (abort on conflict).
    """
    branch = node["branch"]
    ok, reason = _mergeable(node, allow_nagate)
    if not ok:
        return "skip", {"reason": reason}
    rc, _, _ = F.git(repo, "rev-parse", "--verify", branch)
    if rc != 0:
        return "skip", {"reason": "no_branch"}
    rc, _, _ = F.git(repo, "merge-base", "--is-ancestor", branch, integration)
    if rc == 0:
        return "noop", {}
    scratch = os.path.join(os.path.dirname(repo),
                           f"{os.path.basename(repo)}_int_{integration.replace('/','_')}")
    if os.path.exists(scratch):
        F.git(repo, "worktree", "remove", "-f", scratch)
    rc, _, err = F.git(repo, "worktree", "add", scratch, integration)
    if rc != 0:
        return "skip", {"reason": "scratch_failed"}
    try:
        msg = (f"forge merge {F.truncate(node.get('short_title',''),50)}\n\n"
               f"task {task_id.split('-')[-1][:8].lower()}\nTask-Id: {task_id}")
        rc, out, err = F.git(scratch, "merge", "--no-ff", "-m", msg, branch)
        if rc != 0:
            rc2, conf, _ = F.git(scratch, "diff", "--name-only", "--diff-filter=U")
            conflict_files = [c for c in conf.splitlines() if c.strip()]
            F.git(scratch, "merge", "--abort")
            return "skip", {"reason": "conflict", "files": conflict_files}
        return "merged", {}
    finally:
        F.git(repo, "worktree", "remove", "-f", scratch)


def cmd_accept(args):
    m = F.load_manifest(args.target)
    single_tid = None
    if m is None:
        m, single_tid, _ = F.find_batch_for_task(args.target)
        if m is None:
            out_json({"error": f"no such task/batch {args.target}"})
            sys.exit(2)
    repo = m["repo_path"]
    base = m.get("base_sha") or m["base_branch"]
    integration = args.into or m["integration_branch"]
    allow_nagate = args.allow_nagate

    if single_tid:
        ordered = [single_tid]
    else:
        ordered = []
        for wave in m["waves"]:
            ordered.extend(wave)

    if args.all_green and not single_tid:
        not_green = [m["tasks"][t]["tN"] for t in ordered
                     if not _mergeable(m["tasks"][t], allow_nagate)[0]]
        if not_green:
            print(f"REFUSE all-green required: {len(not_green)} not green "
                  f"({','.join(not_green)})")
            sys.exit(1)

    _ensure_integration_branch(repo, integration, base)

    merged, skipped = [], []
    for tid in ordered:
        node = m["tasks"][tid]
        status, info = _merge_one(repo, integration, tid, node, allow_nagate)
        if status in ("merged", "noop"):
            merged.append(tid)
            node["merge"] = {"status": "merged", "into": integration,
                             "conflict_files": []}
            tag = "MERGED" if status == "merged" else "MERGED(noop)"
            print(f"{tag} {F.short_id(tid)} -> {integration}")
        else:
            reason = info.get("reason", "skip")
            files = info.get("files", [])
            node["merge"] = {"status": ("conflict" if reason == "conflict"
                                        else "skipped"),
                             "into": integration, "conflict_files": files}
            if reason == "conflict":
                print(f"SKIP {F.short_id(tid)} reason=conflict files={len(files)}")
            else:
                print(f"SKIP {F.short_id(tid)} reason={reason}")
            skipped.append({"id": tid, "reason": reason})
    with F.manifest_lock(m["batch_id"]):
        # Re-load under lock and apply merge-status updates so we don't clobber a
        # concurrent writer's status fields.
        live = F.load_manifest(m["batch_id"]) or m
        for tid in ordered:
            if tid in live["tasks"]:
                live["tasks"][tid]["merge"] = m["tasks"][tid]["merge"]
        F.save_manifest(live)

    rc, head, _ = F.git(repo, "rev-parse", integration)
    conflicts = sum(1 for s in skipped if s["reason"] == "conflict")
    print(f"ACCEPTED {len(merged)} SKIPPED {len(skipped)} CONFLICT {conflicts}")
    if args.json:
        out_json({"merged": merged, "skipped": skipped,
                  "integration_branch": integration,
                  "head_sha": head.strip() if rc == 0 else None})


# ----------------------------------------------------------------------------
# reject
# ----------------------------------------------------------------------------


def cmd_reject(args):
    m, tid, node = F.find_batch_for_task(args.task_id)
    if node is None:
        out_json({"error": f"no such task {args.task_id}"})
        sys.exit(2)
    repo = m["repo_path"]
    branch = node["branch"]
    proj_name = os.path.basename(repo)
    worktree_dir = os.path.join(os.path.dirname(repo), f"{proj_name}_{tid}")
    removed_wt = False
    if os.path.exists(worktree_dir):
        F.git(repo, "worktree", "remove", "-f", worktree_dir)
        removed_wt = True
    F.git(repo, "branch", "-D", branch)
    F.api_request("POST", f"/tasks/{tid}/reject", {"feedback": "forge reject"})
    F.update_manifest_node(m["batch_id"], tid, lambda n: n.update(
        {"status": "rejected", "summary": "rejected by forge"}))

    retried = None
    if args.retry:
        m2 = F.load_manifest(m["batch_id"])
        retried = _requeue_task(m2, tid, node, shrink=False)
        print(f"RETRY {F.short_id(tid)} -> {F.short_id(retried)} wave=tail")
        out_json({"id": F.short_id(tid), "discarded_branch": branch,
                  "removed_worktree": removed_wt, "retried": F.short_id(retried)})
    else:
        print(f"REJECTED {F.short_id(tid)} branch+worktree removed")
        out_json({"id": F.short_id(tid), "discarded_branch": branch,
                  "removed_worktree": removed_wt, "retried": None})


# ----------------------------------------------------------------------------
# retry
# ----------------------------------------------------------------------------


def _requeue_task(m, old_tid, old_node, shrink):
    """Create a fresh gateway task cloned from old_node's spec, append to tail wave."""
    batch_id = m["batch_id"]
    n_existing = len(m["tasks"])
    new_tN = f"t{n_existing+1}"
    title = old_node["short_title"]
    desc = old_node["full_description"]
    if shrink and len(desc) > 400:
        desc = "SMALLER SCOPE — do ONLY the first half: " + desc
    tags = old_node.get("tags", [])
    # keep tags claimable (defensive; submit already sanitized)
    tags, _ = F.sanitize_tags(tags)
    payload = {
        "title": title,
        "description": desc,
        "complexity": "simple" if shrink else old_node.get("complexity", "medium"),
        "tags": tags,
        "preferred_agent": f"forge-{batch_id}",
        "requires_agent_review": False,
    }
    resp = F.api_request("POST", "/tasks", payload)
    if not isinstance(resp, dict) or "id" not in resp:
        return None
    gid = resp["id"]
    with F.manifest_lock(batch_id):
        m = F.load_manifest(batch_id)
        tail_wave = max((n.get("wave", 0) for n in m["tasks"].values()), default=0) + 1
        ptt = (F.COMPLEXITY_TIMEOUT["simple"] if shrink
               else old_node.get("per_task_timeout_s", F.DEFAULT_PER_TASK_TIMEOUT))
        m["tasks"][gid] = {
            "tN": new_tN, "ref": old_node.get("ref", new_tN) + "_retry",
            "gateway_id": gid, "short_title": title[:60],
            "full_description": desc, "complexity": payload["complexity"],
            "tags": tags, "depends_on": [], "wave": tail_wave,
            "status": "pending", "model_used": None, "duration_s": None,
            "branch": f"forge/{batch_id}/{gid}", "commit_sha": None,
            "files_changed_count": 0, "lines_added": 0, "lines_removed": 0,
            "per_task_timeout_s": ptt, "gate": {}, "summary": None,
            "attempts": old_node.get("attempts", 1) + 1,
            "rl_attempts": 0,
            "merge": {"status": "none", "into": None, "conflict_files": []},
            "started_at": None,
        }
        while len(m["waves"]) <= tail_wave:
            m["waves"].append([])
        m["waves"][tail_wave].append(gid)
        F.save_manifest(m)
    return gid


def cmd_retry(args):
    m = F.load_manifest(args.batch_id)
    if m is None:
        out_json({"error": f"no such batch {args.batch_id}"})
        sys.exit(2)
    if not args.failed:
        out_json({"error": "use --failed to re-queue failed/timed-out tasks"})
        sys.exit(2)
    new_ids = []
    retryable = ("failed", "timeout", "gate_timeout", "rate_limited", "auth",
                 "reclaimed", "unclaimable")
    targets = [(tid, node) for tid, node in list(m["tasks"].items())
               if node.get("status") in retryable]
    for tid, node in targets:
        gid = _requeue_task(F.load_manifest(args.batch_id), tid, node,
                            shrink=args.shrink)
        if gid:
            new_ids.append(gid)
    out_json({"batch_id": args.batch_id, "requeued": new_ids, "n": len(new_ids)})


# ----------------------------------------------------------------------------
# teardown
# ----------------------------------------------------------------------------


def cmd_teardown(args):
    m = F.load_manifest(args.batch_id)
    if m is None:
        out_json({"error": f"no such batch {args.batch_id}"})
        sys.exit(2)
    repo = m["repo_path"]
    removed_wt = 0
    deleted_br = 0
    kept = []
    proj_name = os.path.basename(repo)
    for tid, node in m["tasks"].items():
        branch = node["branch"]
        if args.keep_accepted and node.get("merge", {}).get("status") == "merged":
            kept.append(F.short_id(tid))
            continue
        worktree_dir = os.path.join(os.path.dirname(repo), f"{proj_name}_{tid}")
        if os.path.exists(worktree_dir):
            F.git(repo, "worktree", "remove", "-f", worktree_dir)
            removed_wt += 1
        rc, _, _ = F.git(repo, "branch", "-D", branch)
        if rc == 0:
            deleted_br += 1
    # Scope the prune to THIS batch only: `git worktree prune` is global and
    # would gc pre-existing unrelated prunable worktrees. We removed our own
    # worktrees above (which unregisters them), so a global prune is unneeded;
    # we deliberately do NOT call `git worktree prune` to avoid touching the
    # user's other worktrees. (The remove -f calls already deregister ours.)
    out_json({"removed_worktrees": removed_wt, "deleted_branches": deleted_br,
              "kept": kept, "note": "global worktree prune intentionally skipped (batch-scoped)"})


# ----------------------------------------------------------------------------
# argparse
# ----------------------------------------------------------------------------


def build_parser():
    p = argparse.ArgumentParser(prog="forge",
                                description="compact-by-default AgentForge orchestrator")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("submit")
    s.add_argument("batch_file", help="batch.json path or '-' for stdin")
    s.add_argument("--repo")
    s.add_argument("--into", help="integration branch override")
    s.add_argument("--into-base", dest="into_base",
                   help="base branch override (default: repo current HEAD)")
    s.add_argument("--parallel", type=int)
    s.add_argument("--run", action="store_true", help="drain inline (blocking)")
    s.add_argument("--detach", action="store_true", help="drain via background child")
    s.set_defaults(func=cmd_submit)

    s = sub.add_parser("run")
    s.add_argument("batch_id")
    s.add_argument("--parallel", type=int)
    s.add_argument("--gate", choices=["on", "off"], default="on")
    s.add_argument("--detach", action="store_true")
    s.set_defaults(func=cmd_run)

    s = sub.add_parser("status")
    s.add_argument("batch_id")
    s.add_argument("--filter", choices=["failed", "gatefail", "inflight", "done"])
    s.add_argument("--wave", type=int)
    s.add_argument("--refresh", action="store_true")
    s.set_defaults(func=cmd_status)

    s = sub.add_parser("tree")
    s.add_argument("batch_id")
    s.set_defaults(func=cmd_tree)

    s = sub.add_parser("result")
    s.add_argument("task_id")
    s.set_defaults(func=cmd_result)

    s = sub.add_parser("diff")
    s.add_argument("task_id")
    s.add_argument("--stat", action="store_true")
    s.add_argument("--files", action="store_true")
    s.add_argument("--name")
    s.add_argument("--full", action="store_true")
    s.set_defaults(func=cmd_diff)

    s = sub.add_parser("gate")
    s.add_argument("target", help="task_id or batch_id")
    s.add_argument("--rerun", action="store_true")
    s.set_defaults(func=cmd_gate)

    s = sub.add_parser("gates")
    s.add_argument("--list", action="store_true")
    s.add_argument("--set", nargs=2, metavar=("REPO", "PROFILE_JSON"))
    s.add_argument("--detect", metavar="REPO_PATH")
    s.set_defaults(func=cmd_gates)

    s = sub.add_parser("accept")
    s.add_argument("target", help="task_id or batch_id")
    s.add_argument("--into")
    s.add_argument("--all-green", action="store_true")
    s.add_argument("--allow-nagate", action="store_true",
                   help="treat gate verdict 'n/a' (no runnable gates) as acceptable")
    s.add_argument("--squash", action="store_true")  # accepted for compat
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_accept)

    s = sub.add_parser("reject")
    s.add_argument("task_id")
    s.add_argument("--retry", action="store_true")
    s.set_defaults(func=cmd_reject)

    s = sub.add_parser("retry")
    s.add_argument("batch_id")
    s.add_argument("--failed", action="store_true")
    s.add_argument("--shrink", action="store_true")
    s.set_defaults(func=cmd_retry)

    s = sub.add_parser("teardown")
    s.add_argument("batch_id")
    s.add_argument("--keep-accepted", action="store_true")
    s.set_defaults(func=cmd_teardown)

    return p


def main():
    F.ensure_dirs()
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
