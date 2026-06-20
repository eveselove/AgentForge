#!/usr/bin/env python3
import os
import sys
import sqlite3
import json
import shutil
import lancedb
import pyarrow as pa
import time

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
        pa.field("requires_agent_review", pa.bool_(), nullable=False),
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


def _get(row, key, default=None):
    """Safe row value getter to avoid KeyError on missing columns (defensive vs schema drift)."""
    try:
        val = row[key]
        return val if val is not None else default
    except (KeyError, IndexError, TypeError):
        return default


def _build_record(row):
    """Build Lance record from sqlite Row. Isolated for testability and clarity."""
    # Construct tags_json (robust to json-str, comma-str, scalar, missing)
    tags_raw = _get(row, "tags", "") or ""
    tags_list = []
    if tags_raw:
        try:
            parsed = json.loads(tags_raw)
            if isinstance(parsed, list):
                tags_list = parsed
            elif parsed is not None:
                tags_list = [parsed]
        except Exception:
            if "," in tags_raw:
                tags_list = [t.strip() for t in tags_raw.split(",") if t.strip()]
            elif tags_raw.strip():
                tags_list = [tags_raw.strip()]
    tags_json = json.dumps(tags_list)

    # Construct metadata_json (only known extra cols; safe)
    metadata = {}
    for key in [
        "git_branch",
        "duration_seconds",
        "skill",
        "retry_count",
        "tokens_used",
        "cost_usd",
    ]:
        val = _get(row, key)
        if val is not None:
            metadata[key] = val
    metadata_json = json.dumps(metadata)

    # Result mapping (preserve json if possible, else stringified)
    result_raw = _get(row, "result")
    result_json = ""
    if result_raw is not None:
        try:
            parsed = json.loads(result_raw)
            result_json = json.dumps(parsed)
        except Exception:
            result_json = json.dumps(result_raw)

    return {
        "id": _get(row, "id", "") or "",
        "title": _get(row, "title", "") or "",
        "description": _get(row, "description", "") or "",
        "priority": _get(row, "priority", "medium") or "medium",
        "complexity": _get(row, "complexity", "medium") or "medium",
        "preferred_agent": _get(row, "preferred_agent", "auto") or "auto",
        "assigned_to": _get(row, "assigned_agent", "") or "",
        "status": map_status(_get(row, "status")),
        "tags_json": tags_json,
        "requires_agent_review": False,
        "created_at": _get(row, "created_at", "") or "",
        "updated_at": _get(row, "updated_at", "") or "",
        "started_at": _get(row, "started_at", "") or "",
        "completed_at": _get(row, "completed_at", "") or "",
        "metadata_json": metadata_json,
        "result_json": result_json,
    }


def main():
    if not os.path.exists(DB_PATH):
        print(f"Error: SQLite database {DB_PATH} not found.")
        sys.exit(1)

    print(f"Reading tasks from SQLite: {DB_PATH}...")
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH, timeout=30.0)
        conn.row_factory = sqlite3.Row

        # Stream via cursor + fetchmany to avoid materializing all rows+records in RAM at once.
        # This eliminates the O(N) memory spike bottleneck for large task histories with big JSON blobs.
        # Use dedicated cursors for count (fast) and iteration to avoid cursor state races.
        total_rows = 0
        try:
            count_cur = conn.cursor()
            total_rows = count_cur.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        except Exception:
            total_rows = 0

        print(f"Found {total_rows} tasks in SQLite. Streaming to LanceDB (batch mode)...")

        # Use isolated temp dir for the *new* Lance data. All writes happen here.
        # On success we atomically swap; on any error, live LANCE_DIR is untouched (no partial/corrupt state).
        ts = int(time.time() * 1000)
        tmp_dir = f"{LANCE_DIR}.tmp.{os.getpid()}.{ts}"
        if os.path.exists(tmp_dir):
            shutil.rmtree(tmp_dir, ignore_errors=True)
        os.makedirs(tmp_dir, exist_ok=True)

        db_tmp = lancedb.connect(tmp_dir)
        table = db_tmp.create_table(TABLE_NAME, schema=SCHEMA)

        BATCH_SIZE = 64  # small batch: low mem, good progress, reduces arrow overhead per call
        batch = []
        processed = 0
        last_report = 0

        # Streaming cursor for data rows (separate from count cursor to prevent any state interference)
        data_cur = conn.cursor()
        data_cur.execute("SELECT * FROM tasks")
        while True:
            rows = data_cur.fetchmany(BATCH_SIZE)
            if not rows:
                break
            for row in rows:
                rec = _build_record(row)
                batch.append(rec)
                processed += 1
            if batch:
                table.add(batch)
                batch = []
            if processed - last_report >= 100 or (total_rows and processed == total_rows):
                print(f"  ... migrated {processed}/{total_rows or processed}")
                last_report = processed

        if batch:
            table.add(batch)

        # IMPORTANT: do not touch live dir until *all* data safely written to tmp and no exception.
        bak_dir = None
        if os.path.exists(LANCE_DIR):
            bak_dir = LANCE_DIR + ".bak." + time.strftime("%Y%m%d-%H%M%S")
            print(f"Backing up existing LanceDB dir {LANCE_DIR} to {bak_dir}...")
            # Timestamped backup: never clobber previous .bak (retains migration history).
            # copytree is safe because live data is still present and consistent.
            if os.path.exists(bak_dir):
                shutil.rmtree(bak_dir, ignore_errors=True)
            shutil.copytree(LANCE_DIR, bak_dir)
            shutil.rmtree(LANCE_DIR)

        print(f"Activating migrated data ({processed} rows) ...")
        os.rename(tmp_dir, LANCE_DIR)  # fast dir rename on same FS (near-atomic for consumers)

        # Verify on the now-live location
        db = lancedb.connect(LANCE_DIR)
        tbl = db.open_table(TABLE_NAME)
        final_count = tbl.count_rows()
        print(f"Successfully migrated {final_count} rows to LanceDB tasks table!")

    except Exception as e:
        print(f"Migration error: {e}")
        # Cleanup any partial tmp. If we already deleted live (for rename) but failed, restore from bak if present.
        if "tmp_dir" in locals() and os.path.exists(tmp_dir):
            shutil.rmtree(tmp_dir, ignore_errors=True)
        if (not os.path.exists(LANCE_DIR) and "bak_dir" in locals() and bak_dir and os.path.exists(bak_dir)):
            print(f"Attempting to restore previous data from {bak_dir} ...")
            try:
                os.rename(bak_dir, LANCE_DIR)
                print("Restore successful.")
            except Exception as re:
                print(f"Auto-restore failed ({re}). Manual restore from backup required: {bak_dir}")
        sys.exit(1)
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()
