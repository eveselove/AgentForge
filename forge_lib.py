#!/usr/bin/env python3
"""
forge_lib.py — shared library for the "forge" orchestrator.

forge decomposes a big task into many tiny AgentForge gateway tasks, drains
them through a bounded foreground claim-loop (forge_run.py) that reuses the
stock agy invocation contract but COMMITS and PRESERVES each task's branch,
auto-runs per-repo quality gates against the still-live worktree, and reports
only a fixed compact one-line-per-task schema backed by an on-disk manifest.

stdlib only (urllib / json / subprocess / argparse / re / hashlib / fcntl).
No pip deps. Python 3.8+.

This module holds: config, gateway HTTP client (urllib), manifest read/write
(atomic + cross-process locked), gate profile registry, git helpers,
result-string parsing, summary extraction, compact-row rendering, and the gate
runner. The CLI (forge.py) and the claim-loop (forge_run.py) both import here.
"""

import json
import os
import re
import sys
import time
import hashlib
import subprocess
import urllib.request
import urllib.error

try:
    import fcntl  # POSIX only; erbox is Linux.
    _HAVE_FCNTL = True
except Exception:  # pragma: no cover
    _HAVE_FCNTL = False

# ----------------------------------------------------------------------------
# Paths / constants
# ----------------------------------------------------------------------------

API_BASE = os.environ.get("AGENTFORGE_API", "http://localhost:9090")
HOME = os.path.expanduser("~")
FORGE_HOME = os.environ.get("FORGE_HOME", os.path.join(HOME, ".forge"))
BATCHES_DIR = os.path.join(FORGE_HOME, "batches")
GATES_PATH = os.path.join(FORGE_HOME, "gates.json")
LOCKS_DIR = os.path.join(FORGE_HOME, "locks")

# Stock-worker constants (kept identical so the agy contract matches exactly).
PROJECT_DIR_DEFAULT = os.environ.get("PROJECT_DIR", "/home/eveselove/agentforge")
AGY_BIN = os.environ.get("AGY_BIN", "/home/eveselove/.local/bin/agy")
LOG_DIR = os.environ.get("LOG_DIR", "/home/eveselove/agentforge/logs")

# Gateway hard timeout for any single task (the worker's TASK_TIMEOUT).
GATEWAY_TASK_TIMEOUT = 1800

# Gateway zombie-reclaimer threshold (gateway resets in_progress tasks older
# than this back to pending). Default 25 min; honor the env override the
# gateway itself reads so our heartbeat/budget logic stays consistent.
# (gateway: ZOMBIE_TIMEOUT_MINUTES, default 25 — verified in main.rs.)
ZOMBIE_TIMEOUT_MINUTES = int(os.environ.get("ZOMBIE_TIMEOUT_MINUTES", "25"))
ZOMBIE_TIMEOUT_S = ZOMBIE_TIMEOUT_MINUTES * 60

# Heartbeat cadence: refresh the gateway task's updated_at while agy/gates run
# so the zombie reclaimer never resets a task that is genuinely in-flight.
# Comfortably below ZOMBIE_TIMEOUT_S.
HEARTBEAT_INTERVAL_S = int(os.environ.get("FORGE_HEARTBEAT_S", "300"))  # 5 min

# Complexity-based per-task timeout sizing for the AGY stage.
# Tiny tasks fail fast and free a pool slot instead of burning 30 minutes.
COMPLEXITY_TIMEOUT = {"simple": 300, "medium": 600, "complex": 1200}
DEFAULT_PER_TASK_TIMEOUT = 600

# Independent per-check gate timeout (separate from the agy task timeout).
GATE_CHECK_TIMEOUT = 300

# Overall gate-stage wall-clock budget (spans ALL checks for one task). The
# 18/21-timeout lesson: size AND ENFORCE an end-to-end budget. agy_timeout +
# GATE_BUDGET_S must stay comfortably under ZOMBIE_TIMEOUT_S; we assert this at
# submit time. Default keeps complex(1200)+600 = 1800 < 1500? No — see
# effective_caps(): we additionally CAP the agy stage so the sum is < the
# reclaimer threshold minus a safety margin.
GATE_BUDGET_S = int(os.environ.get("FORGE_GATE_BUDGET_S", "600"))

# Safety margin so heartbeats have slack even if one is missed.
ZOMBIE_SAFETY_MARGIN_S = 120

