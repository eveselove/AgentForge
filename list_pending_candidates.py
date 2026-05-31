#!/usr/bin/env python3
"""
DEPRECATED — Full Rust Migration (2026-05-31)
This Python CLI is legacy. Use `agentforge-runner candidate ...` instead.
See RUST_ONLY_MIGRATION_PLAN.md
"""

"""
list_pending_candidates.py — Tiny CLI entrypoint for the central pending flywheel candidates store (Legacy).

Run as:
    python -m agentforge.list_pending_candidates
    python -m agentforge.list_pending_candidates list
    python -m agentforge.list_pending_candidates promote <id> [--copy-to-skills] [--dry-run]
    python -m agentforge.list_pending_candidates promote-and-ab <id> [--auto-ab] [--dry-run]

This is the production surface for "what improvements has the Rust flywheel proposed lately?"
All candidates come from canonical rust_flywheel_step runs (with bridge) via auto-ingest.
Core flow: list → promote-and-ab (safe copy + full A/B config + LearningEvaluator snippet) → review/run A/B → full prod promote if winner.

!!! AGGRESSIVE FINAL DEPRECATION SWEEP (RUST_FULL_MIGRATION_PLAN.md + PHASE4_REMOVAL_PLAN.md) !!!
!!! THIS PYTHON CLI FOR FLYWHEEL CANDIDATES (list/promote) DEPRECATED — PHASE 4 DELETE !!!
MIGRATE TO DIRECT: agentforge-runner candidate list|prioritize|promote|ingest ...

Guard with Phase 4 hardened central:
  from agentforge.learning.utils import is_pure_rust_flywheel

Loud warnings. Non-breaking shim for !pure. Full removal Phase 4.

See learning/utils.py (stronger guards + full file list)
See PHASE4_REMOVAL_PLAN.md
"""
from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

# Make -m agentforge.list_pending_candidates work when invoked from anywhere
sys.path.insert(0, str(Path(__file__).parent))

from learning.pending_candidates import (
    print_pending_summary,
    list_pending_candidates,
    promote_candidate,
    get_pending_dir,
)

# PHASE 3/4: use EVEN STRONGER central hardened guards only
try:
    from agentforge.learning.utils import is_pure_rust_flywheel, is_rust_flywheel_disabled
except Exception:
    from learning.utils import is_pure_rust_flywheel, is_rust_flywheel_disabled  # fallback


