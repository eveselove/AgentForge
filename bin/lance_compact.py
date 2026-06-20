#!/usr/bin/env python3
"""
LanceDB auto-compaction script.
Запускается cron'ом каждые 5 минут.
Компактирует фрагменты только если их > 20 (бесполезно запускать при 1-2).

Cron: */5 * * * * /home/eveselove/agentforge/bin/lance_compact.py >> /home/eveselove/agentforge/logs/lance_compact.log 2>&1
"""
import lancedb
import sys
import os
from datetime import datetime

LANCE_PATH = os.environ.get(
    "LANCE_PATH",
    "/home/eveselove/agentforge/data/lance_tasks"
)
MIN_FRAGMENTS_TO_COMPACT = 20

def main():
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        db = lancedb.connect(LANCE_PATH)
        tbl = db.open_table("tasks")

        # Считаем фрагменты (через stats)
        try:
            stats = tbl.stats()
            n_fragments = getattr(stats, 'num_fragments', None) or getattr(stats, 'fragments', None)
            if n_fragments is None:
                # fallback: считаем .lance файлы
                import pathlib
                n_fragments = len(list(pathlib.Path(LANCE_PATH).rglob("*.lance")))
        except Exception:
            import pathlib
            n_fragments = len(list(pathlib.Path(LANCE_PATH).rglob("*.lance")))

        if n_fragments < MIN_FRAGMENTS_TO_COMPACT:
            print(f"[{ts}] OK: {n_fragments} fragments, no compaction needed")
            return

        print(f"[{ts}] Compacting {n_fragments} fragments...", flush=True)
        result = tbl.compact_files()
        tbl.cleanup_old_versions()
        print(f"[{ts}] Done: {result}")

    except Exception as e:
        print(f"[{ts}] ERROR: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