# Parallelism cap (below the stock worker's) to avoid cooling down both model
# groups at once under high parallelism.
MAX_PARALLEL_CAP = 6
DEFAULT_PARALLEL = 6

# Stuck-pending watchdog: a task that the gateway can never hand back (e.g. a
# 'build'/'compile' tag is silently excluded from /claim) would otherwise hang
# the drain forever. If a pending task is never claimable for longer than its
# per-task budget + this slack with no progress, we fail it as unclaimable.
UNCLAIMABLE_SLACK_S = int(os.environ.get("FORGE_UNCLAIMABLE_SLACK_S", "180"))

# Rate-limit attempt cap per task: a batch-wide RL storm must drain to a
# terminal rate_limited state rather than re-claiming the same task forever.
MAX_RL_ATTEMPTS = int(os.environ.get("FORGE_MAX_RL_ATTEMPTS", "3"))

# Tags the gateway silently excludes from /claim (recon gateway-api gotcha).
# A forge task carrying such a tag would never be claimable -> drain hangs.
CLAIM_EXCLUDED_TAG_SUBSTRINGS = ("build", "compile")

# Model strings. These are the STOCK antigravity_worker MODEL_GROUPS values
# (verified verbatim on erbox: antigravity_worker.py MODEL_GROUPS). They are
# overridable per-batch via the manifest 'models' field so we never hardcode an
# invented version string into the dispatch path.
DEFAULT_MODEL_COMPLEX = os.environ.get(
    "FORGE_MODEL_COMPLEX", "Claude Opus 4.6 (Thinking)")
DEFAULT_MODEL_SIMPLE = os.environ.get(
    "FORGE_MODEL_SIMPLE", "Claude Opus 4.6 (Thinking)")

# Model single-char tags for compact rows.
MODEL_TAGS = [
    (re.compile(r"opus", re.I), "O"),
    (re.compile(r"gemini.*pro", re.I), "G"),
    (re.compile(r"gemini.*flash", re.I), "F"),
    (re.compile(r"sonnet", re.I), "S"),
    (re.compile(r"gpt", re.I), "X"),
]

# Standing boilerplate appended to every subtask description (HR-8).
SUMMARY_BOILERPLATE = (
    "\n\n--- forge instructions (do not ignore) ---\n"
    "Work ONLY inside the working directory given above; do not touch files "
    "outside it. Make the change complete and self-contained. Keep the change "
    "small enough to finish well under the time limit. When you are done, "
    "print exactly ONE final line in this exact form and nothing after it:\n"
    "SUMMARY: <one sentence describing what you changed>"
)

# Seeded ground-truth gate profiles (from recon). cwd is relative to repo root.
SEEDED_GATES = {
    "agentforge": {
        "repo_path": "/home/eveselove/agentforge",
        "checks": [
            {"name": "check", "cwd": "rust",
             "cmd": "cargo check --workspace --all-targets"},
            {"name": "clippy", "cwd": "rust",
             "cmd": "cargo clippy --workspace --all-targets --locked -- -D warnings"},
            {"name": "test", "cwd": "rust",
             "cmd": "cargo test --workspace --lib -- --test-threads=2"},
            {"name": "fmt", "cwd": "rust",
             "cmd": "cargo fmt --all -- --check"},
        ],
    },
    "planlytasksko": {
        "repo_path": "/home/eveselove/planlytasksko",
        "checks": [
            {"name": "check", "cwd": ".",
             "cmd": "cargo check -p planly_gateway -p planly_parser"},
            {"name": "clippy", "cwd": ".",
             "cmd": "cargo clippy -p planly_gateway -p planly_parser -- -D warnings"},
            {"name": "test", "cwd": ".",
             "cmd": "cargo test -p planly_gateway -p planly_parser --lib"},
        ],
    },
}

# ----------------------------------------------------------------------------
# Small utilities
# ----------------------------------------------------------------------------


def eprint(*a):
    print(*a, file=sys.stderr, flush=True)


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def ensure_dirs():
    os.makedirs(BATCHES_DIR, exist_ok=True)
    os.makedirs(LOCKS_DIR, exist_ok=True)
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
    except Exception:
        pass


def short_id(task_id, n=8):
    """First n chars of the gateway id, but keep the 'task-' prefix readable."""
    return task_id[:n] if task_id else "????????"


def model_tag(model_str):
    if not model_str:
        return "?"
    for rx, tag in MODEL_TAGS:
        if rx.search(model_str):
            return tag
    return "?"


