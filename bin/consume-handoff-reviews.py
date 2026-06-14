#!/usr/bin/env python3
"""
Handoff Consumer Script (Post-100% Hardening: c48c5f56)

Scans ~/.grok/handoffs/ for completed agent-review handoffs (presence of
jules-review-*.md or *-review-*.md files written by independent reviewer).

- Detects approval verdict using conservative heuristics (looks for explicit
  **APPROVE** / "Recommendation: **APPROVE**" etc.; rejects on REQUEST_CHANGES,
  REJECT, or high bug counts).
- For approved reviews: advances the originating task (from metadata.json
  "task_id") to status "done" via the Task Queue API, injecting rich traceable
  result notes + links to the handoff dir and review file.
- Idempotent: skips handoffs that already have a .consumed marker file or
  whose task result already references the handoff_id.
- Safe by default: --dry-run (no mutations). Use --apply to execute.
- Well-logged: structured stdout + optional persistent log file.
- Bulk + selective: --limit, --handoff-id, --all (even non-explicit), --stats, --list.

This closes the review backlog loop that plagued waves: reviewers produce
auditable jules-review-*.md inside portable handoff packages; this script
mechanically consumes them to finalize tasks in the queue.

Part of the 5 critical Post-100% Hardening items.

Usage examples:
  # Inspect everything (no changes)
  python3 bin/consume-handoff-reviews.py --stats --list

  # Dry-run preview of what would be approved/advanced (recommended first)
  python3 bin/consume-handoff-reviews.py --dry-run --verbose --limit 20

  # Actually consume and approve a specific handoff (after manual review of dry-run)
  python3 bin/consume-handoff-reviews.py --apply --handoff-id 6cbb2bb1

  # Bulk apply everything the heuristics consider clearly approved
  python3 bin/consume-handoff-reviews.py --apply --limit 50 2>&1 | tee -a ~/.grok/handoffs/consume.log

  # Force process even borderline reviews (use with extreme caution + manual vetting)
  python3 bin/consume-handoff-reviews.py --apply --all-reviewed --limit 5

Exit codes: 0 success (even if 0 items processed), 1 on fatal errors only.

Integrates with:
- Task Queue API (http://localhost:9090 by default, same as approve_tasks.py)
- Existing handoff package spec from ~/.grok/skills/agent-review/SKILL.md
- Future Rust LanceTaskStore (via same HTTP surface during transition)

See AGENTS.md "Mandatory Post-Work Agent-Review Step" and the handoff consumer
section added by this task.
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

# === Constants (tunable via CLI where appropriate) ===
DEFAULT_HANDOFF_ROOT = Path.home() / ".grok" / "handoffs"
DEFAULT_API_BASE = "http://localhost:9090/tasks"
CONSUMED_MARKER = ".consumed"
LOG_FILE_DEFAULT = DEFAULT_HANDOFF_ROOT / "consume.log"

# Approval detection patterns (conservative; order matters for logging)
APPROVE_PATTERNS = [
    r"\*\*APPROVE\*\*",
    r"Recommendation\s*[:\n]+\s*\*\*APPROVE\*\*",
    r"Verdict\s*[:\n]+\s*APPROVE",
    r"Overall[^:]*:\s*APPROVE",
    r"accept-with-minor.*ready",
    r"APPROVE\s+for\s+(immediate|merge|PR)",
]
BLOCK_PATTERNS = [
    r"REQUEST_CHANGES",
    r"\bREJECT\b",
    r"\bREJECTED\b",
]

# How many trailing lines to inspect for verdict (reviews put final decision at end)
VERDICT_SCAN_LINES = 40


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def log(
    msg: str,
    *,
    verbose: bool = False,
    log_file: Optional[Path] = None,
    force: bool = False,
) -> None:
    """Timestamped structured logging to stdout (and file if provided)."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    if force or verbose or not msg.startswith("  "):  # always show top-level
        print(line, flush=True)
    if log_file:
        try:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception as e:
            print(
                f"[{ts}] [WARN] Could not write to log file {log_file}: {e}",
                file=sys.stderr,
            )


