#!/usr/bin/env python3
"""
State Checkpoints: crash recovery for tasks (Planly Tasks on Jetson).

Saves task state after every pipeline step so that if Jetson crashes
(power loss, OOM, kernel panic, thermal throttle), on restart the
task runner can resume from the last successful checkpoint instead of
repeating expensive work (git clone, full Grok sessions, long CI runs).

Table schema (as specified):
  checkpoints(task_id, step, data_json, created_at)

+ RAG / Knowledge (tags: rag,knowledge):
  FTS5-powered full-text search over task titles, descriptions, outcomes and logs.
  Enables "similar past tasks" retrieval for RAG context injection into Grok prompts.
  Search similar engineering tasks by natural language query (e.g. "dark mode crash on login").

  Virtual table: tasks_fts (task_id, title, content, tags, outcome)

+ Shared Memory: общая база знаний агентов (memory,knowledge,database,rag)
  Explicit key-value store for agents to persist facts, learnings, decisions across tasks.
  Agents should save important outcomes / extracted knowledge AFTER task completion (done/failed).
  Table in tasks.db: knowledge(id, agent, task_id, key, value, embedding_hash, created_at)
  Searchable via FTS5 (knowledge_fts) + direct key lookup.
  HTTP: POST /knowledge , GET /knowledge/search?q=...
  Agents auto-search similar facts before starting work for context injection.

+ Team Operational Memory (Blackboard): оперативная память команды (memory,blackboard,communication)
  Live shared board for *active* agents. Agents publish current actions in real time
  (e.g. 'Я меняю структуру БД') so other agents see what teammates are doing *now*.
  Tables: blackboard_activity in task_checkpoints.db (agent, team_id, task_id, message, created_at)
  HTTP (via gateway): POST /blackboard/activity , GET /blackboard/feed , GET /blackboard/current
  Use post_activity() / get_current_actions() from agent code or task_queue.

Steps (in order):
  dispatch -> git_clone -> grok_start -> grok_done -> ci_start -> ci_done -> review -> done

Usage:
  from scripts.task_checkpoints import (
      init_db, save_checkpoint, get_last_checkpoint, resume_or_start,
      search_similar_tasks, get_rag_context,
      save_knowledge, search_knowledge, init_knowledge_db,
      post_activity, get_blackboard_feed, get_current_actions, clear_blackboard_activity
  )

  init_db()
  save_checkpoint(task_id, "dispatch", {"repo": "https://...", "title": "..."})
  ...
  similar = search_similar_tasks("crash recovery git revert", limit=3)
  context = get_rag_context("implement safe auto-rollback on CI fail", limit=3)
  # inject `context` into your LLM system prompt for RAG over past task knowledge

  # Shared Memory for agents (post-task):
  save_knowledge(agent="grok", task_id=task_id, key="learned_pattern", value="always revert on ci_fail")
  facts = search_knowledge("revert ci", limit=5)

  # Live team blackboard (operational, during execution):
  post_activity("grok-worker-3", "Я меняю структуру БД: добавляю индекс", team_id="team-7")
  current = get_current_actions(team_id="team-7")  # who is doing what right now
  feed = get_blackboard_feed(team_id="team-7", since_minutes=10)

Recovery:
  On gateway or task-runner startup, call list_recoverable_tasks()
  to find interrupted work and continue.

Multi-Repo (scale):
  Every checkpoint can (and should) carry "repo": "https://github.com/owner/name".
  The runner uses this to prepare an isolated clone:
      save_checkpoint(tid, "dispatch", {"title": "...", "repo": "https://github.com/agx/akson-data"})
      # later
      repo = cp["data"].get("repo")
      clone_path = prepare_or_get_repo_workspace(repo)   # your helper using git clone + worktree
  See grok_worker.sh:get_repo_workdir + run_task for the reference implementation.
"""

import sqlite3
import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

# --- Configuration ---
# AgentForge: resolve DATA_DIR relative to project root
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(_PROJECT_ROOT, "data")
DB_PATH = os.path.join(DATA_DIR, "task_checkpoints.db")
# Shared Memory knowledge base lives in its own DB per spec (tasks.db)
KNOWLEDGE_DB_PATH = os.path.join(DATA_DIR, "tasks.db")

# Canonical ordered steps for a Grok-powered task pipeline
PIPELINE_STEPS = [
    "dispatch",
    "git_clone",
    "grok_start",
    "grok_done",
    "ci_start",
    "ci_done",
    "ci_failed",     # CI failed on the changes (triggers auto-rollback in grok_worker)
    "rollback",      # Auto git revert executed by grok_worker to protect main
    "review",
    "done",          # terminal success
    "failed",        # terminal failure (with error in data_json)
]

# --- Internal helpers ---

def _ensure_data_dir() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)

