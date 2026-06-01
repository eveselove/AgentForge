"""
LanceDB-backed Task Store (Python side).

This is the bridge implementation while the Rust LanceTaskStore is being matured
and while certain environments have trouble resolving the full lancedb Rust dependency tree.

It uses the same table schema as the Rust version (as much as possible) so that
the two sides can eventually share the same physical tables.

See: docs/LANCE_TASK_STORE_MIGRATION_PLAN.md
"""

import os
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

import lancedb
import pyarrow as pa

DB_PATH = os.path.expanduser("~/agentforge/data/lance_tasks")
TABLE_NAME = "tasks"

# Match the Rust schema as closely as possible
SCHEMA = pa.schema([
    pa.field("id", pa.string()),
    pa.field("title", pa.string()),
    pa.field("description", pa.string()),
    pa.field("priority", pa.string()),
    pa.field("complexity", pa.string()),
    pa.field("preferred_agent", pa.string()),
    pa.field("assigned_to", pa.string()),
    pa.field("status", pa.string()),
    pa.field("tags", pa.string()),           # comma-separated for simplicity
    pa.field("created_at", pa.string()),
    pa.field("updated_at", pa.string()),
    pa.field("started_at", pa.string()),
    pa.field("completed_at", pa.string()),
    pa.field("metadata", pa.string()),       # JSON string
    pa.field("result", pa.string()),         # JSON string
    # Future: pa.field("embedding", pa.list_(pa.float32(), list_size=...))
])

def _get_db():
    os.makedirs(DB_PATH, exist_ok=True)
    return lancedb.connect(DB_PATH)

def _get_table():
    db = _get_db()
    if TABLE_NAME in db.table_names():
        return db.open_table(TABLE_NAME)
    return db.create_table(TABLE_NAME, schema=SCHEMA)

def create_task(task: Dict[str, Any]) -> Dict[str, Any]:
    """Create a task in LanceDB. Expects a dict with the Task fields."""
    table = _get_table()

    now = datetime.now(timezone.utc).isoformat()
    task = dict(task)  # copy
    task.setdefault("created_at", now)
    task.setdefault("updated_at", now)
    task.setdefault("tags", "")
    task.setdefault("metadata", "{}")
    task.setdefault("result", "")

    # Ensure all required fields exist
    for field in SCHEMA.names:
        task.setdefault(field, "")

    table.add([task])
    return task

def get_task(task_id: str) -> Optional[Dict[str, Any]]:
    table = _get_table()
    results = table.search().where(f"id = '{task_id}'").limit(1).to_pandas()
    if len(results) == 0:
        return None
    return results.iloc[0].to_dict()

def list_pending() -> List[Dict[str, Any]]:
    table = _get_table()
    results = table.search().where("status = 'Pending'").to_pandas()
    return results.to_dict("records")

# More methods (update, claim, etc.) can be added following the same pattern.