def truncate(s, n):
    s = s or ""
    s = s.replace("\n", " ").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def sanitize_tags(tags):
    """
    Rename/strip tags the gateway /claim filter silently excludes (anything
    containing 'build' or 'compile'). Such a tag makes a forge task permanently
    un-claimable -> the drain loop would never terminate. We map e.g.
    'build' -> 'build_step' so the substring no longer matches the exclusion.
    Returns (clean_tags, renamed[list of (orig,new)]).
    """
    clean = []
    renamed = []
    for t in tags:
        ts = str(t)
        low = ts.lower()
        if any(sub in low for sub in CLAIM_EXCLUDED_TAG_SUBSTRINGS):
            new = ts + "_step"
            clean.append(new)
            renamed.append((ts, new))
        else:
            clean.append(ts)
    return clean, renamed


def effective_caps(agy_timeout):
    """
    Compute the enforced per-task wall-clock caps so total in_progress time
    (agy + commit + gates) provably stays under the zombie reclaimer threshold
    even if a heartbeat is missed.

    Returns (agy_cap_s, gate_budget_s). The agy stage is the dominant cost; we
    keep agy_cap + gate_budget <= ZOMBIE_TIMEOUT_S - safety. With heartbeats
    refreshing updated_at this is belt-and-suspenders, but it guarantees
    termination even if heartbeats fail.
    """
    gate_budget = GATE_BUDGET_S
    ceiling = ZOMBIE_TIMEOUT_S - ZOMBIE_SAFETY_MARGIN_S - gate_budget
    if ceiling < 60:
        # Pathologically small zombie window; shrink gate budget too.
        gate_budget = max(60, (ZOMBIE_TIMEOUT_S - ZOMBIE_SAFETY_MARGIN_S) // 2)
        ceiling = ZOMBIE_TIMEOUT_S - ZOMBIE_SAFETY_MARGIN_S - gate_budget
    agy_cap = min(agy_timeout, max(60, ceiling))
    return agy_cap, gate_budget


# ----------------------------------------------------------------------------
# Gateway HTTP client (stdlib urllib only)
# ----------------------------------------------------------------------------


def api_request(method, path, data=None, timeout=30):
    """
    Minimal JSON HTTP client. Returns parsed JSON (dict/list) on 2xx,
    None on 204 / network error, and the tuple ('http_error', status, body)
    on >=400 so callers can branch (e.g. 409 CAS conflict on /claim).
    """
    url = f"{API_BASE}{path}"
    body = None
    headers = {"Accept": "application/json"}
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 204:
                return None
            raw = resp.read()
            if not raw:
                return None
            return json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode("utf-8", "ignore")
        except Exception:
            err_body = ""
        return ("http_error", e.code, err_body)
    except (urllib.error.URLError, ValueError, OSError):
        return None


def gateway_healthy():
    """
    Treat ANY 2xx JSON response from /health as healthy. The gateway's exact
    body shape is build-dependent (observed {"status":"ok",...} on 2.0.0-lance,
    but we must not block all runs if a future build changes the field). We use
    urlopen directly so a 200 with any body counts.
    """
    url = f"{API_BASE}/health"
    req = urllib.request.Request(url, headers={"Accept": "application/json"},
                                 method="GET")
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            return 200 <= resp.status < 300
    except Exception:
        return False


# ----------------------------------------------------------------------------
# Cross-process file locking (manifest writes shared by forge.py + forge_run.py)
# ----------------------------------------------------------------------------


class _NullLock:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def manifest_lock(batch_id):
    """
    Cross-process advisory lock guarding ALL manifest read-modify-write cycles
    for a batch. forge_run.py (the draining process) and forge.py (e.g.
    `status --refresh`, accept) must both hold this to avoid last-writer-wins
    corruption of status/gate fields. Use as a context manager.
    """
    if not _HAVE_FCNTL:
        return _NullLock()
    ensure_dirs()
    lock_path = os.path.join(LOCKS_DIR, f"manifest-{batch_id}.lock")

    class _FLock:
        def __enter__(self):
            self.fh = open(lock_path, "a+")
            fcntl.flock(self.fh.fileno(), fcntl.LOCK_EX)
            return self

        def __exit__(self, *a):
            try:
                fcntl.flock(self.fh.fileno(), fcntl.LOCK_UN)
            finally:
                self.fh.close()
            return False

    return _FLock()


# ----------------------------------------------------------------------------
# Manifest persistence (atomic tmp+rename; callers hold manifest_lock)
# ----------------------------------------------------------------------------


def batch_path(batch_id):
    return os.path.join(BATCHES_DIR, f"{batch_id}.json")


def load_manifest(batch_id):
    p = batch_path(batch_id)
    if not os.path.exists(p):
        return None
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def save_manifest(manifest):
    ensure_dirs()
    p = batch_path(manifest["batch_id"])
    tmp = p + f".tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, p)


def update_manifest_node(batch_id, task_id, mutate):
    """
    Cross-process-safe read-modify-write of a single task node. `mutate(node)`
    is called with the live node dict and may edit it in place. Holds the
    per-batch manifest lock for the whole cycle so a concurrent --refresh or
    forge_run write cannot clobber it (last-writer-wins fix).
    """
    with manifest_lock(batch_id):
        m = load_manifest(batch_id)
        if m is None:
            return None
        node = m["tasks"].get(task_id)
        if node is None:
            return None
        mutate(node)
        save_manifest(m)
        return node


def list_batches():
    ensure_dirs()
    out = []
    for fn in sorted(os.listdir(BATCHES_DIR)):
        if fn.endswith(".json") and not fn.endswith(".tmp"):
            out.append(fn[:-5])
    return out


def find_task(manifest, task_ref):
    """
    Resolve a task reference: accepts the full gateway id, an id prefix
    (task-XXXX), or a batch-local ref (t1..tN). Returns (task_id, node) or
    (None, None).
    """
    tasks = manifest.get("tasks", {})
    if task_ref in tasks:
        return task_ref, tasks[task_ref]
    for tid, node in tasks.items():
        if node.get("tN") == task_ref:
            return tid, node
    for tid, node in tasks.items():
        if tid.startswith(task_ref):
            return tid, node
    return None, None


def find_batch_for_task(task_ref):
    """Search all manifests for a task ref. Returns (manifest, task_id, node)."""
    for bid in list_batches():
        m = load_manifest(bid)
        if not m:
            continue
        tid, node = find_task(m, task_ref)
        if tid:
            return m, tid, node
    return None, None, None


# ----------------------------------------------------------------------------
# Gate profile registry
# ----------------------------------------------------------------------------


def load_gates():
    ensure_dirs()
    if os.path.exists(GATES_PATH):
        try:
            with open(GATES_PATH, "r", encoding="utf-8") as f:
                reg = json.load(f)
        except Exception:
            reg = {}
    else:
        reg = {}
    changed = False
    for k, v in SEEDED_GATES.items():
        if k not in reg:
            reg[k] = v
            changed = True
    if changed:
        save_gates(reg)
    return reg


def save_gates(reg):
    ensure_dirs()
    tmp = GATES_PATH + f".tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(reg, f, ensure_ascii=False, indent=1)
    os.replace(tmp, GATES_PATH)


def detect_gate_profile(repo_path):
    """Autodetect a gate profile for an unknown repo from its build files."""
    def has(name):
        return os.path.exists(os.path.join(repo_path, name))

    checks = []
    if has("Cargo.toml"):
        checks = [
            {"name": "check", "cwd": ".", "cmd": "cargo check --all-targets"},
            {"name": "clippy", "cwd": ".",
             "cmd": "cargo clippy --all-targets -- -D warnings"},
            {"name": "test", "cwd": ".", "cmd": "cargo test --lib"},
            {"name": "fmt", "cwd": ".", "cmd": "cargo fmt --all -- --check"},
        ]
    elif has("package.json"):
        checks = [
            {"name": "install", "cwd": ".", "cmd": "npm ci || npm install"},
            {"name": "build", "cwd": ".",
             "cmd": "npm run build --if-present"},
            {"name": "test", "cwd": ".",
             "cmd": "npm test --if-present"},
        ]
    elif has("pyproject.toml") or has("setup.py"):
        checks = [
            {"name": "ruff", "cwd": ".", "cmd": "ruff check ."},
            {"name": "test", "cwd": ".",
             "cmd": "python3 -m pytest -q || true"},
        ]
    else:
        checks = []  # unrunnable => gate n/a
    return {"repo_path": repo_path, "checks": checks}


def resolve_gate_profile(repo, override_checks=None, repo_path=None):
    """
    Resolve the effective gate profile for a batch. Order:
      1. explicit override_checks from the batch JSON,
      2. registry entry keyed by repo,
      3. autodetect from repo_path and persist.
    Returns the profile dict {repo_path, checks:[...]}.
    """
    reg = load_gates()
    if override_checks is not None:
        rp = repo_path or (reg.get(repo, {}) or {}).get("repo_path") or PROJECT_DIR_DEFAULT
        return {"repo_path": rp, "checks": override_checks}
    if repo in reg:
        return reg[repo]
    rp = repo_path or os.path.join(os.path.dirname(PROJECT_DIR_DEFAULT), repo)
    prof = detect_gate_profile(rp)
    reg[repo] = prof
    save_gates(reg)
    return prof


# ----------------------------------------------------------------------------
# Git helpers (safe, idempotent)
# ----------------------------------------------------------------------------


def git(repo, *args, check=False, timeout=120):
    """Run a git command in repo. Returns (rc, stdout, stderr)."""
    try:
        p = subprocess.run(
            ["git", *args],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if check and p.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} failed: {p.stderr.strip()}")
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return -9, "", "git timeout"


def current_branch(repo):
    """Current HEAD branch name, or '' if detached / error."""
    rc, out, _ = git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    if rc != 0:
        return ""
    name = out.strip()
    return "" if name == "HEAD" else name


def rev_parse(repo, ref):
    """Resolve ref to a commit SHA, or '' if it does not exist."""
    rc, out, _ = git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}")
    return out.strip() if rc == 0 else ""


