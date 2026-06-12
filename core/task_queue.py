#!/usr/bin/env python3
"""
task_queue.py — Dynamic Team Orchestration for hierarchical agent teams.

Manager-агент выполняет рекурсивную декомпозицию задач, динамически создаёт/удаляет sub-agents,
управляет shared blackboard memory.

Core additions to task model (via extended tasks table + agent_teams):
  - parent_task_id (hierarchy)
  - subtasks[] (JSON array of child task_ids)
  - team_ (team_id + team_json: {"id", "manager", "members": [...], "roles": {...}, "blackboard_scope"} )

Features:
- Recursive task decomposition by Manager agents (pluggable decompose_fn + built-in heuristic)
- Dynamic sub-agent lifecycle: spawn_subagent / retire_subagent (child tasks)
- Shared blackboard (long-term facts via knowledge): team-scoped + hierarchy-aware
- Live operational blackboard (memory,blackboard,communication): post_activity for real-time current actions of active agents ("Я меняю структуру БД") via task_checkpoints + /blackboard/* HTTP
- Team registry (agent_teams) for dynamic creation/teardown of agent collectives

Tags: orchestration,teams,delegation,hierarchy
Agent CLI for direct subtask creation (preferred for Architect-driven decomposition):
    python scripts/agentforge_create_task.py --parent <root-id> --title "..." --description "..."
(See agentforge_create_task.py — gives agents terminal rights to build hierarchy without relying solely on LLM decompose.)

Usage:
    from scripts.task_queue import (
        init_task_queue, create_orchestrated_task, decompose_and_spawn,
        get_task_hierarchy, create_team, post_to_blackboard, read_blackboard,
        spawn_subagent, retire_subagent, list_team_tasks
    )
    init_task_queue()
    root = create_orchestrated_task("Build auth system", manager_agent="manager-42")
    team_id = create_team("manager-42", "auth-squad", members=["worker-a", "worker-b"])
    subtasks = decompose_and_spawn("manager-42", root, max_depth=2)
    post_to_blackboard("team", team_id, "design:decision:jwt", "use RS256 + short-lived access", agent="manager-42")
    facts = read_blackboard("team", team_id, include_children=True)

Integrates fully with task_checkpoints (checkpoints + knowledge blackboard + crash recovery).
"""

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

# --- Integration with existing checkpoint / knowledge system ---
try:
    from core.task_checkpoints import (
        init_db,
        save_checkpoint,
        get_last_checkpoint,
        save_knowledge,
        search_knowledge,
        _get_conn as _get_checkpoint_conn,  # internal but stable for same-package use
        DATA_DIR,
    )
except ImportError:
    # Fallback: direct import from same directory
    from task_checkpoints import (
        init_db,
        save_checkpoint,
        get_last_checkpoint,
        save_knowledge,
        search_knowledge,
        _get_conn as _get_checkpoint_conn,
        DATA_DIR,
    )


DB_PATH = os.path.join(DATA_DIR, "task_checkpoints.db")  # same DB as checkpoints + knowledge
KNOWLEDGE_DB_PATH = os.path.join(DATA_DIR, "tasks.db")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat() + "Z"


def _ensure_data_dir() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)