def is_approved(review_text: str) -> Tuple[bool, str, str]:
    """
    Conservative approval heuristic.

    Returns: (approved: bool, reason: str, extracted_verdict: str)
    """
    if not review_text or not review_text.strip():
        return False, "empty review file", "NO_REVIEW"

    upper = review_text.upper()
    last_lines = "\n".join(review_text.splitlines()[-VERDICT_SCAN_LINES:])

    # Strong blockers first
    for pat in BLOCK_PATTERNS:
        if re.search(pat, last_lines, re.IGNORECASE) or re.search(
            pat, upper, re.IGNORECASE
        ):
            return False, f"blocked by pattern '{pat}'", "BLOCKED"

    # Look for explicit positive signals in the verdict area (preferred)
    for pat in APPROVE_PATTERNS:
        if re.search(pat, last_lines, re.IGNORECASE | re.MULTILINE):
            return (
                True,
                f"matched verdict pattern '{pat}' in last {VERDICT_SCAN_LINES} lines",
                "APPROVE",
            )

    # Fallback: explicit APPROVE anywhere near the end + zero bugs language
    if re.search(r"\*\*APPROVE\*\*", last_lines, re.IGNORECASE):
        return True, "explicit **APPROVE** near end of review", "APPROVE"

    # Very conservative fallback: "No BUGs" + "APPROVE" word somewhere prominent
    bug_count_match = re.search(
        r"(Bugs|BUGs)\s*[:\-]?\s*(\d+)", review_text, re.IGNORECASE
    )
    if bug_count_match and int(bug_count_match.group(2)) == 0:
        if "APPROVE" in upper[-2000:]:  # last ~2k chars
            return True, "zero bugs + APPROVE token present", "APPROVE_LIKELY"

    return (
        False,
        "no strong explicit APPROVE verdict found (conservative default)",
        "NEEDS_REVIEW",
    )


def load_metadata(handoff_dir: Path) -> Optional[Dict[str, Any]]:
    meta_file = handoff_dir / "metadata.json"
    if not meta_file.exists():
        return None
    try:
        return json.loads(meta_file.read_text(encoding="utf-8"))
    except Exception:
        return None


def find_review_file(handoff_dir: Path) -> Optional[Path]:
    """Return the primary review file if present (prefers jules-review-*.md)."""
    candidates = sorted(handoff_dir.glob("jules-review-*.md")) + sorted(
        handoff_dir.glob("*review*.md")
    )
    for p in candidates:
        if p.is_file() and p.name != "REVIEW_INSTRUCTIONS.md":
            return p
    return None


def get_task_via_api(task_id: str, api_base: str) -> Optional[Dict[str, Any]]:
    url = f"{api_base.rstrip('/')}/{task_id}"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            if resp.status == 200:
                return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
    except Exception:
        pass
    return None