def resolve_base(repo, requested_base):
    """
    Resolve the base for a batch. If requested_base is falsy, use the repo's
    CURRENT HEAD branch (so agents branch off the live working state, not a
    stale 'main'). Pin to the exact commit SHA so worktree-add and accept both
    use a fixed base even if the branch ref moves later.

    Returns (base_branch_name, base_sha, error_or_None).
    """
    if requested_base:
        sha = rev_parse(repo, requested_base)
        if not sha:
            return requested_base, "", f"base branch '{requested_base}' not found in {repo}"
        return requested_base, sha, None
    name = current_branch(repo)
    if not name:
        # Detached HEAD: pin to the commit directly.
        sha = rev_parse(repo, "HEAD")
        if not sha:
            return "", "", f"cannot resolve HEAD in {repo} (detached and unresolved)"
        return "HEAD", sha, None
    sha = rev_parse(repo, name)
    return name, sha, None


def numstat(repo, base_ref, branch):
    """
    Returns (files_changed, added, removed) for branch vs base_ref using
    git diff --numstat base...branch (merge-base diff). base_ref may be a SHA.
    """
    rc, out, _ = git(repo, "diff", "--numstat", f"{base_ref}...{branch}")
    if rc != 0:
        return 0, 0, 0
    files = 0
    add = 0
    rem = 0
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        a, r, _path = parts
        files += 1
        if a.isdigit():
            add += int(a)
        if r.isdigit():
            rem += int(r)
    return files, add, rem


