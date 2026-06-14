"""
AgentForge Settings — centralised paths and configuration.
All modules import from here instead of hardcoding paths.
"""

import os

# ── Directories ──────────────────────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
LOG_DIR = os.path.join(PROJECT_ROOT, "logs")

# ── Databases ────────────────────────────────────────────────
CHECKPOINTS_DB = os.path.join(DATA_DIR, "task_checkpoints.db")
TASKS_DB = os.path.join(DATA_DIR, "tasks.db")

# ── Gateway ──────────────────────────────────────────────────
GATEWAY_URL = os.environ.get("PLANLY_GATEWAY", "http://localhost:3000")
API_BASE = os.environ.get("AGENTFORGE_API", "http://127.0.0.1:9090")

# ── Watchdog ─────────────────────────────────────────────────
POLL_INTERVAL = int(os.environ.get("WATCHDOG_POLL", "10"))
LOOP_THRESHOLD = int(os.environ.get("WATCHDOG_LOOP_THRESHOLD", "5"))
MAX_LOG_SIZE_MB = float(os.environ.get("WATCHDOG_MAX_LOG_MB", "2.0"))

# ── Worker ───────────────────────────────────────────────────
WORK_DIR = os.environ.get("AGENTFORGE_WORKDIR", "/tmp/agentforge")
DRY_RUN = os.environ.get("DRY_RUN", "0") == "1"

# Ensure dirs exist
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)