def _get_conn() -> sqlite3.Connection:
    """Create a crash-safe SQLite connection (WAL + sane pragmas)."""
    _ensure_data_dir()
    conn = sqlite3.connect(DB_PATH, timeout=30.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    # Crash recovery friendly settings
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("PRAGMA busy_timeout=30000;")
    return conn


def _get_knowledge_conn() -> sqlite3.Connection:
    """Dedicated connection for agent shared memory (knowledge table in tasks.db)."""
    _ensure_data_dir()
    conn = sqlite3.connect(KNOWLEDGE_DB_PATH, timeout=30.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA busy_timeout=30000;")
    return conn


def init_knowledge_db() -> str:
    """
    Initialize (or migrate) the shared agent knowledge tables in tasks.db.
    Idempotent. Creates:
      knowledge(id, agent, task_id, key, value, embedding_hash, created_at)
      + supporting indexes + knowledge_fts (FTS5)
    Returns the DB path.
    """
    _ensure_data_dir()
    conn = _get_knowledge_conn()
    try:
        # Core table exactly as specified
        conn.execute("""
            CREATE TABLE IF NOT EXISTS knowledge (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                agent           TEXT,
                task_id         TEXT,
                key             TEXT NOT NULL,
                value           TEXT NOT NULL,
                embedding_hash  TEXT,
                created_at      TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_knowledge_agent ON knowledge (agent)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_knowledge_task ON knowledge (task_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_knowledge_key ON knowledge (key)")

        # FTS5 for fast search over key+value (agent/task_id also indexed for filters)
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(
                id UNINDEXED,
                agent,
                task_id,
                key,
                value,
                tokenize = 'unicode61 remove_diacritics 2'
            )
        """)
        conn.commit()
    finally:
        conn.close()
    return KNOWLEDGE_DB_PATH


def init_db() -> str:
    """
    Initialize (or migrate) the checkpoints table.
    Idempotent and safe to call on every startup / before any save.
    Returns the DB path for logging.
    """
    _ensure_data_dir()
    conn = _get_conn()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS checkpoints (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id      TEXT NOT NULL,
                step         TEXT NOT NULL,
                data_json    TEXT NOT NULL,
                created_at   TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        # Efficient lookup of the latest checkpoint per task
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_checkpoints_task_created
            ON checkpoints (task_id, created_at DESC)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_checkpoints_step
            ON checkpoints (step)
        """)
        # Optional: lightweight task registry derived from checkpoints
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                task_id      TEXT PRIMARY KEY,
                created_at   TEXT NOT NULL DEFAULT (datetime('now')),
                last_step    TEXT,
                last_updated TEXT
            )
        """)

        # --- Dynamic Team Orchestration schema (orchestration,teams,delegation,hierarchy) ---
        # Extended task registry for hierarchical teams + blackboard scoping.
        # Added columns are nullable for backward compat with existing tasks.
        _ensure_orchestration_schema(conn)

        # Team Operational Memory / Blackboard (live activity for active agents)
        # memory,blackboard,communication — real-time "what is the team doing now"
        _ensure_blackboard_schema(conn)

        # RAG / Knowledge: FTS5 virtual table for similar task search (rag,knowledge)
        # Used for "Поиск похожих задач" over task titles, descriptions, outcomes from logs/checkpoints.
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS tasks_fts USING fts5(
                task_id UNINDEXED,
                title,
                content,
                tags,
                outcome,
                tokenize = 'unicode61 remove_diacritics 2'
            )
        """)
        # Note: we do not create external content table to keep it simple and self-contained.
        # Population happens via _index_task_fts on dispatch + terminal steps.

        conn.commit()
    finally:
        conn.close()

    # Shared Memory knowledge lives in dedicated tasks.db (see init_knowledge_db)
    init_knowledge_db()
    return DB_PATH

def _upsert_task_meta(conn: sqlite3.Connection, task_id: str, step: str) -> None:
    conn.execute("""
        INSERT INTO tasks (task_id, last_step, last_updated)
        VALUES (?, ?, datetime('now'))
        ON CONFLICT(task_id) DO UPDATE SET
            last_step = excluded.last_step,
            last_updated = excluded.last_updated
    """, (task_id, step))


def _ensure_orchestration_schema(conn: sqlite3.Connection) -> None:
    """
    Idempotent migration for Dynamic Team Orchestration fields (parent_task_id, subtasks, team, depends_on for DAG).
    Adds columns to `tasks` table + supporting indexes/tables.
    Safe on existing DBs; all new fields nullable.
    Tags: orchestration,teams,delegation,hierarchy,dag
    """
    # Use table_info to avoid duplicate column errors on old SQLite
    cols = {row[1] for row in conn.execute("PRAGMA table_info(tasks)").fetchall()}
    alters = []
    if "parent_task_id" not in cols:
        alters.append("ALTER TABLE tasks ADD COLUMN parent_task_id TEXT")
    if "team_id" not in cols:
        alters.append("ALTER TABLE tasks ADD COLUMN team_id TEXT")
    if "subtasks_json" not in cols:
        alters.append("ALTER TABLE tasks ADD COLUMN subtasks_json TEXT")
    if "team_json" not in cols:
        alters.append("ALTER TABLE tasks ADD COLUMN team_json TEXT")
    if "manager_agent" not in cols:
        alters.append("ALTER TABLE tasks ADD COLUMN manager_agent TEXT")
    if "depends_on_json" not in cols:
        alters.append("ALTER TABLE tasks ADD COLUMN depends_on_json TEXT")
    if "retry_count" not in cols:
        alters.append("ALTER TABLE tasks ADD COLUMN retry_count INTEGER DEFAULT 0")
    if "tokens_used" not in cols:
        alters.append("ALTER TABLE tasks ADD COLUMN tokens_used INTEGER DEFAULT 0")
    if "cost_usd" not in cols:
        alters.append("ALTER TABLE tasks ADD COLUMN cost_usd REAL DEFAULT 0.0")

    for sql in alters:
        try:
            conn.execute(sql)
        except sqlite3.OperationalError:
            pass  # column may have been added concurrently

    # Indexes for hierarchy traversal and team scoping
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_parent ON tasks (parent_task_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_team ON tasks (team_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_manager ON tasks (manager_agent)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_depends ON tasks (depends_on_json)")

    # Optional dedicated table for team registry (for dynamic agent team lifecycle)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agent_teams (
            team_id       TEXT PRIMARY KEY,
            manager_agent TEXT,
            config_json   TEXT,
            status        TEXT DEFAULT 'active',
            created_at    TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at    TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_teams_manager ON agent_teams (manager_agent)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_teams_status ON agent_teams (status)")


def _index_task_fts(conn: sqlite3.Connection, task_id: str) -> None:
    """
    (Re)build the FTS5 document for a task from its full checkpoint history.
    This powers RAG "search similar tasks" via FTS5 MATCH + bm25 ranking.
    Called automatically from save_checkpoint (inside transaction).
    """
    conn.execute("DELETE FROM tasks_fts WHERE task_id = ?", (task_id,))

    rows = conn.execute(
        "SELECT step, data_json FROM checkpoints WHERE task_id = ? ORDER BY created_at, id",
        (task_id,)
    ).fetchall()
    if not rows:
        return

    title = ""
    tags: list[str] = []
    content_parts: list[str] = []
    outcome = "in_progress"

    for r in rows:
        try:
            d = json.loads(r["data_json"])
        except Exception:
            continue
        step = r["step"]

        # Always emit the step name — very useful for log-style queries ("ci_failed", "rollback" etc)
        content_parts.append(f"step:{step}")

        # Capture title as early as possible (usually at dispatch)
        if not title:
            title = (d.get("title") or d.get("task_title") or d.get("repo") or "")[:400]

        # Collect rich text for search (title, errors, reasons, branches, repos, etc.)
        for key in ("title", "description", "repo", "branch", "error", "reason", "message", "details"):
            if val := d.get(key):
                content_parts.append(f"{key}:{val}")

        if err := d.get("error"):
            content_parts.append(f"error:{err}")
            content_parts.append(f"fail:{step}")

        # Tag important events for better filtering in queries (ci_failed, rollback are gold for RAG)
        if step in ("ci_failed", "rollback", "failed"):
            tags.append(step)
            content_parts.append(step)

        if step == "done":
            outcome = "success"
        elif step == "failed":
            outcome = "failed:" + str(d.get("error", ""))[:180]

    # Also pull latest task meta
    meta = conn.execute(
        "SELECT last_step FROM tasks WHERE task_id = ?",
        (task_id,)
    ).fetchone()
    if meta and meta["last_step"] in ("done", "failed"):
        outcome = "success" if meta["last_step"] == "done" else outcome

    content = " ".join(content_parts)[:6000]
    tags_str = ",".join(sorted(set(tags))) if tags else ""

    conn.execute(
        """INSERT INTO tasks_fts (task_id, title, content, tags, outcome)
           VALUES (?, ?, ?, ?, ?)""",
        (task_id, title or task_id, content, tags_str, outcome)
    )


# ============================================================
# SHARED MEMORY / AGENT KNOWLEDGE BASE (memory,knowledge,database,rag)
# ============================================================

def _index_knowledge_fts(conn: sqlite3.Connection, knowledge_id: int) -> None:
    """Index single knowledge row into FTS (called inside save transaction on knowledge DB)."""
    row = conn.execute(
        "SELECT id, agent, task_id, key, value FROM knowledge WHERE id = ?",
        (knowledge_id,)
    ).fetchone()
    if not row:
        return
    conn.execute(
        "INSERT INTO knowledge_fts (id, agent, task_id, key, value) VALUES (?, ?, ?, ?, ?)",
        (row["id"], row["agent"] or "", row["task_id"] or "", row["key"], row["value"])
    )


def save_knowledge(
    key: str,
    value: str,
    agent: Optional[str] = None,
    task_id: Optional[str] = None,
    embedding_hash: Optional[str] = None,
) -> int:
    """
    Save a fact into the shared agent knowledge base (post-task learning).
    Agents call this after "done" or "failed" to persist reusable insights.

    Table lives in tasks.db (per spec: {id,agent,task_id,key,value,embedding_hash,created_at}).

    Returns the new row id.
    Example:
        save_knowledge("pattern:ci_failure", "Always run git revert before review",
                       agent="grok-4", task_id="t-123")
    """
    if not key or not value:
        raise ValueError("key and value are required")

    _ensure_data_dir()
    now = datetime.utcnow().isoformat() + "Z"

    conn = _get_knowledge_conn()
    try:
        with conn:
            cur = conn.execute(
                """
                INSERT INTO knowledge (agent, task_id, key, value, embedding_hash, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (agent, task_id, key, value, embedding_hash, now),
            )
            kid = cur.lastrowid
            _index_knowledge_fts(conn, kid)
        return kid
    finally:
        conn.close()


def search_knowledge(
    q: str,
    limit: int = 10,
    agent: Optional[str] = None,
    task_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Search the shared knowledge base. Uses FTS5 (bm25) when q provided,
    falls back to recent entries if q empty.
    Supports optional agent / task_id filters.

    Returns list of rows with score when FTS used.
    """
    q = (q or "").strip()
    conn = _get_knowledge_conn()
    try:
        init_knowledge_db()  # ensure knowledge tables in tasks.db

        params: list = []
        where = []
        if agent:
            where.append("k.agent = ?")
            params.append(agent)
        if task_id:
            where.append("k.task_id = ?")
            params.append(task_id)

        if not q:
            # No query: return most recent knowledge (respecting filters)
            sql = f"""
                SELECT k.id, k.agent, k.task_id, k.key, k.value, k.embedding_hash, k.created_at
                FROM knowledge k
                {"WHERE " + " AND ".join(where) if where else ""}
                ORDER BY k.created_at DESC, k.id DESC
                LIMIT ?
            """
            params.append(limit)
            rows = conn.execute(sql, params).fetchall()
            return [
                {
                    "id": r["id"],
                    "agent": r["agent"],
                    "task_id": r["task_id"],
                    "key": r["key"],
                    "value": r["value"],
                    "embedding_hash": r["embedding_hash"],
                    "created_at": r["created_at"],
                }
                for r in rows
            ]

        # FTS5 search with bm25
        import re
        def _make_fts_query(user_query: str) -> str:
            tokens = re.findall(r'\S+', user_query)
            safe = []
            for tok in tokens:
                if re.search(r'[^a-zA-Z0-9_]', tok):
                    safe.append('"' + tok.replace('"', '""') + '"')
                else:
                    safe.append(tok)
            return " ".join(safe)

        safe_q = _make_fts_query(q)
        where_clause = ("WHERE " + " AND ".join(where) + " AND ") if where else "WHERE "
        # Join FTS for ranking + filter
        sql = f"""
            SELECT
                k.id, k.agent, k.task_id, k.key, k.value, k.embedding_hash, k.created_at,
                bm25(knowledge_fts) AS score
            FROM knowledge_fts f
            JOIN knowledge k ON k.id = f.id
            {where_clause} knowledge_fts MATCH ?
            ORDER BY bm25(knowledge_fts) ASC
            LIMIT ?
        """
        params_with_q = params + [safe_q, limit]
        rows = conn.execute(sql, params_with_q).fetchall()

        results = []
        for r in rows:
            results.append({
                "id": r["id"],
                "agent": r["agent"],
                "task_id": r["task_id"],
                "key": r["key"],
                "value": r["value"],
                "embedding_hash": r["embedding_hash"],
                "created_at": r["created_at"],
                "score": float(r["score"]) if r["score"] is not None else 0.0,
            })
        return results
    finally:
        conn.close()


def clear_knowledge(agent: Optional[str] = None, task_id: Optional[str] = None) -> int:
    """Test helper: delete knowledge rows (optionally filtered). Returns deleted count. Operates on tasks.db."""
    conn = _get_knowledge_conn()
    try:
        with conn:
            if agent and task_id:
                res = conn.execute("DELETE FROM knowledge WHERE agent=? AND task_id=?", (agent, task_id))
            elif agent:
                res = conn.execute("DELETE FROM knowledge WHERE agent=?", (agent,))
            elif task_id:
                res = conn.execute("DELETE FROM knowledge WHERE task_id=?", (task_id,))
            else:
                res = conn.execute("DELETE FROM knowledge")
            # FTS is contentless in practice for this use; rebuild not strictly needed (search ignores orphans)
            conn.execute("DELETE FROM knowledge_fts")
        return res.rowcount if hasattr(res, 'rowcount') else 0
    finally:
        conn.close()


def save_checkpoint(task_id: str, step: str, data: Dict[str, Any]) -> None:
    """
    Persist state AFTER a pipeline step completes successfully.
    Always call this at the end of each of:
        dispatch, git_clone, grok_start, grok_done, ci_start, ci_done, review, done/failed
    """
    if step not in PIPELINE_STEPS:
        # allow custom steps but warn in practice
        pass

    _ensure_data_dir()
    data_json = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    now = datetime.utcnow().isoformat() + "Z"

    conn = _get_conn()
    try:
        with conn:
            conn.execute(
                "INSERT INTO checkpoints (task_id, step, data_json, created_at) VALUES (?, ?, ?, ?)",
                (task_id, step, data_json, now)
            )
            _upsert_task_meta(conn, task_id, step)
            _index_task_fts(conn, task_id)
    finally:
        conn.close()

def get_last_checkpoint(task_id: str) -> Optional[Dict[str, Any]]:
    """
    Return the most recent checkpoint for a task (or None).
    Shape:
      {
        "task_id": "...",
        "step": "grok_done",
        "data": { ...original dict... },
        "created_at": "2026-04-..."
      }
    """
    conn = _get_conn()
    try:
        row = conn.execute(
            """
            SELECT task_id, step, data_json, created_at
            FROM checkpoints
            WHERE task_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (task_id,)
        ).fetchone()
        if not row:
            return None
        return {
            "task_id": row["task_id"],
            "step": row["step"],
            "data": json.loads(row["data_json"]),
            "created_at": row["created_at"],
        }
    finally:
        conn.close()

def get_last_step(task_id: str) -> Optional[str]:
    """Just the step name of the latest checkpoint (or None)."""
    cp = get_last_checkpoint(task_id)
    return cp["step"] if cp else None

def list_recoverable_tasks() -> List[Dict[str, Any]]:
    """
    Tasks that have started but never reached a terminal step ("done" or "failed").
    Useful at startup to automatically resume crashed / interrupted work.
    """
    conn = _get_conn()
    try:
        rows = conn.execute(
            """
            SELECT t.task_id, t.last_step, t.last_updated,
                   (SELECT data_json FROM checkpoints c
                    WHERE c.task_id = t.task_id
                    ORDER BY c.created_at DESC, c.id DESC LIMIT 1) as last_data
            FROM tasks t
            WHERE t.last_step NOT IN ('done', 'failed')
            ORDER BY t.last_updated DESC
            """
        ).fetchall()

        result = []
        for r in rows:
            data = json.loads(r["last_data"]) if r["last_data"] else {}
            result.append({
                "task_id": r["task_id"],
                "last_step": r["last_step"],
                "last_updated": r["last_updated"],
                "data": data,
            })
        return result
    finally:
        conn.close()

def get_all_checkpoints(task_id: str) -> List[Dict[str, Any]]:
    """Full history for debugging / audit."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT step, data_json, created_at FROM checkpoints WHERE task_id = ? ORDER BY created_at, id",
            (task_id,)
        ).fetchall()
        return [
            {"step": r["step"], "data": json.loads(r["data_json"]), "created_at": r["created_at"]}
            for r in rows
        ]
    finally:
        conn.close()

def resume_or_start(task_id: str, initial_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    High-level helper for task runners.

    Returns a dict:
      {
        "task_id": "...",
        "last_step": "grok_done" | None,
        "data": {...merged...},
        "is_resume": bool,
        "next_step": "ci_start" | "dispatch"   # suggested next action
      }
    """
    init_db()
    existing = get_last_checkpoint(task_id)

    if existing:
        data = existing["data"].copy()
        last = existing["step"]
        # Merge any new initial_data on top (rarely needed)
        if initial_data:
            data.update(initial_data)
        is_resume = last not in ("done", "failed")
        # Determine suggested next step (simple linear progression)
        try:
            idx = PIPELINE_STEPS.index(last)
            next_step = PIPELINE_STEPS[idx + 1] if idx + 1 < len(PIPELINE_STEPS) else "done"
        except ValueError:
            next_step = "dispatch"
        return {
            "task_id": task_id,
            "last_step": last,
            "data": data,
            "is_resume": is_resume,
            "next_step": next_step,
        }
    else:
        # brand new task
        if initial_data:
            save_checkpoint(task_id, "dispatch", initial_data)
        return {
            "task_id": task_id,
            "last_step": None,
            "data": initial_data or {},
            "is_resume": False,
            "next_step": "dispatch",
        }

def clear_task(task_id: str) -> None:
    """Dangerous: remove all history for a task (testing / reset only)."""
    conn = _get_conn()
    try:
        with conn:
            conn.execute("DELETE FROM checkpoints WHERE task_id = ?", (task_id,))
            conn.execute("DELETE FROM tasks WHERE task_id = ?", (task_id,))
            conn.execute("DELETE FROM tasks_fts WHERE task_id = ?", (task_id,))
    finally:
        conn.close()

# --- Convenience: mark terminal states ---
def mark_done(task_id: str, final_data: Optional[Dict[str, Any]] = None) -> None:
    data = final_data or get_last_checkpoint(task_id)["data"] if get_last_checkpoint(task_id) else {}
    data.setdefault("completed_at", datetime.utcnow().isoformat() + "Z")
    save_checkpoint(task_id, "done", data)

def mark_failed(task_id: str, error: str, data: Optional[Dict[str, Any]] = None) -> None:
    payload = (data or (get_last_checkpoint(task_id)["data"] if get_last_checkpoint(task_id) else {})).copy()
    payload["error"] = error
    payload["failed_at"] = datetime.utcnow().isoformat() + "Z"
    save_checkpoint(task_id, "failed", payload)


# ============================================================
# RAG / KNOWLEDGE: FTS5 search for similar tasks (rag,knowledge)
# "Поиск похожих задач через FTS5" — lightweight keyword/semantic-ish retrieval
# over past task titles, descriptions, outcomes and log-derived content.
# Used to build RAG context blocks for Grok prompts so the agent learns from
# similar historical tasks (success patterns, failure modes, rollback cases, etc).
# ============================================================

def search_similar_tasks(query: str, limit: int = 6) -> List[Dict[str, Any]]:
    """
    Full-text search of past tasks using SQLite FTS5 + bm25 ranking.

    Returns the most relevant previous tasks for RAG context.
    Each result contains:
      - task_id, title, outcome ("success" / "failed:msg" / "in_progress")
      - last_step, last_updated
      - score (lower bm25 = better match)
      - snippet (concatenated searchable text from checkpoints)
      - data (selected useful keys from latest checkpoint)

    Example usage for RAG:
        similar = search_similar_tasks("dark mode crash recovery", limit=3)
        rag_context = "\\n".join(f"- {s['title']} -> {s['outcome']}" for s in similar)
    """
    q = (query or "").strip()
    if not q:
        return []

    conn = _get_conn()
    try:
        # Make sure schema (including FTS) exists
        init_db()

        # Robust FTS5 query builder:
        # - Split user query into tokens
        # - Quote tokens containing special characters (hyphen, colon, etc.)
        # - This supports both "dark mode" and "ci-failed" / "auto-rollback" style searches
        def _make_fts_query(user_query: str) -> str:
            import re
            tokens = re.findall(r'\S+', user_query)
            safe_tokens = []
            for tok in tokens:
                if re.search(r'[^a-zA-Z0-9_]', tok):
                    safe_tokens.append('"' + tok.replace('"', '""') + '"')
                else:
                    safe_tokens.append(tok)
            return " ".join(safe_tokens)  # implicit AND in FTS5

        safe_q = _make_fts_query(q)

        # FTS5 MATCH query with bm25 ranking (built-in, no extra config needed)
        # We join back to `tasks` for current status.
        sql = """
            SELECT
                f.task_id,
                f.title,
                f.outcome,
                f.content,
                f.tags,
                t.last_step,
                t.last_updated,
                bm25(tasks_fts) AS score
            FROM tasks_fts f
            JOIN tasks t USING (task_id)
            WHERE tasks_fts MATCH ?
            ORDER BY bm25(tasks_fts) ASC
            LIMIT ?
        """
        rows = conn.execute(sql, (safe_q, limit)).fetchall()

        results: List[Dict[str, Any]] = []
        for r in rows:
            # Pull the most recent full data snapshot (for RAG to know what was done)
            last = conn.execute(
                """
                SELECT step, data_json FROM checkpoints
                WHERE task_id = ?
                ORDER BY created_at DESC, id DESC LIMIT 1
                """,
                (r["task_id"],)
            ).fetchone()

            data = {}
            if last:
                try:
                    full = json.loads(last["data_json"])
                    # Keep only high-value keys for context injection (avoid huge payloads)
                    for k in ("title", "repo", "branch", "error", "reason", "grok_session_id", "files_changed"):
                        if k in full:
                            data[k] = full[k]
                    data["last_checkpoint_step"] = last["step"]
                except Exception:
                    pass

            results.append({
                "task_id": r["task_id"],
                "title": r["title"] or "",
                "outcome": r["outcome"] or "unknown",
                "last_step": r["last_step"],
                "last_updated": r["last_updated"],
                "score": float(r["score"]) if r["score"] is not None else 0.0,
                "tags": r["tags"] or "",
                "snippet": (r["content"] or "")[:420],
                "data": data,
            })
        return results
    finally:
        conn.close()


def get_rag_context(query: str, limit: int = 4, max_chars: int = 1800) -> str:
    """
    Convenience: return a compact multi-line string ready to paste into an LLM prompt
    as "Similar past tasks (RAG via FTS5):".
    Perfect for grok_worker / any autonomous agent before starting new work.
    """
    hits = search_similar_tasks(query, limit=limit)
    if not hits:
        return ""
    lines = ["### Similar past tasks (retrieved via FTS5):"]
    total = 0
    for h in hits:
        line = f"- [{h['task_id']}] {h['title'][:80]} → {h['outcome']} (last: {h['last_step']})"
        if total + len(line) > max_chars:
            break
        lines.append(line)
        total += len(line)
    lines.append("---")
    return "\n".join(lines)


# Back-compat alias referenced in module docstring
rag_retrieve_knowledge_context = get_rag_context


def perform_git_auto_rollback(
    clone_path: str,
    task_id: str,
    ci_run_id: Optional[str] = None,
    main_ref: str = "origin/main",
    reason: str = "CI failed",
) -> Dict[str, Any]:
    """
    Git Auto-Rollback on CI failure.

    Finds all commits on the current feature branch since main_ref,
    reverts them safely (accumulated --no-commit, single final commit),
    and records a clear audit trail.

    Returns a dict:
      {"status": "reverted"|"no-op"|"conflict"|"error", "revert_commit": "...", ...}

    IMPORTANT:
    - Operates ONLY inside the provided isolated clone_path (never host repo).
    - Feature branches only: the worker creates "grok-*" branches and never
      commits directly to main locally.
    - The resulting revert commit makes any future merge-to-main safe.
    """
    import subprocess

    if not os.path.isdir(os.path.join(clone_path, ".git")):
        return {"status": "skipped", "reason": "no .git directory", "clone_path": clone_path}

    original_cwd = os.getcwd()
    try:
        os.chdir(clone_path)

        # Best-effort fetch (shallow clones may be limited). Skip for local refs (tests)
        if "origin/" in main_ref or main_ref.startswith("origin"):
            subprocess.run(
                ["git", "fetch", "origin", "main", "--depth=50"],
                check=False, capture_output=True, text=True
            )

        try:
            branch = subprocess.check_output(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"], text=True
            ).strip()
        except subprocess.CalledProcessError:
            branch = "HEAD"

        # Support both "origin/main" and local "main" (for tests / non-remote clones)
        rev_list_ref = main_ref
        revs_out = subprocess.run(
            ["git", "rev-list", "--reverse", f"{rev_list_ref}..HEAD"],
            capture_output=True, text=True
        )
        revs = [r for r in revs_out.stdout.strip().splitlines() if r]

        # Robust fallback for local test repos or non-standard default branches (master vs main etc.)
        # Critical for reliable "git revert on CI fail" in all environments.
        if not revs:
            for fallback in (main_ref, "main", "master", "origin/main", "origin/master"):
                if fallback == rev_list_ref:
                    continue
                try:
                    revs_out = subprocess.run(
                        ["git", "rev-list", "--reverse", f"{fallback}..HEAD"],
                        capture_output=True, text=True
                    )
                    tmp = [r for r in revs_out.stdout.strip().splitlines() if r]
                    if tmp:
                        revs = tmp
                        rev_list_ref = fallback
                        break
                except Exception:
                    pass

        if not revs:
            return {"status": "no-op", "branch": branch, "reason": f"no commits beyond {main_ref}"}

        reverted: list[str] = []
        for rev in reversed(revs):  # newest → oldest for revert order
            rc = subprocess.run(
                ["git", "revert", "--no-commit", rev],
                capture_output=True, text=True
            )
            if rc.returncode != 0:
                subprocess.run(["git", "revert", "--abort"], check=False)
                return {
                    "status": "conflict",
                    "branch": branch,
                    "attempted": reverted,
                    "failed_on": rev,
                    "stderr": rc.stderr[:600],
                }
            reverted.append(rev[:8])

        short = ", ".join(reverted[:5]) + (f" (+{len(reverted)-5} more)" if len(reverted) > 5 else "")
        msg = (
            f"Revert: auto-rollback after CI failure (task {task_id})\n\n"
            f"Reason: {reason}\n"
            f"CI run: {ci_run_id or 'local'}\n\n"
            f"Tags: git,ci,safety\n\n"
            f"Reverted commits (newest first): {short}\n\n"
            f"This commit guarantees the main branch is never broken by failed Grok/agent changes.\n"
            f"Feature branch: {branch}\n"
            f"Generated by grok_worker / perform_git_auto_rollback.\n"
        )

        c_rc = subprocess.run(["git", "commit", "-m", msg], capture_output=True, text=True)
        if c_rc.returncode != 0:
            return {"status": "commit-failed", "branch": branch, "stderr": c_rc.stderr[:400]}

        new_head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        return {
            "status": "reverted",
            "branch": branch,
            "reverted_commits": reverted,
            "revert_commit": new_head[:12],
            "revert_commit_full": new_head,
            "message": f"Auto-rollback committed — main protected for task {task_id}",
        }
    except Exception as e:
        subprocess.run(["git", "revert", "--abort"], check=False)
        return {"status": "error", "error": str(e), "type": type(e).__name__}
    finally:
        os.chdir(original_cwd)


# ============================================================
# TEAM OPERATIONAL MEMORY / BLACKBOARD (memory,blackboard,communication)
# ============================================================
# Real-time shared "blackboard" for active agents.
# Agents post their current actions (e.g. "Я меняю структуру БД") so teammates
# can see live what the team is working on. Polling-friendly + simple.
# Scope primarily by team_id (or task_id for sub-teams). Short-term operational.
# Complements the long-term /knowledge store (post-completion facts).

def _ensure_blackboard_schema(conn: sqlite3.Connection) -> None:
    """Idempotent: create blackboard_activity table + indexes for live agent status."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS blackboard_activity (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            agent        TEXT NOT NULL,
            team_id      TEXT,
            task_id      TEXT,
            message      TEXT NOT NULL,
            created_at   TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_bba_created ON blackboard_activity (created_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_bba_team ON blackboard_activity (team_id, created_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_bba_agent ON blackboard_activity (agent, created_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_bba_task ON blackboard_activity (task_id, created_at DESC)")


def post_activity(
    agent: str,
    message: str,
    *,
    team_id: Optional[str] = None,
    task_id: Optional[str] = None,
) -> int:
    """
    Publish current action/status to the shared team blackboard (operational memory).
    Call this periodically or on major step changes from active agent loops.
    Other agents read via get_blackboard_feed() or get_current_actions() (or HTTP /blackboard/*).

    Example:
        post_activity("grok-worker-3", "Я меняю структуру БД: добавляю колонку blackboard_scope", team_id="team-42")
        post_activity("grok-worker-4", "Пишу тесты для A2A messaging", task_id="t-991")

    Returns row id. Tags: memory,blackboard,communication
    """
    if not agent or not message:
        raise ValueError("agent and message are required")
    _ensure_data_dir()
    now = datetime.utcnow().isoformat() + "Z"
    conn = _get_conn()
    try:
        with conn:
            _ensure_blackboard_schema(conn)
            cur = conn.execute(
                """
                INSERT INTO blackboard_activity (agent, team_id, task_id, message, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (agent, team_id, task_id, message, now),
            )
            return cur.lastrowid or 0
    finally:
        conn.close()


def get_blackboard_feed(
    *,
    team_id: Optional[str] = None,
    task_id: Optional[str] = None,
    agent: Optional[str] = None,
    limit: int = 30,
    since_minutes: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Recent activity log from the team blackboard. Primary way for agents to observe
    what others are doing "right now". Supports team/task scoping + recency filter.
    Returns newest first.
    """
    _ensure_data_dir()
    conn = _get_conn()
    try:
        _ensure_blackboard_schema(conn)
        params: list = []
        where: list[str] = []
        if team_id:
            where.append("team_id = ?")
            params.append(team_id)
        if task_id:
            where.append("task_id = ?")
            params.append(task_id)
        if agent:
            where.append("agent = ?")
            params.append(agent)
        if since_minutes is not None and since_minutes > 0:
            cutoff_dt = datetime.utcnow() - __import__("datetime").timedelta(minutes=since_minutes)
            cutoff = cutoff_dt.isoformat() + "Z"
            where.append("created_at >= ?")
            params.append(cutoff)

        sql = f"""
            SELECT id, agent, team_id, task_id, message, created_at
            FROM blackboard_activity
            {"WHERE " + " AND ".join(where) if where else ""}
            ORDER BY created_at DESC, id DESC
            LIMIT ?
        """
        params.append(min(limit, 200))
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_current_actions(
    *,
    team_id: Optional[str] = None,
    task_id: Optional[str] = None,
    window_minutes: int = 20,
) -> List[Dict[str, Any]]:
    """
    Live snapshot: the most recent message from each agent that posted within the window.
    This is the 'team dashboard' view — who is active and what they are doing right now.
    Perfect for manager agents or UI to render operational memory.
    """
    feed = get_blackboard_feed(
        team_id=team_id, task_id=task_id, limit=300, since_minutes=window_minutes
    )
    latest: dict[str, dict] = {}
    for entry in feed:  # feed is newest-first so first occurrence wins
        ag = entry.get("agent") or ""
        if ag and ag not in latest:
            latest[ag] = entry
    out = list(latest.values())
    out.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return out


def clear_blackboard_activity(team_id: Optional[str] = None) -> int:
    """Test helper: remove activity rows (optionally scoped to a team). Returns deleted count."""
    _ensure_data_dir()
    conn = _get_conn()
    try:
        with conn:
            _ensure_blackboard_schema(conn)
            if team_id:
                cur = conn.execute("DELETE FROM blackboard_activity WHERE team_id = ?", (team_id,))
            else:
                cur = conn.execute("DELETE FROM blackboard_activity")
            return cur.rowcount or 0
    finally:
        conn.close()


if __name__ == "__main__":
    # quick self-test when run directly
    print("Initializing checkpoints DB...")
    print("DB:", init_db())
    tid = "test-crash-recovery-001"
    clear_task(tid)
    save_checkpoint(tid, "dispatch", {"title": "Add dark mode", "repo": "https://github.com/agx/planlytasksko"})
    save_checkpoint(tid, "git_clone", {"branch": "grok-42", "clone_path": "/tmp/work/app", "repo": "https://github.com/agx/planlytasksko"})
    save_checkpoint(tid, "grok_start", {"session": "grok-abc123"})
    cp = get_last_checkpoint(tid)
    print("Last checkpoint:", cp["step"], "at", cp["created_at"])
    print("Recoverable tasks:", [t["task_id"] for t in list_recoverable_tasks()])
    print("Resume helper:", resume_or_start(tid))

    # --- RAG / FTS5 demo (rag,knowledge) ---
    # Index another task with different keywords for search test
    tid2 = "test-rag-fts5-002"
    clear_task(tid2)
    save_checkpoint(tid2, "dispatch", {
        "title": "Implement git auto-rollback on CI failure",
        "repo": "https://github.com/agx/planlytasksko",
        "description": "After CI fails on feature branch we must revert all commits safely so main is never broken",
        "tags": ["git", "ci", "safety", "rollback"]
    })
    save_checkpoint(tid2, "ci_failed", {"error": "tests failed"})
    save_checkpoint(tid2, "rollback", {"reverted": True})
    save_checkpoint(tid2, "done", {"completed": True})

    print("\n--- RAG FTS5 similar task search demo ---")
    hits = search_similar_tasks("git revert rollback ci failure", limit=5)
    print(f"Found {len(hits)} similar task(s) for 'git revert rollback ci failure':")
    for h in hits:
        print(f"  [{h['task_id']}] {h['title'][:60]} | outcome={h['outcome']} | score={h['score']:.2f}")
        print(f"      snippet: {h['snippet'][:110]}...")

    rag_block = get_rag_context("git auto rollback ci failure", limit=3, max_chars=900)
    print("\nRAG context block for LLM prompt:\n" + (rag_block or "(no hits)"))
    print("✅ FTS5 RAG self-test passed")

    # --- Shared Memory knowledge base demo (memory,knowledge) ---
    print("\n--- Shared Memory / Agent Knowledge demo ---")
    clear_knowledge()  # clean slate for test
    # Simulate agents storing learnings after task completion
    k1 = save_knowledge(
        key="lesson:rollback",
        value="On ci_failed always invoke perform_git_auto_rollback before marking review",
        agent="grok-worker",
        task_id="test-rag-fts5-002",
    )
    k2 = save_knowledge(
        key="fact:jetson",
        value="Use task_checkpoints for full crash recovery on thermal/power loss",
        agent="grok-worker",
        task_id=tid2,
        embedding_hash="hash-of-emb-001",
    )
    k3 = save_knowledge(
        key="pattern:ci",
        value="CI failures on Jetson often caused by OOM during sglang embed",
        agent="review-agent",
    )
    print(f"  Saved knowledge rows: {k1}, {k2}, {k3}")

    # Search
    mem_hits = search_knowledge("rollback ci_failed", limit=5)
    print(f"Found {len(mem_hits)} knowledge facts for 'rollback ci_failed':")
    for h in mem_hits:
        print(f"  [{h['id']}] {h['key']}: {h.get('value','')[:70]}... (agent={h.get('agent')}, score={h.get('score',0):.2f})")

    recent = search_knowledge("", limit=3, agent="grok-worker")
    print(f"Recent knowledge for grok-worker: {len(recent)} items")

    print("✅ Shared Memory knowledge self-test passed")

    # --- Git Auto-Rollback local simulation test (no network, real git reverts) ---
    # This directly verifies the core safety primitive requested: "git revert автоматически при падении CI"
    print("\n--- Git Auto-Rollback core logic test (local repo) ---")
    import tempfile, shutil, subprocess as sp
    test_dir = tempfile.mkdtemp(prefix="grok_rb_test_")
    try:
        repo = test_dir + "/repo"
        sp.check_call(["git", "init", "-q", repo], stdout=sp.DEVNULL, stderr=sp.DEVNULL)
        sp.check_call(["git", "-C", repo, "config", "user.email", "test@local"], stdout=sp.DEVNULL, stderr=sp.DEVNULL)
        sp.check_call(["git", "-C", repo, "config", "user.name", "Test"], stdout=sp.DEVNULL, stderr=sp.DEVNULL)

        # Force "main" as default branch (portable across git versions/configs)
        sp.check_call(["git", "-C", repo, "checkout", "-q", "-b", "main"], stdout=sp.DEVNULL, stderr=sp.DEVNULL)
        with open(repo + "/README.md", "w") as f: f.write("init\n")
        sp.check_call(["git", "-C", repo, "add", "README.md"], stdout=sp.DEVNULL, stderr=sp.DEVNULL)
        sp.check_call(["git", "-C", repo, "commit", "-q", "-m", "init main"], stdout=sp.DEVNULL, stderr=sp.DEVNULL)

        # Simulate Grok feature branch + "bad" change that would fail CI
        sp.check_call(["git", "-C", repo, "checkout", "-q", "-b", "grok-bad-42"], stdout=sp.DEVNULL, stderr=sp.DEVNULL)
        with open(repo + "/GROK_EDIT.md", "w") as f: f.write("bad change that breaks CI\n")
        sp.check_call(["git", "-C", repo, "add", "GROK_EDIT.md"], stdout=sp.DEVNULL, stderr=sp.DEVNULL)
        sp.check_call(["git", "-C", repo, "commit", "-q", "-m", "grok: simulate breaking change [task rb-test-42]"], stdout=sp.DEVNULL, stderr=sp.DEVNULL)

        # Now invoke the safety function (local main, no origin remote)
        res = perform_git_auto_rollback(repo, task_id="rb-test-42", ci_run_id="ci-local-1", main_ref="main", reason="simulated CI failure in test")
        print(f"  rollback status: {res.get('status')}")
        assert res.get("status") == "reverted", f"expected reverted, got {res}"
        assert "revert_commit" in res
        assert len(res.get("reverted_commits", [])) >= 1

        # Verify the revert commit exists and mentions auto-rollback + tags
        log = sp.check_output(["git", "-C", repo, "log", "-1", "--pretty=%s %b"], text=True)
        print(f"  revert commit msg head: {log.splitlines()[0][:80]}")
        assert "auto-rollback" in log.lower() or "revert" in log.lower()
        assert "git,ci,safety" in log or "Tags:" in log

        # Verify the bad file is gone after revert
        assert not os.path.exists(repo + "/GROK_EDIT.md"), "bad change should be reverted"

        print("✅ perform_git_auto_rollback local simulation: PASS (reverted 1 commit cleanly)")
    except Exception as e:
        print(f"❌ rollback test failed: {e}")
        import traceback; traceback.print_exc()
        raise
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)

    print("\n✅ task_checkpoints self-test passed (including Git Auto-Rollback + Shared Memory knowledge)")