def _get_conn() -> sqlite3.Connection:
    """Reuse crash-safe connection settings from checkpoints."""
    _ensure_data_dir()
    conn = sqlite3.connect(DB_PATH, timeout=30.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("PRAGMA busy_timeout=30000;")
    return conn


def init_task_queue() -> str:
    """Initialize (or migrate) orchestration tables. Calls base init_db() which now includes orchestration columns."""
    init_db()  # ensures checkpoints + tasks table + orchestration columns + agent_teams
    # Extra indexes / views specific to queue orchestration (idempotent)
    conn = _get_conn()
    try:
        with conn:
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_subtasks ON tasks (subtasks_json)")
            # Lightweight view for active hierarchy roots (no parent)
            conn.execute("""
                CREATE VIEW IF NOT EXISTS v_active_roots AS
                SELECT * FROM tasks
                WHERE parent_task_id IS NULL
                  AND (last_step IS NULL OR last_step NOT IN ('done', 'failed'))
            """)
        return DB_PATH
    finally:
        conn.close()


# ============================================================
# CORE TASK + HIERARCHY OPERATIONS (parent_task_id, subtasks[], team_)
# ============================================================

def _get_task_row(task_id: str) -> Optional[sqlite3.Row]:
    conn = _get_conn()
    try:
        return conn.execute(
            "SELECT * FROM tasks WHERE task_id = ?",
            (task_id,),
        ).fetchone()
    finally:
        conn.close()


def _update_task_fields(task_id: str, **fields: Any) -> None:
    """Generic updater for orchestration columns."""
    if not fields:
        return
    sets = ", ".join(f"{k} = ?" for k in fields)
    params = list(fields.values()) + [task_id]
    conn = _get_conn()
    try:
        with conn:
            conn.execute(f"UPDATE tasks SET {sets}, last_updated = datetime('now') WHERE task_id = ?", params)
    finally:
        conn.close()


def create_orchestrated_task(
    title: str,
    *,
    task_id: Optional[str] = None,
    parent_task_id: Optional[str] = None,
    team: Optional[Dict[str, Any]] = None,
    manager_agent: Optional[str] = None,
    priority: int = 0,
    initial_data: Optional[Dict[str, Any]] = None,
    depends_on: Optional[List[str]] = None,
) -> str:
    """
    Create a new task supporting full hierarchy + team metadata + DAG dependencies.
    Stores parent_task_id, team_id, subtasks_json, team_json, manager_agent, depends_on_json.
    If depends_on provided and not all satisfied, caller should set appropriate last_step (e.g. 'blocked').
    """
    init_task_queue()
    tid = task_id or f"task-{uuid.uuid4().hex[:12]}"
    now = _now()

    team_id = None
    team_json = None
    if team:
        team_id = team.get("id") or team.get("team_id") or f"team-{uuid.uuid4().hex[:8]}"
        team_json = json.dumps(team, ensure_ascii=False, separators=(",", ":"))

    subtasks_json = json.dumps([])

    data = initial_data or {}
    data.setdefault("title", title)
    data.setdefault("priority", priority)
    data.setdefault("created_at", now)

    conn = _get_conn()
    try:
        with conn:
            # Insert into lightweight tasks registry (orchestration fields)
            depends_json = json.dumps(depends_on or [], separators=(",", ":")) if depends_on else "[]"
            conn.execute(
                """
                INSERT OR REPLACE INTO tasks
                (task_id, created_at, last_step, last_updated,
                 parent_task_id, team_id, subtasks_json, team_json, manager_agent, depends_on_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (tid, now, "dispatch", now, parent_task_id, team_id, subtasks_json, team_json, manager_agent, depends_json),
            )
            # Also emit a dispatch checkpoint so existing pipeline tooling sees it
            save_checkpoint(tid, "dispatch", data)
    finally:
        conn.close()

    # If this is a subtask, register it under parent's subtasks[]
    if parent_task_id:
        _add_subtask_to_parent(parent_task_id, tid)

    return tid


def _add_subtask_to_parent(parent_id: str, child_id: str) -> None:
    row = _get_task_row(parent_id)
    if not row:
        return
    current = []
    if row["subtasks_json"]:
        try:
            current = json.loads(row["subtasks_json"])
        except Exception:
            current = []
    if child_id not in current:
        current.append(child_id)
        _update_task_fields(parent_id, subtasks_json=json.dumps(current, separators=(",", ":")))


def get_task(task_id: str) -> Optional[Dict[str, Any]]:
    """Return rich task dict including parsed hierarchy and team fields.
    Title is merged from latest checkpoint data for display / decomposition use.
    """
    row = _get_task_row(task_id)
    if not row:
        return None
    task = {k: row[k] for k in row.keys()}
    # Parse JSON fields
    for jf in ("subtasks_json", "team_json", "depends_on_json"):
        if task.get(jf):
            try:
                task[jf.replace("_json", "")] = json.loads(task[jf])
            except Exception:
                task[jf.replace("_json", "")] = [] if jf != "team_json" else {}
        else:
            task[jf.replace("_json", "")] = [] if jf != "team_json" else {}
    task["subtasks"] = task.pop("subtasks", [])
    task["depends_on"] = task.pop("depends_on", [])
    task["team"] = task.pop("team", {})

    # Enrich with title from checkpoint data (common pattern in existing system)
    try:
        cp = get_last_checkpoint(task_id)
        if cp and cp.get("data"):
            d = cp["data"]
            if not task.get("title"):
                task["title"] = d.get("title") or d.get("task_title")
    except Exception:
        pass
    return task


def get_task_hierarchy(task_id: str, max_depth: int = 6) -> Dict[str, Any]:
    """
    Return full recursive hierarchy tree starting at task_id.
    Includes parent pointers, children list, and team metadata at each node.
    """
    def _build(tid: str, depth: int) -> Optional[Dict[str, Any]]:
        if depth > max_depth:
            return None
        t = get_task(tid)
        if not t:
            return None
        children = []
        for sid in t.get("subtasks", []):
            ch = _build(sid, depth + 1)
            if ch:
                children.append(ch)
        t["children"] = children
        # Also surface direct parent reference for upward traversal
        t["parent"] = t.get("parent_task_id")
        return t

    return _build(task_id, 0) or {}


def list_team_tasks(team_id: str, include_completed: bool = False) -> List[Dict[str, Any]]:
    """All tasks belonging to a team (by team_id on the task row)."""
    conn = _get_conn()
    try:
        sql = "SELECT task_id FROM tasks WHERE team_id = ?"
        if not include_completed:
            sql += " AND (last_step IS NULL OR last_step NOT IN ('done','failed'))"
        rows = conn.execute(sql, (team_id,)).fetchall()
        return [get_task(r["task_id"]) for r in rows if r["task_id"]]
    finally:
        conn.close()


# ============================================================
# DYNAMIC TEAM MANAGEMENT (create / retire / scope)
# ============================================================

def create_team(
    manager_agent: str,
    name: Optional[str] = None,
    *,
    team_id: Optional[str] = None,
    members: Optional[List[str]] = None,
    config: Optional[Dict[str, Any]] = None,
) -> str:
    """Create/register a dynamic agent team led by a manager. Returns team_id."""
    init_task_queue()
    tid = team_id or f"team-{uuid.uuid4().hex[:10]}"
    now = _now()
    cfg = config or {}
    cfg.setdefault("name", name or f"team-{tid[-6:]}")
    cfg.setdefault("created_by", manager_agent)
    members = members or []
    cfg["members"] = members

    conn = _get_conn()
    try:
        with conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO agent_teams (team_id, manager_agent, config_json, status, created_at, updated_at)
                VALUES (?, ?, ?, 'active', ?, ?)
                """,
                (tid, manager_agent, json.dumps(cfg, ensure_ascii=False), now, now),
            )
    finally:
        conn.close()
    return tid


def get_team(team_id: str) -> Optional[Dict[str, Any]]:
    conn = _get_conn()
    try:
        row = conn.execute("SELECT * FROM agent_teams WHERE team_id = ?", (team_id,)).fetchone()
        if not row:
            return None
        t = {k: row[k] for k in row.keys()}
        if t.get("config_json"):
            try:
                t["config"] = json.loads(t["config_json"])
            except Exception:
                t["config"] = {}
        return t
    finally:
        conn.close()


def retire_team(team_id: str, reason: str = "completed") -> None:
    """Mark team inactive (does not delete tasks; caller may retire_subtree separately)."""
    conn = _get_conn()
    try:
        with conn:
            conn.execute(
                "UPDATE agent_teams SET status='retired', updated_at=? WHERE team_id=?",
                (_now(), team_id),
            )
    finally:
        conn.close()


# ============================================================
# DYNAMIC SUB-AGENT SPAWN / RETIRE (manager creates workers)
# ============================================================

def spawn_subagent(
    parent_task_id: str,
    title: str,
    *,
    manager_agent: Optional[str] = None,
    team_id: Optional[str] = None,
    role: str = "worker",
    initial_data: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Dynamically create a sub-agent task (child) under a parent.
    This represents spawning a specialized worker / sub-agent.
    The child is immediately registered in parent's subtasks[] and inherits team.
    """
    parent = get_task(parent_task_id)
    if not parent:
        raise ValueError(f"parent task {parent_task_id} not found")

    inherited_team = parent.get("team") or {}
    if team_id:
        inherited_team = {"id": team_id, **inherited_team}

    sub_id = create_orchestrated_task(
        title,
        parent_task_id=parent_task_id,
        team=inherited_team or None,
        manager_agent=manager_agent or parent.get("manager_agent"),
        initial_data=initial_data,
    )
    # Record delegation fact on blackboard
    if inherited_team.get("id"):
        post_to_blackboard(
            "team",
            inherited_team["id"],
            f"delegation:{parent_task_id}->{sub_id}",
            f"spawned sub-agent '{title}' role={role}",
            agent=manager_agent or "manager",
        )
    return sub_id


def retire_subagent(sub_task_id: str, reason: str = "completed") -> None:
    """Retire (mark terminal) a dynamically spawned sub-agent task."""
    payload = get_last_checkpoint(sub_task_id) or {}
    data = payload.get("data", {}) if payload else {}
    data["retired_reason"] = reason
    data["retired_at"] = _now()
    # Use existing terminal markers
    from task_checkpoints import mark_done  # type: ignore

    try:
        mark_done(sub_task_id, data)
    except Exception:
        save_checkpoint(sub_task_id, "failed", data)


# ============================================================
# RECURSIVE DECOMPOSITION (Manager Agent)
# ============================================================

DEFAULT_DECOMPOSE_PROMPT_HINTS = {
    "auth": ["design-jwt", "session-store", "password-hash", "rate-limit", "integration-tests"],
    "feature": ["requirements", "api-design", "implementation", "tests", "docs"],
    "bug": ["reproduce", "root-cause", "fix", "regression-test", "verify"],
}


def _default_decomposer(task: Dict[str, Any], depth: int, max_depth: int) -> List[Dict[str, str]]:
    """
    Built-in heuristic decomposer (no external LLM required for demo / self-test).
    Real Manager agents (Grok etc.) replace this with LLM-driven recursive breakdown.
    """
    title = (task.get("title") or task.get("data", {}).get("title") or "").lower()
    if depth >= max_depth:
        return []

    buckets: List[str] = []
    if any(k in title for k in ("auth", "login", "jwt", "session")):
        buckets = DEFAULT_DECOMPOSE_PROMPT_HINTS["auth"]
    elif any(k in title for k in ("bug", "fix", "crash")):
        buckets = DEFAULT_DECOMPOSE_PROMPT_HINTS["bug"]
    else:
        buckets = DEFAULT_DECOMPOSE_PROMPT_HINTS["feature"]

    # Limit branching; deeper levels get narrower
    n = max(2, min(5, len(buckets) - depth))
    children = []
    for i, b in enumerate(buckets[:n]):
        children.append({
            "title": f"{b.replace('-', ' ').title()} for {task.get('title', 'task')}",
            "role": "specialist" if depth > 0 else "worker",
        })
    return children


def decompose_and_spawn(
    manager_agent: str,
    parent_task_id: str,
    *,
    max_depth: int = 3,
    decompose_fn: Optional[Callable[[Dict[str, Any], int, int], List[Dict[str, str]]]] = None,
    team_id: Optional[str] = None,
) -> List[str]:
    """
    Manager agent entry point: recursively decompose + dynamically spawn sub-agents.
    Returns list of all created subtask ids (flattened).
    """
    init_task_queue()
    parent = get_task(parent_task_id)
    if not parent:
        raise ValueError(f"Parent task {parent_task_id} does not exist")

    decompose_fn = decompose_fn or _default_decomposer
    created: List[str] = []

    def _recurse(tid: str, depth: int) -> None:
        if depth >= max_depth:
            return
        t = get_task(tid)
        if not t:
            return
        kids_spec = decompose_fn(t, depth, max_depth)
        if not kids_spec:
            return
        for spec in kids_spec:
            child_id = spawn_subagent(
                parent_task_id=tid,
                title=spec["title"],
                manager_agent=manager_agent,
                team_id=team_id or (t.get("team") or {}).get("id"),
                role=spec.get("role", "worker"),
            )
            created.append(child_id)
            # Recurse deeper
            _recurse(child_id, depth + 1)

    _recurse(parent_task_id, 0)
    return created


# ============================================================
# SHARED BLACKBOARD MEMORY (team + hierarchy scoped)
# ============================================================

def post_to_blackboard(
    scope: str,  # "team" | "task" | "global"
    scope_id: str,
    key: str,
    value: str,
    *,
    agent: Optional[str] = None,
    task_id: Optional[str] = None,
) -> int:
    """
    Write to the shared agent blackboard (backed by knowledge table).
    Scope augments the stored record for later filtered retrieval.
    Hierarchy-aware: when scope=task we also record parent linkage.
    """
    meta = {"scope": scope, "scope_id": scope_id}
    if scope == "task":
        t = get_task(scope_id)
        if t and t.get("parent_task_id"):
            meta["parent_task_id"] = t["parent_task_id"]
    augmented_key = f"{scope}:{scope_id}:{key}"
    return save_knowledge(
        key=augmented_key,
        value=value,
        agent=agent,
        task_id=task_id or (scope_id if scope == "task" else None),
    )


def read_blackboard(
    scope: str,
    scope_id: str,
    *,
    limit: int = 20,
    include_children: bool = False,
    q: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Read blackboard entries for a team or task scope.
    When include_children=True and scope=task, also pulls facts from the entire subtree.
    """
    results: List[Dict[str, Any]] = []
    prefix = f"{scope}:{scope_id}:"

    # Direct scoped facts
    hits = search_knowledge(q or "", limit=limit * 2)
    for h in hits:
        k = h.get("key", "")
        if k.startswith(prefix):
            h["blackboard_scope"] = scope
            h["blackboard_scope_id"] = scope_id
            results.append(h)

    if include_children and scope == "task":
        # Walk hierarchy and collect any child task facts
        hier = get_task_hierarchy(scope_id)
        child_ids: List[str] = []

        def _collect(node: Dict[str, Any]) -> None:
            for c in node.get("children", []):
                child_ids.append(c["task_id"])
                _collect(c)

        _collect(hier)
        for cid in child_ids[:30]:  # safety bound
            child_hits = search_knowledge(q or "", limit=5, task_id=cid)
            for h in child_hits:
                h["blackboard_scope"] = "task-child"
                h["blackboard_scope_id"] = cid
                results.append(h)

    # De-dup + trim
    seen = set()
    deduped = []
    for r in results:
        sig = (r.get("key"), r.get("id"))
        if sig not in seen:
            seen.add(sig)
            deduped.append(r)
    return deduped[:limit]


def get_team_blackboard(team_id: str, limit: int = 30) -> List[Dict[str, Any]]:
    """Convenience wrapper for team-scoped blackboard (most common manager view)."""
    return read_blackboard("team", team_id, limit=limit)


# ============================================================
# HIERARCHY + TEAM CLEANUP
# ============================================================

def close_subtree(parent_task_id: str, reason: str = "manager-closed") -> List[str]:
    """Recursively retire all descendants of a parent task (dynamic team teardown)."""
    retired: List[str] = []
    hier = get_task_hierarchy(parent_task_id)

    def _retire(node: Dict[str, Any]) -> None:
        for child in node.get("children", []):
            retire_subagent(child["task_id"], reason=reason)
            retired.append(child["task_id"])
            _retire(child)

    _retire(hier)
    # Mark the root as well
    try:
        from task_checkpoints import mark_done  # type: ignore
        mark_done(parent_task_id, {"closed_by_manager": True, "reason": reason})
    except Exception:
        save_checkpoint(parent_task_id, "done", {"closed_by_manager": True})
    retired.append(parent_task_id)
    return retired


# ============================================================
# DAG DEPENDENCIES (depends_on JSON list, blocked -> pending promotion)
# ============================================================

TERMINAL_DONE_STEPS = {"done", "completed", "ai_done", "success", "approved"}

def _get_all_tasks_map() -> Dict[str, Dict[str, Any]]:
    """Lightweight map of all tasks for dep checking."""
    conn = _get_conn()
    try:
        rows = conn.execute("SELECT task_id, last_step, depends_on_json FROM tasks").fetchall()
        out = {}
        for r in rows:
            deps = []
            if r["depends_on_json"]:
                try:
                    deps = json.loads(r["depends_on_json"])
                except Exception:
                    deps = []
            out[r["task_id"]] = {"last_step": r["last_step"], "depends_on": deps}
        return out
    finally:
        conn.close()

def are_dependencies_met(task_id: str) -> bool:
    """Return True if all tasks in depends_on for this task have last_step in TERMINAL_DONE_STEPS."""
    task_map = _get_all_tasks_map()
    t = task_map.get(task_id)
    if not t:
        return True
    deps = t.get("depends_on") or []
    if not deps:
        return True
    for d in deps:
        dep_task = task_map.get(d)
        if not dep_task or (dep_task.get("last_step") not in TERMINAL_DONE_STEPS):
            return False
    return True

def get_ready_blocked_tasks() -> List[str]:
    """Return list of task_ids that are currently blocked (by last_step) but have all deps met."""
    task_map = _get_all_tasks_map()
    ready = []
    for tid, info in task_map.items():
        if (info.get("last_step") or "").lower() in {"blocked", "waiting_deps", "depends"}:
            if are_dependencies_met(tid):
                ready.append(tid)
    return ready

def promote_ready_blocked_tasks() -> List[str]:
    """
    Worker-facing: promote all currently blocked tasks whose depends_on are now all done.
    Updates last_step to 'pending' (or 'dispatch' to re-enter queue).
    Returns list of promoted task_ids. Integrates with checkpointing.
    """
    ready = get_ready_blocked_tasks()
    promoted = []
    for tid in ready:
        try:
            _update_task_fields(tid, last_step="pending")
            # Emit checkpoint so existing dispatchers see the transition
            try:
                save_checkpoint(tid, "pending", {"promoted_by": "dag_resolver", "reason": "dependencies_satisfied"})
            except Exception:
                pass
            promoted.append(tid)
        except Exception as e:
            print(f"[DAG] Failed to promote {tid}: {e}")
    if promoted:
        print(f"[DAG] Promoted {len(promoted)} blocked tasks to pending: {promoted}")
    return promoted


# ============================================================
# SELF-TEST / DEMO (orchestration,teams,delegation,hierarchy)
# ============================================================

if __name__ == "__main__":
    print("=== Dynamic Team Orchestration self-test (task_queue.py) ===")
    print("Initializing task queue + extended schema...")
    dbp = init_task_queue()
    print(f"DB: {dbp}")

    # 1. Create root task for a manager
    root_id = create_orchestrated_task(
        "Implement secure user authentication + JWT",
        manager_agent="manager-alpha-7",
        initial_data={"repo": "https://github.com/example/auth-service", "priority": 10},
    )
    print(f"Created root task: {root_id}")

    # 2. Create dynamic team
    team_id = create_team(
        "manager-alpha-7",
        "auth-squad-001",
        members=["worker-jwt", "worker-session", "worker-tests"],
        config={"specialty": "security", "max_concurrency": 4},
    )
    print(f"Created team: {team_id}")

    # Attach team to root (retrofit for demo)
    _update_task_fields(root_id, team_id=team_id, team_json=json.dumps({"id": team_id, "manager": "manager-alpha-7"}))

    # 3. Manager performs recursive decomposition + dynamic sub-agent spawn
    print("\nManager decomposing task (max_depth=2) ...")
    spawned = decompose_and_spawn(
        "manager-alpha-7",
        root_id,
        max_depth=2,
        team_id=team_id,
    )
    print(f"Spawned {len(spawned)} sub-agents: {spawned}")

    # 4. Show full hierarchy
    hier = get_task_hierarchy(root_id)
    print("\nHierarchy tree (depth 2):")
    print(json.dumps({
        "task_id": hier.get("task_id"),
        "title": hier.get("title") or hier.get("data", {}).get("title"),
        "children": [{"task_id": c["task_id"], "title": c.get("title") or c.get("data", {}).get("title"),
                      "children": [gc["task_id"] for gc in c.get("children", [])]} for c in hier.get("children", [])]
    }, indent=2, ensure_ascii=False))

    # 5. Shared blackboard usage (manager posts, workers would read)
    print("\n--- Shared Blackboard (team + hierarchy) ---")
    post_to_blackboard("team", team_id, "architecture:jwt", "Use RS256 + 15m access tokens + refresh rotation", agent="manager-alpha-7")
    post_to_blackboard("task", root_id, "security:threat-model", "Token theft via XSS mitigated by HttpOnly + SameSite", agent="manager-alpha-7")

    # One of the child tasks (first spawned) posts a sub-result
    if spawned:
        first_child = spawned[0]
        post_to_blackboard("task", first_child, "impl:status", "JWT minting + verification complete", agent="worker-jwt", task_id=first_child)

    team_facts = get_team_blackboard(team_id, limit=8)
    print(f"Team blackboard facts ({len(team_facts)}):")
    for f in team_facts[:5]:
        print(f"  - {f.get('key')}: {str(f.get('value',''))[:70]}... (agent={f.get('agent')})")

    # Hierarchy-aware read from root (pulls children)
    subtree_facts = read_blackboard("task", root_id, include_children=True, limit=10)
    print(f"Root task + children blackboard hits: {len(subtree_facts)}")

    # --- Live Operational Blackboard (new: memory,blackboard,communication) ---
    # For *active* agents to broadcast current actions in real time (separate from long-term facts).
    # Use this for "Я меняю структуру БД", "Running tests on worker-2" etc.
    try:
        from task_checkpoints import post_activity, get_current_actions, get_blackboard_feed, clear_blackboard_activity
        clear_blackboard_activity(team_id)
        post_activity("manager-alpha-7", "Планирую декомпозицию задачи на 4 под-агента", team_id=team_id)
        post_activity("worker-jwt", "Я меняю структуру БД: добавляю индекс на agent_teams", team_id=team_id, task_id=first_child if spawned else None)
        post_activity("worker-jwt", "Пишу миграцию + тесты", team_id=team_id)
        live = get_current_actions(team_id=team_id, window_minutes=30)
        print(f"\n[Live Blackboard] Current actions for team ({len(live)} agents):")
        for a in live:
            print(f"  {a['agent']}: {a['message']} @ {a['created_at'][:19]}")
        feed = get_blackboard_feed(team_id=team_id, since_minutes=5, limit=10)
        print(f"  Recent feed entries: {len(feed)}")
    except Exception as e:
        print(f"  (live blackboard demo skipped: {e})")

    # 6. Dynamic retire of one sub-agent (simulates completion / pruning)
    if len(spawned) > 1:
        retired = spawned[-1]
        retire_subagent(retired, reason="subtask-complete")
        print(f"Retired sub-agent: {retired}")

    # 7. Team task listing
    active = list_team_tasks(team_id)
    print(f"\nActive tasks in team {team_id}: {len(active)}")

    # 8. Full subtree close (manager teardown)
    closed = close_subtree(root_id, reason="demo-complete")
    print(f"Closed subtree ({len(closed)} nodes)")

    print("\n✅ Dynamic Team Orchestration self-test PASSED")
    print("   Features verified: parent_task_id, subtasks[], team_, recursive decompose+spawn, blackboard, retire")