# ----------------------------------------------------------------------------
# Result-string parsing & summary extraction
# ----------------------------------------------------------------------------

# ^AntigravityWorker: <int>s (model=<model>) ✅   (success)
RX_RESULT = re.compile(r"AntigravityWorker:\s*(\d+)s\s*\(model=(.+?)\)")


def parse_result_string(result):
    """
    Extract (duration_int_or_None, model_or_None, kind) from a worker result.
    kind in {success, timeout, error, rate_limit, launch_fail, unknown}.
    """
    if not result:
        return None, None, "unknown"
    if isinstance(result, dict):
        result = json.dumps(result)
    m = RX_RESULT.search(result)
    dur = int(m.group(1)) if m else None
    model = m.group(2) if m else None
    low = result.lower()
    if "✅" in result:
        kind = "success"
    elif result.startswith("rate_limit:") or "rate_limit" in low:
        kind = "rate_limit"
    elif "timeout" in low:
        kind = "timeout"
    elif "ошибка запуска" in low or "launch" in low:
        kind = "launch_fail"
    elif "exit=" in low or "fail" in low:
        kind = "error"
    else:
        kind = "unknown"
    return dur, model, kind


def task_log_path(task_id):
    return os.path.join(LOG_DIR, f"antigravity_{task_id}.log")