def main(argv: list[str] | None = None) -> int:
    # TODO(Phase 1 Deprecation Expander): per RUST_FULL_MIGRATION_PLAN.md
    # Expanded is_pure_rust_flywheel() usage + deprecation for this Python CLI entrypoint.
    if not is_pure_rust_flywheel():
        warnings.warn(
            "list_pending_candidates.py (Python orchestration CLI) is deprecated per "
            "RUST_FULL_MIGRATION_PLAN.md PHASE 3. Prefer `agentforge-runner candidate list|promote`. "
            "Python paths remain for safe transition.",
            DeprecationWarning,
            stacklevel=2,
        )
        print(
            "[DEPRECATION PHASE 3] list_pending_candidates (Python) — per RUST_FULL_MIGRATION_PLAN.md. "
            "Migrate to agentforge-runner candidate ... See bin/make_pure_rust_flywheel_default.sh",
            file=sys.stderr,
        )

    parser = argparse.ArgumentParser(
        prog="python -m agentforge.list_pending_candidates",
        description="List / inspect / promote Rust flywheel candidates from central pending_candidates/ store.",
    )
    sub = parser.add_subparsers(dest="cmd", required=False)

    p_list = sub.add_parser("list", help="Show summary of all pending candidates (default)")
    p_list.add_argument("--limit", type=int, default=20, help="Max candidates to display")
    p_list.add_argument("--sort", choices=["value", "recency"], default="value",
                        help="Sort order: 'value' (default: by rich_avg_learning_value + lift potential for autonomy) or 'recency'")
    p_list.add_argument("--high-value-only", action="store_true", help="Use prioritizer: only high-LV candidates (top by learning value)")

    p_prom = sub.add_parser("promote", help="Promote candidate (mark reviewed + optional safe copy to skills/). Now with A/B prep by default.")
    p_prom.add_argument("candidate_id", help="candidate_id (the timestamp_skill_hash dir name) or full path")
    p_prom.add_argument("--copy-to-skills", action="store_true",
                        help="Also (safe) copy the candidate_skill.yaml into skills/ as <name>.promoted.<ts>.yaml")
    p_prom.add_argument("--target-name", type=str, default=None,
                        help="Explicit destination name when copying (advanced; skips timestamp)")
    p_prom.add_argument("--dry-run", action="store_true", help="Show what would happen, write nothing")
    p_prom.add_argument("--no-ab", action="store_true", help="Skip A/B config + snippet generation (default: prepare full A/B artifacts)")
    p_prom.add_argument("--auto-ab", action="store_true", help="After A/B prep, also invoke LearningEvaluator in safe simulate mode")

    p_pab = sub.add_parser("promote-and-ab", help="Promote (safe copy) + generate real A/B test config + exact LearningEvaluator command snippet. Recommended entrypoint for the track.")
    p_pab.add_argument("candidate_id", help="candidate_id (the timestamp_skill_hash dir name) or full path")
    p_pab.add_argument("--auto-ab", action="store_true", help="Additionally call LearningEvaluator (simulate by default; combine with --real-ab for live runs)")
    p_pab.add_argument("--real-ab", action="store_true", help="With --auto-ab: run with wait_for_real=True (real execution, slower)")
    p_pab.add_argument("--copy-to-skills", action="store_true", default=True,
                        help="Safe-copy to skills/ (default: True for promote-and-ab)")
    p_pab.add_argument("--no-copy", action="store_true", help="Override: do not copy to skills/")
    p_pab.add_argument("--target-name", type=str, default=None, help="Explicit name for the promoted yaml")
    p_pab.add_argument("--dry-run", action="store_true", help="Preview only")
    p_pab.add_argument("--benchmarks", type=str, default=None, help="Comma-separated benchmark ids (override defaults)")

    p_info = sub.add_parser("info", help="Print location and usage")
    p_info.add_argument("--pending-dir", action="store_true", help="Just print the pending dir path")

    args = parser.parse_args(argv)

    if args.cmd == "info" or (args.cmd is None and getattr(args, "pending_dir", False)):
        print("Central pending_candidates location:", get_pending_dir())
        print("Env override: AGENTFORGE_PENDING_CANDIDATES_DIR=...")
        print("Candidates are auto-populated by every run of:")
        print("  AGENTFORGE_RUST_FLYWHEEL=1 python -m agentforge.rust_flywheel_step --real-data --use-rust --no-env-guard")
        return 0

    if args.cmd in (None, "list"):
        sort_by = getattr(args, "sort", "value")
        lim = getattr(args, "limit", 20)
        if getattr(args, "high_value_only", False):
            # Use the new prioritizer directly for focused high-value view (autonomy boost)
            from learning.pending_candidates import list_high_value_candidates
            hv = list_high_value_candidates(limit=lim)
            print(f"\n=== HIGH-VALUE FLYWHEEL CANDIDATES (prioritized by learning_value + lift; showing {len(hv)}) ===")
            for c in hv:
                cid = c.get("candidate_id", "?")
                lv = c.get("rich_avg_learning_value") or c.get("avg_learning_value") or "?"
                print(f"  {cid}  avg_lv={lv}  skill={c.get('skill')}")
            print("Use normal list for full details, or promote-and-ab on top ones.")
            return 0
        print_pending_summary(limit=lim, sort_by=sort_by)
        return 0

    if args.cmd == "promote":
        prepare_ab = not getattr(args, "no_ab", False)
        auto_ab = getattr(args, "auto_ab", False)
        res = promote_candidate(
            args.candidate_id,
            copy_to_skills=args.copy_to_skills,
            mark_reviewed=True,
            dry_run=args.dry_run,
            target_name=args.target_name,
            prepare_ab=prepare_ab,
            auto_ab=auto_ab,
        )
        if res:
            print(f"[CLI] promote finished. Result: {res}")
            # If A/B prepared, surface the suggested command file
            cand_dir = get_pending_dir() / str(args.candidate_id)
            sug = cand_dir / "suggested_ab_command.txt"
            if sug.exists():
                print("\n--- Suggested A/B command (from generated artifacts) ---")
                print(sug.read_text(encoding="utf-8")[:2000])
        return 0 if res else 1

    if args.cmd == "promote-and-ab":
        do_copy = getattr(args, "copy_to_skills", True) and not getattr(args, "no_copy", False)
        dry = args.dry_run
        bm_list = None
        if getattr(args, "benchmarks", None):
            bm_list = [b.strip() for b in args.benchmarks.split(",") if b.strip()]
        auto_ab = getattr(args, "auto_ab", False)
        # Note: --real-ab is advisory for user; we keep auto safe here, but pass intent via meta later if needed
        if auto_ab and getattr(args, "real_ab", False):
            print("[CLI] NOTE: --real-ab requested with --auto-ab. For safety the built-in auto call still uses simulate=True.")
            print("        Edit the generated run_ab_after_promote.py and run it directly for real runs.")

        res = promote_candidate(
            args.candidate_id,
            copy_to_skills=do_copy,
            mark_reviewed=True,
            dry_run=dry,
            target_name=args.target_name,
            prepare_ab=True,   # always for this command
            auto_ab=auto_ab,
            benchmarks=bm_list,
        )
        if res:
            print(f"[CLI] promote-and-ab finished. Result: {res}")
            # Always surface the exact generated A/B artifacts + commands
            cand_dir = get_pending_dir() / str(args.candidate_id)
            for fname in ("suggested_ab_command.txt", "run_ab_after_promote.py", "ab_test_config.json"):
                p = cand_dir / fname
                if p.exists():
                    print(f"\n=== {fname} ===")
                    content = p.read_text(encoding="utf-8")
                    print(content if len(content) < 1800 else content[:1800] + "\n... (truncated)")
            print("\n[CLI] To execute the A/B (recommended after review):")
            print(f"   python {cand_dir / 'run_ab_after_promote.py'}")
        return 0 if res else 1

    # default when no subcommand
    print_pending_summary(sort_by="value")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
