#!/usr/bin/env python3
"""Dedup task rows in LanceDB, keeping the latest (max updated_at) row per id.

Schema-preserving: overwrites the table using its own pyarrow schema, so the
Rust gateway's merge_insert keeps working unchanged.

Usage:
  dedup_lance_tasks.py            # dry-run: report duplicates, change nothing
  dedup_lance_tasks.py --apply    # rewrite table with one row per id

IMPORTANT: stop the gateway before --apply so this is the sole writer.
"""

import sys
import os
import lancedb
import pyarrow as pa

DATA = os.environ.get("AGENTFORGE_DATA", "/home/eveselove/agentforge/data")
DB_PATH = f"{DATA}/lance_tasks"
TABLE = "tasks"

apply = "--apply" in sys.argv

db = lancedb.connect(DB_PATH)
tbl = db.open_table(TABLE)
schema = tbl.schema
at = tbl.to_arrow()
rows = at.to_pylist()
print(f"rows total: {len(rows)}  | schema fields: {len(schema)}")

# group by id, keep row with max updated_at (rfc3339 UTC strings sort lexically)
by_id = {}
for r in rows:
    rid = r.get("id")
    cur = by_id.get(rid)
    if cur is None or (r.get("updated_at") or "") >= (cur.get("updated_at") or ""):
        by_id[rid] = r

unique = len(by_id)
dups = len(rows) - unique
dup_groups = {}
for r in rows:
    dup_groups.setdefault(r.get("id"), []).append(r)
dup_groups = {k: v for k, v in dup_groups.items() if len(v) > 1}

print(
    f"unique ids: {unique}  | duplicate rows to drop: {dups}  | dup groups: {len(dup_groups)}"
)
for rid, grp in sorted(dup_groups.items()):
    statuses = [g.get("status") for g in grp]
    winner = by_id[rid]
    print(
        f"  {rid}: {len(grp)} copies statuses={statuses} -> keep status={winner.get('status')} updated_at={winner.get('updated_at')}"
    )

if not apply:
    print(
        "\nDRY-RUN — nothing changed. Re-run with --apply (gateway stopped) to rewrite."
    )
    sys.exit(0)

winners = list(by_id.values())
# cast back to the table's exact schema to avoid any drift
new_tbl = pa.Table.from_pylist(winners, schema=schema)
db.create_table(TABLE, data=new_tbl, schema=schema, mode="overwrite")
print(f"\nAPPLIED: table rewritten with {len(winners)} rows (was {len(rows)}).")