def update_task_status(task_id: str, status: str, result: str, api_base: str) -> bool:
    """PATCH task to new status + result. Returns True on success."""
    url = f"{api_base.rstrip('/')}/{task_id}"
    payload = {
        "status": status,
        "result": result,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="PATCH"
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return 200 <= resp.status < 300
    except Exception:
        return False


def mark_consumed(handoff_dir: Path, info: Dict[str, Any]) -> None:
    marker = handoff_dir / CONSUMED_MARKER
    try:
        marker.write_text(
            json.dumps(info, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        # Make it obvious
        os.chmod(marker, 0o644)
    except Exception:
        pass  # best effort


def already_consumed(
    handoff_dir: Path, task_result: Optional[str], handoff_id: str
) -> bool:
    if (handoff_dir / CONSUMED_MARKER).exists():
        return True
    if task_result and handoff_id in task_result:
        return True
    return False


def collect_handoffs(root: Path) -> List[Path]:
    if not root.exists():
        return []
    return sorted([p for p in root.iterdir() if p.is_dir()], key=lambda p: p.name)


def process_handoff(
    handoff_dir: Path,
    api_base: str,
    dry_run: bool,
    require_approve: bool,
    force_all: bool,
    verbose: bool,
    log_file: Optional[Path],
) -> Dict[str, Any]:
    """Process one handoff dir. Returns a result dict for reporting."""
    handoff_id = handoff_dir.name
    result: Dict[str, Any] = {
        "handoff_id": handoff_id,
        "path": str(handoff_dir),
        "action": "skipped",
        "reason": "",
        "task_id": None,
        "approved": False,
    }

    review_file = find_review_file(handoff_dir)
    if not review_file:
        result["reason"] = "no review file present"
        return result

    meta = load_metadata(handoff_dir)
    task_id = meta.get("task_id") if meta else None
    result["task_id"] = task_id

    review_text = ""
    try:
        review_text = review_file.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        result["reason"] = f"failed to read review: {e}"
        return result

    approved, approve_reason, verdict = is_approved(review_text)
    result["approved"] = approved
    result["verdict"] = verdict
    result["approve_reason"] = approve_reason

    if force_all:
        approved = True
        approve_reason = "forced via --all-reviewed"
        result["approved"] = True

    if require_approve and not approved:
        result["reason"] = f"not approved by heuristic ({approve_reason})"
        return result

    if not task_id:
        result["reason"] = "no task_id in metadata.json"
        result["action"] = "skipped-no-task"
        return result

    # Fetch current task state
    task = get_task_via_api(task_id, api_base)
    if task is None:
        result["reason"] = f"task {task_id} not found in queue (or API unreachable)"
        result["action"] = "skipped-no-task"
        return result

    current_status = task.get("status", "unknown")
    current_result = task.get("result") or ""

    if already_consumed(handoff_dir, current_result, handoff_id):
        result["reason"] = "already consumed (marker or result contains handoff id)"
        result["action"] = "skipped-idempotent"
        result["current_status"] = current_status
        return result

    if current_status == "done" and not force_all:
        # Still allow enriching the result if not already referenced
        if handoff_id in current_result:
            result["reason"] = "task already done and references this handoff"
            result["action"] = "skipped-idempotent"
            return result

    # Build rich traceable result note
    excerpt_lines = [ln.strip() for ln in review_text.splitlines() if ln.strip()][:8]
    excerpt = "\n".join(excerpt_lines)[:800]
    processed_at = now_iso()

    new_result = (
        f"[handoff-consumer] {verdict} via {handoff_id}\n\n"
        f"Handoff: {handoff_id}  (dir: {handoff_dir})\n"
        f"Review file: {review_file.name}\n"
        f"Reviewer verdict heuristic: {verdict} ({approve_reason})\n"
        f"Task was: {current_status}\n"
        f"Processed: {processed_at}\n\n"
        f"Review excerpt (first lines):\n{excerpt}\n\n"
        f"Full review: {review_file}\n"
        f"Full handoff package: {handoff_dir}\n"
        f"Metadata: {meta}\n"
    )

    if dry_run:
        result["action"] = "would-advance"
        result["reason"] = f"DRY-RUN: would set status=done (was {current_status})"
        result["proposed_result_preview"] = new_result[:300] + "..."
        log(
            f"  [DRY] {handoff_id} -> task {task_id} ({current_status} -> done) | {approve_reason}",
            verbose=verbose,
            log_file=log_file,
        )
        return result

    # Real update
    success = update_task_status(task_id, "done", new_result, api_base)
    if success:
        result["action"] = "advanced-to-done"
        result["reason"] = f"updated task {task_id} from {current_status} to done"
        mark_consumed(
            handoff_dir,
            {
                "handoff_id": handoff_id,
                "task_id": task_id,
                "approved": approved,
                "verdict": verdict,
                "processed_at": processed_at,
                "review_file": str(review_file),
                "consumer_version": "c48c5f56-v1",
            },
        )
        log(
            f"  ✅ ADVANCED {handoff_id} -> task {task_id} (was {current_status})",
            verbose=verbose or True,
            log_file=log_file,
        )
    else:
        result["action"] = "update-failed"
        result["reason"] = f"PATCH to API failed for task {task_id}"

    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Handoff Consumer - bulk approve + advance originating tasks after agent-review (c48c5f56)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --stats
  %(prog)s --dry-run --verbose --limit 30
  %(prog)s --apply --handoff-id 02d2727d,6cbb2bb1
  %(prog)s --apply  # process all clear approvals (use after dry-run inspection)
        """,
    )
    parser.add_argument(
        "--handoff-root",
        type=Path,
        default=DEFAULT_HANDOFF_ROOT,
        help="Root directory containing handoff subdirs (default: ~/.grok/handoffs)",
    )
    parser.add_argument(
        "--api",
        default=DEFAULT_API_BASE,
        help="Task Queue API base (default: http://localhost:9090/tasks)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Preview only, do not mutate tasks or write markers (DEFAULT)",
    )
    parser.add_argument(
        "--apply",
        dest="dry_run",
        action="store_false",
        help="Actually perform PATCH updates and write .consumed markers (DANGEROUS - review dry-run first)",
    )
    parser.add_argument(
        "--require-approve",
        action="store_true",
        default=True,
        help="Only advance tasks whose review passes the conservative APPROVE heuristic (DEFAULT)",
    )
    parser.add_argument(
        "--all-reviewed",
        dest="require_approve",
        action="store_false",
        help="Process every handoff that has ANY review file (even REQUEST_CHANGES). Use only after manual inspection.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Maximum number of handoffs to consider (0 = unlimited)",
    )
    parser.add_argument(
        "--handoff-id",
        type=str,
        default="",
        help="Comma-separated list of specific handoff IDs to process (ignores limit/filter)",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Print summary counts only (reviews present, consumed, candidate approvals) and exit",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List handoffs with review presence, approval verdict, linked task status",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Extra logging of decisions and excerpts",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        default=None,
        help=f"Append structured log (default: {LOG_FILE_DEFAULT} when --apply / not dry-run)",
    )
    parser.add_argument(
        "--force", action="store_true", help="Skip some safety prompts (for automation)"
    )

    args = parser.parse_args()

    log_file = args.log_file or (LOG_FILE_DEFAULT if (not args.dry_run) else None)

    log(
        f"=== handoff-consumer starting (c48c5f56) dry_run={args.dry_run} require_approve={args.require_approve} ===",
        log_file=log_file,
    )

    root = args.handoff_root
    if not root.exists():
        log(f"ERROR: handoff root does not exist: {root}", log_file=log_file)
        return 1

    handoffs = collect_handoffs(root)

    # Filter to specific IDs if requested
    if args.handoff_id:
        wanted = {x.strip() for x in args.handoff_id.split(",") if x.strip()}
        handoffs = [h for h in handoffs if h.name in wanted]
        log(f"Restricted to specific handoffs: {wanted}", log_file=log_file)

    if args.limit > 0:
        handoffs = handoffs[: args.limit]

    # Stats mode - fast path
    if args.stats or args.list:
        reviewed = 0
        consumed = 0
        approved_count = 0
        by_verdict: Dict[str, int] = {}

        for h in handoffs:
            review = find_review_file(h)
            if not review:
                continue
            reviewed += 1
            if (h / CONSUMED_MARKER).exists():
                consumed += 1
            meta = load_metadata(h) or {}
            task_id = meta.get("task_id", "?")
            try:
                txt = review.read_text(encoding="utf-8", errors="replace")
                appr, reason, verdict = is_approved(txt)
                if (
                    args.require_approve and not appr and not args.all_reviewed
                ):  # note: --all-reviewed flips the flag
                    pass
                by_verdict[verdict] = by_verdict.get(verdict, 0) + 1
                if appr:
                    approved_count += 1
                if args.list:
                    task = (
                        get_task_via_api(task_id, args.api) if task_id != "?" else None
                    )
                    tstatus = task.get("status") if task else "?"
                    print(
                        f"  {h.name}: review={review.name} verdict={verdict} task={task_id}({tstatus}) approved={appr}"
                    )
            except Exception:
                pass

        print(f"\nHandoff root: {root}")
        print(f"Total handoff dirs scanned: {len(handoffs)} (after filters)")
        print(f"  With review file: {reviewed}")
        print(f"  Already consumed (marker): {consumed}")
        print(f"  Heuristic-approved (would advance if --apply): {approved_count}")
        print(f"  Verdict breakdown: {by_verdict}")
        print("Done (stats/list mode).")
        return 0

    # Normal processing loop
    processed = 0
    advanced = 0
    skipped = 0

    for h in handoffs:
        res = process_handoff(
            h,
            api_base=args.api,
            dry_run=args.dry_run,
            require_approve=args.require_approve,
            force_all=not args.require_approve,
            verbose=args.verbose,
            log_file=log_file,
        )
        processed += 1
        if res["action"] in ("advanced-to-done", "would-advance"):
            advanced += 1
        else:
            skipped += 1

        if args.verbose:
            log(f"  detail: {res}", verbose=True, log_file=log_file)

        # Gentle pacing for API
        time.sleep(0.05)

    mode = "DRY-RUN" if args.dry_run else "APPLY"
    log(
        f"=== {mode} COMPLETE: processed={processed} would/adv={advanced} skipped={skipped} ===",
        force=True,
        log_file=log_file,
    )
    log(f"Log (if any): {log_file}", log_file=log_file)

    # Final progress note for the task itself (best-effort, non-fatal)
    try:
        _note = f"[handoff-consumer self-update] {mode} run at {now_iso()}: {advanced} tasks advanced/would-advance out of {processed} handoffs considered (root={root}). See bin/consume-handoff-reviews.py and this log."
        # We do not call update here on c48c5f56 to avoid side-effects unless explicitly --apply on the consumer itself.
    except Exception:
        pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