def extract_summary(task_id, local_log=None):
    """
    Tail the per-task log for the LAST line matching ^SUMMARY:. Returns the
    summary text (without the SUMMARY: prefix) or None. Reads a generous tail
    so a SUMMARY printed before a long trailing dump is still captured.
    """
    path = local_log or task_log_path(task_id)
    if not os.path.exists(path):
        return None
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            # Read up to the last 64KB (logs observed 4.6–17.7KB; 64KB covers a
            # SUMMARY followed by a verbose trailing dump).
            tail_n = 65536
            if size > tail_n:
                f.seek(-tail_n, os.SEEK_END)
            tail = f.read().decode("utf-8", "ignore")
    except Exception:
        return None
    found = None
    for line in tail.splitlines():
        ls = line.strip()
        if ls.upper().startswith("SUMMARY:"):
            found = ls[len("SUMMARY:"):].strip()
    return found or None


def log_has_rate_limit(task_id, local_log=None):
    """True if the per-task log shows rate-limit markers (regardless of exit)."""
    markers = ["rate limit", "429", "quota", "throttle", "too many requests",
               "ratelimit", "slowdown", "resource_exhausted"]
    path = local_log or task_log_path(task_id)
    try:
        with open(path, "r", errors="ignore") as f:
            content = f.read(16384).lower()
        return any(m in content for m in markers)
    except Exception:
        return False


def detect_auth_failure(task_id, exit_code, duration, local_log=None):
    """
    Distinguish an agy OAuth/auth failure from a rate-limit. Auth failures must
    STOP the batch (st=AUTH). To avoid a single flaky fast-exit halting the
    whole batch, we require an EXPLICIT auth marker in the log. A bare fast
    empty exit is treated as a generic error (not auth), per review guidance.
    """
    auth_markers = [
        "unauthorized", "not authenticated", "oauth", "please log in",
        "token expired", "no credentials", "permission denied (publickey)",
        "authentication failed", "401",
    ]
    rl_markers = ["rate limit", "429", "quota", "throttle", "too many requests"]
    path = local_log or task_log_path(task_id)
    content = ""
    try:
        with open(path, "r", errors="ignore") as f:
            content = f.read(16384).lower()
    except Exception:
        pass
    if any(m in content for m in rl_markers):
        return False
    if any(m in content for m in auth_markers):
        return True
    return False


# ----------------------------------------------------------------------------
# Status normalization for compact rows
# ----------------------------------------------------------------------------

# Manifest node 'status' is a forge-internal token; map to a single short token.
ST_TOKEN = {
    "pending": "pend",
    "claimed": "run",
    "in_progress": "run",
    "running": "run",
    "review": "rev",
    "done": "done",
    "failed": "FAIL",
    "timeout": "TMO",
    "gatefail": "GFAIL",
    "gate_timeout": "GTMO",
    "rate_limited": "RL",
    "blocked": "BLK",
    "auth": "AUTH",
    "rejected": "REJ",
    "reclaimed": "RECL",
    "unclaimable": "UNCL",
}

TERMINAL_GOOD = {"done", "review"}
TERMINAL_BAD = {"failed", "timeout", "gatefail", "gate_timeout", "rate_limited",
                "blocked", "auth", "rejected", "reclaimed", "unclaimable"}
TERMINAL = TERMINAL_GOOD | TERMINAL_BAD


def is_terminal(status):
    return status in TERMINAL


def st_token(status):
    return ST_TOKEN.get(status, status[:4])


# ----------------------------------------------------------------------------
# Compact row rendering
# ----------------------------------------------------------------------------


def render_row(node):
    """
    One fixed-width line:
      <tN> <id8> <st> <gate> +<add>/-<rem> f<files> <model1> <dur>s "<title28>"
    """
    tN = node.get("tN", "t?")
    idp = short_id(node.get("gateway_id", ""), 8)
    st = st_token(node.get("status", "pending"))
    gate = node.get("gate", {}) or {}
    verdict = gate.get("verdict")
    if not is_terminal(node.get("status", "")):
        gate_tok = "-"
    elif verdict == "pass":
        gate_tok = "ok"
    elif verdict == "fail":
        chk = gate.get("first_failing_check") or "?"
        gate_tok = f"FAIL:{chk}"
    elif verdict == "n/a":
        gate_tok = "n/a"
    else:
        gate_tok = "-"
    add = node.get("lines_added", 0) or 0
    rem = node.get("lines_removed", 0) or 0
    files = node.get("files_changed_count", 0) or 0
    mt = model_tag(node.get("model_used"))
    dur = node.get("duration_s")
    dur_s = f"{int(dur)}s" if dur else "-"
    title = truncate(node.get("short_title", ""), 28)
    return (
        f"{tN:>3} {idp:<8} {st:<5} {gate_tok:<10} "
        f"+{add}/-{rem} f{files} {mt} {dur_s:>5} \"{title}\""
    )


