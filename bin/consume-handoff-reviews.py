#!/usr/bin/env python3
"""
Handoff Consumer Script (Post-100% Hardening: c48c5f56 + audit-hardening v2)

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

# Version for markers/logs (bump on hardening changes)
CONSUMER_VERSION = "c48c5f56-v2"


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

    # Very conservative fallback: "No BUGs" + "APPROVE" word somewhere prominent.
    # Also: if positive bug count (and no prior explicit APPROVE verdict matched),
    # reject per docstring promise ("rejects on ... or high bug counts").
    bug_count_match = re.search(
        r"(Bugs|BUGs)\s*[:\-]?\s*(\d+)", review_text, re.IGNORECASE
    )
    if bug_count_match:
        bc = int(bug_count_match.group(2))
        if bc == 0:
            if "APPROVE" in upper[-2000:]:  # last ~2k chars
                return True, "zero bugs + APPROVE token present", "APPROVE_LIKELY"
        else:
            return (
                False,
                f"positive bug count ({bc}) and no explicit APPROVE verdict",
                "BLOCKED_BUGS",
            )

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
            status = getattr(resp, "status", None) or getattr(resp, "code", 0) or 0
            if 200 <= status < 300:
                body = resp.read().decode("utf-8")
                return json.loads(body) if body and body.strip() else {}
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
            status = getattr(resp, "status", None) or getattr(resp, "code", 0) or 0
            return 200 <= status < 300
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
    if task_result and (
        f"via {handoff_id}\n" in task_result or f"Handoff: {handoff_id}" in task_result
    ):
        return True
    return False


def is_pid_alive(pid: int) -> bool:
    """Check if pid is currently running (for stale claim detection)."""
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)  # no signal, just existence check
        return True
    except ProcessLookupError:
        return False
    except Exception:
        # permission or other: assume alive to be conservative (don't steal live)
        return True


def _read_last_lines(p: Path, n: int, max_bytes: int = 16384) -> str:
    """Lightning-fast tail read for verdict area (avoid full load of huge reviews in stats)."""
    try:
        with p.open("rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            if size == 0:
                return ""
            to_read = min(size, max_bytes)
            f.seek(-to_read, os.SEEK_END)
            chunk = f.read(to_read)
        text = chunk.decode("utf-8", errors="replace")
        lines = text.splitlines(keepends=False)
        return "\n".join(lines[-n:])
    except Exception:
        try:
            full = p.read_text(encoding="utf-8", errors="replace")
            return "\n".join(full.splitlines()[-n:])
        except Exception:
            return ""


def claim_consumed(handoff_dir: Path, info: Dict[str, Any]) -> bool:
    """Atomic claim via O_EXCL marker create. Prevents concurrent consumers
    from both PATCHing the same task (data race on marker+result checks).
    Returns True only if this process created the marker exclusively.
    Cleans up on write failure to avoid stuck/empty markers blocking retries.
    """
    marker = handoff_dir / CONSUMED_MARKER
    try:
        fd = os.open(str(marker), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        return False
    except Exception:
        return False
    try:
        payload = json.dumps(info, indent=2, ensure_ascii=False) + "\n"
        data = payload.encode("utf-8")
        n = os.write(fd, data)
        if n != len(data):
            raise IOError("incomplete write")
    except Exception:
        try:
            os.close(fd)
        except Exception:
            pass
        try:
            marker.unlink()
        except Exception:
            pass
        return False
    finally:
        try:
            os.close(fd)
        except Exception:
            pass
    return True


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
        "did_network": False,
    }

    review_file = find_review_file(handoff_dir)
    if not review_file:
        result["reason"] = "no review file present"
        return result

    # Load meta early (cheap). This enables early idempotency checks via task
    # result *before* reading potentially-large review text (perf + race safety).
    meta = load_metadata(handoff_dir)
    task_id = meta.get("task_id") if meta else None
    result["task_id"] = task_id

    # Fast-path skip for marker BEFORE read/is_approved or network (perf win).
    # v2: distinguish FULL (has processed_at) vs PARTIAL/STALE claim (crash after O_EXCL but before PATCH).
    # Stale (pid dead) -> unlink + fallthrough for recovery (prevents permanent stuck tasks).
    # Live claim -> skip (in progress). Partial without pid -> treat as stale for recovery.
    marker_path = handoff_dir / CONSUMED_MARKER
    if marker_path.exists():
        is_full = False
        claimed_pid = None
        try:
            mdata = json.loads(
                marker_path.read_text(encoding="utf-8", errors="replace")
            )
            if mdata.get("processed_at"):
                is_full = True
            claimed_pid = mdata.get("pid")
        except Exception:
            # corrupt marker: treat as stale so we can recover below
            is_full = False
            claimed_pid = None
        if is_full:
            result["reason"] = "already consumed (marker)"
            result["action"] = "skipped-idempotent"
            result["current_status"] = "unknown"
            return result
        # partial claim marker
        if claimed_pid and is_pid_alive(claimed_pid):
            result["reason"] = f"already claimed by live pid {claimed_pid} (in progress)"
            result["action"] = "skipped-claimed"
            result["current_status"] = "unknown"
            return result
        # stale or no pid: safe to recover - unlink and fallthrough to verify+re-process
        try:
            marker_path.unlink()
            log(
                f"  [RECOVER] unlinked stale/partial claim marker for {handoff_id} (pid {claimed_pid or 'n/a'})",
                verbose=verbose,
                log_file=log_file,
            )
        except Exception:
            pass
        # fall through to net fetch + already check + claim (will re-advance if needed)

    if not task_id:
        result["reason"] = "no task_id in metadata.json"
        result["action"] = "skipped-no-task"
        return result

    # Hoist task fetch + already_consumed (result ref) check before read review.
    # This closes a narrow perf place: previously reviewed large .md even for
    # already-referenced (idempotent) handoffs that had no marker.
    # Also strengthens TOCTOU protection: we only read/review when we may act.
    task = get_task_via_api(task_id, api_base)
    result["did_network"] = True
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
        # Backfill .consumed marker (if absent) so future runs hit ultra-fast early-marker
        # path (no GET, no sleep, no review read). This is the key fix for repeated-scan
        # bottleneck on large history of handoffs that were advanced via result-ref only.
        if not (handoff_dir / CONSUMED_MARKER).exists():
            try:
                mark_consumed(
                    handoff_dir,
                    {
                        "handoff_id": handoff_id,
                        "task_id": task_id,
                        "approved": result.get("approved", False),
                        "verdict": result.get("verdict", "ALREADY_VIA_RESULT"),
                        "discovered_at": now_iso(),
                        "consumer_version": CONSUMER_VERSION,
                        "note": "backfilled from result-ref (no prior marker)",
                    },
                )
            except Exception:
                pass
        return result

    # (no marker, has task_id, task exists, no ref in result -> may proceed to review+claim)

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
        verdict = "APPROVE_FORCED"
        result["approved"] = True
        result["verdict"] = verdict

    if require_approve and not approved:
        result["reason"] = f"not approved by heuristic ({approve_reason})"
        return result

    # Note: the previous "if done and not force: if ref: skip" block is removed --
    # it was dead code after already_consumed (which catches refs first) and
    # is no longer needed; behavior for done-no-ref (enrich) is unchanged.

    # Atomic claim to close TOCTOU race with concurrent consumers (marker check
    # + task result check are not atomic across processes).
    if not dry_run:
        claim_info = {
            "handoff_id": handoff_id,
            "task_id": task_id,
            "approved": approved,
            "verdict": verdict,
            "claimed_at": now_iso(),
            "pid": os.getpid(),
            "consumer_version": CONSUMER_VERSION,
        }
        if not claim_consumed(handoff_dir, claim_info):
            result["action"] = "skipped-race"
            result["reason"] = (
                "concurrent consumer claimed this handoff (data race avoided)"
            )
            return result

        # Re-fetch under our claim to get the *freshest* current_result before append.
        # Narrows the TOCTOU / lost-update window for result clobber if other writers
        # (workers, manual, concurrent consumers for *other* handoffs on same task) PATCH
        # concurrently. (Not 100% but best-effort without server-side CAS/append.)
        try:
            fresh = get_task_via_api(task_id, api_base)
            if fresh:
                current_result = fresh.get("result") or current_result
                current_status = fresh.get("status", current_status)
                result["did_network"] = True
        except Exception:
            pass

    # Build rich traceable result note; always append to prior result (if any)
    # to avoid clobbering original task output from worker on enrich/done cases.
    excerpt_lines = [ln.strip() for ln in review_text.splitlines() if ln.strip()][:8]
    excerpt = "\n".join(excerpt_lines)[:800]
    processed_at = now_iso()

    consumer_note = (
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
    if current_result:
        new_result = current_result.rstrip() + "\n\n" + consumer_note
    else:
        new_result = consumer_note

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
        # Overwrite claim marker with final info (includes processed_at)
        mark_consumed(
            handoff_dir,
            {
                "handoff_id": handoff_id,
                "task_id": task_id,
                "approved": approved,
                "verdict": verdict,
                "processed_at": processed_at,
                "review_file": str(review_file),
                "consumer_version": CONSUMER_VERSION,
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
        # Unclaim so a future run (after transient fix) can retry this handoff
        try:
            (handoff_dir / CONSUMED_MARKER).unlink()
        except Exception:
            pass

    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Handoff Consumer - bulk approve + advance originating tasks after agent-review (c48c5f56 + v2: race recovery, marker backfill, claim re-fetch, force gate)",
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
        f"=== handoff-consumer starting (c48c5f56-v2) dry_run={args.dry_run} require_approve={args.require_approve} force={args.force} ===",
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

    if args.limit > 0 and not args.handoff_id:
        handoffs = handoffs[: args.limit]

    # Safety gate for dangerous mode (activates the --force arg which was parsed but unused).
    # --all-reviewed processes *even* REQUEST_CHANGES/REJECT/blocked-bugs reviews.
    # Requires explicit --force (or --handoff-id) + (ideally) prior --dry-run --list.
    if (not args.dry_run) and (not args.force) and (not args.require_approve):
        log(
            "ERROR: --all-reviewed without --force is unsafe (processes non-approved reviews in bulk). "
            "Use after manual inspection + --force, or restrict with --handoff-id.",
            log_file=log_file,
        )
        return 1

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
            is_cons = (h / CONSUMED_MARKER).exists()
            if is_cons:
                consumed += 1
            meta = load_metadata(h) or {}
            task_id = meta.get("task_id", "?")
            appr = False
            verdict = "?"
            try:
                if is_cons:
                    # Perf: use tiny .consumed marker for verdict/approved on consumed
                    # (avoids re-reading large review .md files on every --stats/--list)
                    try:
                        mdata = json.loads(
                            (h / CONSUMED_MARKER).read_text(
                                encoding="utf-8", errors="replace"
                            )
                        )
                        verdict = mdata.get("verdict") or "CONSUMED"
                        appr = bool(mdata.get("approved", False))
                    except Exception:
                        # fallback to review read if marker corrupt
                        txt = review.read_text(encoding="utf-8", errors="replace")
                        appr, _r, verdict = is_approved(txt)
                else:
                    txt = review.read_text(encoding="utf-8", errors="replace")
                    appr, _r, verdict = is_approved(txt)
                by_verdict[verdict] = by_verdict.get(verdict, 0) + 1
                if appr:
                    approved_count += 1
                if args.list:
                    # Lightning optimization: avoid net GET for consumed (historical) handoffs.
                    # Consumed almost always means task is done (or was enriched). Pending (non-cons)
                    # are the ones worth live status query. Saves N roundtrips on large histories.
                    if is_cons:
                        tstatus = "done (marker)"
                    else:
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

        # Gentle pacing for API (only after actual network calls; skips on pure
        # filtered handoffs cost 0 delay).
        if res.get("did_network"):
            time.sleep(0.05)

    mode = "DRY-RUN" if args.dry_run else "APPLY"
    log(
        f"=== {mode} COMPLETE: processed={processed} would/adv={advanced} skipped={skipped} (v2 hardened) ===",
        force=True,
        log_file=log_file,
    )
    log(f"Log (if any): {log_file}", log_file=log_file)

    return 0


if __name__ == "__main__":
    sys.exit(main())
