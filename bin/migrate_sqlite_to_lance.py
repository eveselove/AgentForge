#!/usr/bin/env python3
import os
import sys
import sqlite3
import json
import shutil
import lancedb
import pyarrow as pa

DB_PATH = os.path.expanduser("~/agentforge/tasks.db")
LANCE_DIR = os.path.expanduser("~/agentforge/data/lance_tasks")
TABLE_NAME = "tasks"

SCHEMA = pa.schema(
    [
        pa.field("id", pa.string(), nullable=False),
        pa.field("title", pa.string(), nullable=False),
        pa.field("description", pa.string(), nullable=True),
        pa.field("priority", pa.string(), nullable=False),
        pa.field("complexity", pa.string(), nullable=False),
        pa.field("preferred_agent", pa.string(), nullable=True),
        pa.field("assigned_to", pa.string(), nullable=True),
        pa.field("status", pa.string(), nullable=False),
        pa.field("tags_json", pa.string(), nullable=True),
        pa.field("created_at", pa.string(), nullable=False),
        pa.field("updated_at", pa.string(), nullable=False),
        pa.field("started_at", pa.string(), nullable=True),
        pa.field("completed_at", pa.string(), nullable=True),
        pa.field("metadata_json", pa.string(), nullable=True),
        pa.field("result_json", pa.string(), nullable=True),
    ]
)


def map_status(s):
    s = str(s or "pending").lower()
    if s in ("pending", "dispatch"):
        return "Pending"
    if s == "dispatched":
        return "Dispatched"
    if s in (
        "in_progress",
        "grok_start",
        "grok_done",
        "ci_start",
        "ci_done",
        "ci_failed",
        "rollback",
    ):
        return "InProgress"
    if s == "review":
        return "Review"
    if s == "done":
        return "Done"
    if s == "failed":
        return "Failed"
    if s == "cancelled":
        return "Cancelled"
    return "Pending"


def main():
    if not os.path.exists(DB_PATH):
        print(f"Error: SQLite database {DB_PATH} not found.")
        sys.exit(1)

    print(f"Reading tasks from SQLite: {DB_PATH}...")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        rows = cursor.execute("SELECT * FROM tasks").fetchall()
    except sqlite3.OperationalError as e:
        print(f"Error reading tasks: {e}")
        sys.exit(1)

    print(f"Found {len(rows)} tasks in SQLite.")

    # Prepare records for LanceDB
    records = []
    for row in rows:
        # Construct tags_json
        tags_raw = row["tags"]
        tags_list = []
        if tags_raw:
            try:
                tags_list = json.loads(tags_raw)
                if not isinstance(tags_list, list):
                    tags_list = [tags_list]
            except Exception:
                if "," in tags_raw:
                    tags_list = [t.strip() for t in tags_raw.split(",")]
                elif tags_raw.strip():
                    tags_list = [tags_raw.strip()]
        tags_json = json.dumps(tags_list)

        # Construct metadata_json
        metadata = {}
        for key in [
            "git_branch",
            "duration_seconds",
            "skill",
            "retry_count",
            "tokens_used",
            "cost_usd",
        ]:
            if key in row.keys() and row[key] is not None:
                metadata[key] = row[key]
        metadata_json = json.dumps(metadata)

        # Result mapping
        result_raw = row["result"]
        result_json = ""
        if result_raw is not None:
            # Check if it is valid json already, else dump as json string
            try:
                parsed = json.loads(result_raw)
                result_json = json.dumps(parsed)
            except Exception:
                result_json = json.dumps(result_raw)

        rec = {
            "id": row["id"] or "",
            "title": row["title"] or "",
            "description": row["description"] or "",
            "priority": row["priority"] or "medium",
            "complexity": row["complexity"] or "medium",
            "preferred_agent": row["preferred_agent"] or "auto",
            "assigned_to": row["assigned_agent"] or "",
            "status": map_status(row["status"]),
            "tags_json": tags_json,
            "created_at": row["created_at"] or "",
            "updated_at": row["updated_at"] or "",
            "started_at": row["started_at"] or "",
            "completed_at": row["completed_at"] or "",
            "metadata_json": metadata_json,
            "result_json": result_json,
        }
        records.append(rec)

    # Backup existing LanceDB table if exists
    if os.path.exists(LANCE_DIR):
        bak_dir = LANCE_DIR + ".bak"
        print(f"Backing up existing LanceDB dir {LANCE_DIR} to {bak_dir}...")
        if os.path.exists(bak_dir):
            shutil.rmtree(bak_dir)
        shutil.copytree(LANCE_DIR, bak_dir)
        shutil.rmtree(LANCE_DIR)

    os.makedirs(LANCE_DIR, exist_ok=True)
    db = lancedb.connect(LANCE_DIR)

    print(f"Writing {len(records)} tasks to LanceDB in {LANCE_DIR}...")

    # Create the table with the precise schema
    table = db.create_table(TABLE_NAME, schema=SCHEMA)
    table.add(records)

    print("Verification:")
    tbl = db.open_table(TABLE_NAME)
    print(f"Successfully migrated {tbl.count_rows()} rows to LanceDB tasks table!")


if __name__ == "__main__":
    main()