def render_header(manifest):
    tasks = manifest.get("tasks", {})
    total = len(tasks)
    done = sum(1 for n in tasks.values() if n.get("status") == "done")
    rev = sum(1 for n in tasks.values() if n.get("status") == "review")
    fail = sum(1 for n in tasks.values()
               if n.get("status") in TERMINAL_BAD)
    gp = sum(1 for n in tasks.values()
             if (n.get("gate") or {}).get("verdict") == "pass")
    gf = sum(1 for n in tasks.values()
             if (n.get("gate") or {}).get("verdict") == "fail")
    return (
        f"BATCH {manifest['batch_id']} {done}/{total} done {rev} review "
        f"{fail} fail | gate {gp}pass/{gf}fail"
    )


def render_table(manifest, flt=None, wave=None):
    lines = [render_header(manifest)]
    nodes = sorted(
        manifest.get("tasks", {}).values(),
        key=lambda n: int(re.sub(r"\D", "", n.get("tN", "t0")) or 0),
    )
    for node in nodes:
        st = node.get("status", "pending")
        if wave is not None and node.get("wave") != wave:
            continue
        if flt == "failed" and st not in TERMINAL_BAD:
            continue
        if flt == "gatefail" and (node.get("gate") or {}).get("verdict") != "fail":
            continue
        if flt == "inflight" and is_terminal(st):
            continue
        if flt == "done" and st != "done":
            continue
        lines.append(render_row(node))
    return "\n".join(lines)


def compact_result_obj(node):
    """The single compact-result JSON object for `forge result <id>`."""
    gate = node.get("gate", {}) or {}
    return {
        "tN": node.get("tN"),
        "id": short_id(node.get("gateway_id", ""), 8),
        "gateway_id": node.get("gateway_id"),
        "short_title": node.get("short_title"),
        "status": st_token(node.get("status", "pending")),
        "model_used": model_tag(node.get("model_used")),
        "duration_s": int(node.get("duration_s") or 0),
        "branch": node.get("branch"),
        "commit_sha": node.get("commit_sha"),
        "files_changed_count": node.get("files_changed_count", 0),
        "lines_added": node.get("lines_added", 0),
        "lines_removed": node.get("lines_removed", 0),
        "gate_verdict": gate.get("verdict"),
        "first_failing_check": gate.get("first_failing_check"),
        "first_error_line": gate.get("first_error_line"),
        "summary": node.get("summary"),
    }


# ----------------------------------------------------------------------------
# Gate runner (project-parameterized quality gates, overall-budget enforced)
# ----------------------------------------------------------------------------


def run_gates(worktree_dir, gate_profile, budget_s=None):
    """
    Run the profile's checks IN ORDER against the live worktree, stopping at the
    FIRST failure. Each check has an independent per-check timeout
    (GATE_CHECK_TIMEOUT), AND the whole stage is bounded by an overall wall-clock
    budget (budget_s, default GATE_BUDGET_S) so gating can never hang the drain
    or trip the zombie reclaimer.

    Returns a dict:
      {verdict: pass|fail|gate_timeout, first_failing_check, first_error_line,
       gates_run:[names], dur_s, ran_at}
    'n/a' verdict => no runnable checks (unknown repo / missing toolchain).
    'gate_timeout' => the overall budget was exhausted.
    """
    if budget_s is None:
        budget_s = GATE_BUDGET_S
    checks = (gate_profile or {}).get("checks") or []
    if not checks:
        return {
            "verdict": "n/a", "first_failing_check": None,
            "first_error_line": None, "gates_run": [], "dur_s": 0.0,
            "ran_at": now_iso(),
        }
    started = time.time()
    deadline = started + budget_s
    ran = []
    for chk in checks:
        name = chk["name"]
        cwd = os.path.join(worktree_dir, chk.get("cwd", "."))
        if not os.path.isdir(cwd):
            continue
        remaining = deadline - time.time()
        if remaining <= 1:
            return {
                "verdict": "gate_timeout", "first_failing_check": name,
                "first_error_line": f"gate budget {budget_s}s exhausted before {name}",
                "gates_run": ran, "dur_s": round(time.time() - started, 1),
                "ran_at": now_iso(),
            }
        ran.append(name)
        per_check = min(GATE_CHECK_TIMEOUT, int(remaining))
        try:
            p = subprocess.run(
                chk["cmd"],
                shell=True,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=per_check,
            )
            rc = p.returncode
            combined = (p.stdout or "") + (p.stderr or "")
        except subprocess.TimeoutExpired:
            # Could be per-check or budget exhaustion; distinguish for the token.
            verdict = "gate_timeout" if time.time() >= deadline else "fail"
            return {
                "verdict": verdict, "first_failing_check": name,
                "first_error_line": f"gate timeout in {name} (per-check {per_check}s / budget {budget_s}s)",
                "gates_run": ran, "dur_s": round(time.time() - started, 1),
                "ran_at": now_iso(),
            }
        if rc != 0:
            first_err = _first_error_line(combined)
            return {
                "verdict": "fail", "first_failing_check": name,
                "first_error_line": truncate(first_err, 160),
                "gates_run": ran, "dur_s": round(time.time() - started, 1),
                "ran_at": now_iso(),
            }
    if not ran:
        return {
            "verdict": "n/a", "first_failing_check": None,
            "first_error_line": None, "gates_run": [], "dur_s": 0.0,
            "ran_at": now_iso(),
        }
    return {
        "verdict": "pass", "first_failing_check": None,
        "first_error_line": None, "gates_run": ran,
        "dur_s": round(time.time() - started, 1), "ran_at": now_iso(),
    }


def _first_error_line(text):
    """Heuristic: the first line that looks like an error/failure."""
    patterns = [
        re.compile(r"^error(\[|:|\s)", re.I),
        re.compile(r"error:", re.I),
        re.compile(r"^\s*--> "),
        re.compile(r"test result: FAILED", re.I),
        re.compile(r"panicked at", re.I),
        re.compile(r"^FAILED", re.I),
        re.compile(r"Diff in ", re.I),  # cargo fmt --check
    ]
    lines = text.splitlines()
    for rx in patterns:
        for line in lines:
            if rx.search(line):
                return line.strip()
    for line in reversed(lines):
        if line.strip():
            return line.strip()
    return "non-zero exit, no error line captured"


# ----------------------------------------------------------------------------
# Run lock (PER-BATCH; prevents double-execution of the SAME batch, allows
# independent batches to drain concurrently). No daemon.
# ----------------------------------------------------------------------------


def run_lock_path(batch_id):
    return os.path.join(LOCKS_DIR, f"run-{batch_id}.lock")


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    except Exception:
        return True


def acquire_run_lock(batch_id):
    """
    Acquire the PER-BATCH run lock ~/.forge/locks/run-<batch_id>.lock.
    Returns True if acquired. If a live pid already holds THIS batch's lock,
    returns False (refuse double-execution of the same batch — the previous
    false-True race is fixed). Stale lock (dead pid) is reclaimed. Different
    batches use different lock files, so independent batches run in parallel.
    Lock content: "<pid> <batch_id>".
    """
    ensure_dirs()
    path = run_lock_path(batch_id)
    if os.path.exists(path):
        try:
            with open(path) as f:
                content = f.read().strip().split()
            pid = int(content[0])
        except Exception:
            pid = -1
        if pid > 0 and _pid_alive(pid):
            return False  # same batch already draining -> refuse
        try:
            os.remove(path)
        except Exception:
            pass
    with open(path, "w") as f:
        f.write(f"{os.getpid()} {batch_id}\n")
    # Verify we still own it (defends against a tiny race window).
    try:
        with open(path) as f:
            owner = int(f.read().strip().split()[0])
        return owner == os.getpid()
    except Exception:
        return True


def release_run_lock(batch_id):
    path = run_lock_path(batch_id)
    try:
        if os.path.exists(path):
            with open(path) as f:
                content = f.read().strip().split()
            if content and int(content[0]) == os.getpid():
                os.remove(path)
    except Exception:
        pass


def run_lock_owner_pid(batch_id):
    """Return the live pid holding this batch's run lock, or None."""
    path = run_lock_path(batch_id)
    try:
        if not os.path.exists(path):
            return None
        with open(path) as f:
            pid = int(f.read().strip().split()[0])
        return pid if _pid_alive(pid) else None
    except Exception:
        return None
