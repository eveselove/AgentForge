"""
Mappings between Evaluation Benchmark Tasks and real AgentForge tasks.

This module provides a clean way to track:
- Which real AgentForge task corresponds to which benchmark
- Execution status
- When it was dispatched

Stored in a simple JSON file for now (easy to evolve later).
"""
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

_DEFAULT_MAPPINGS_DIR = Path(__file__).parent / "mappings"
MAPPINGS_DIR = Path(
    os.environ.get("AGENTFORGE_EVAL_MAPPINGS_DIR", str(_DEFAULT_MAPPINGS_DIR))
)
MAPPINGS_DIR.mkdir(parents=True, exist_ok=True)

MAPPINGS_FILE = MAPPINGS_DIR / "eval_mappings.json"


def _load_mappings() -> Dict[str, Dict[str, Any]]:
    if not MAPPINGS_FILE.exists():
        return {}
    try:
        with open(MAPPINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_mappings(data: Dict[str, Dict[str, Any]]):
    with open(MAPPINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def save_mapping(
    benchmark_id: str,
    real_task_id: str,
    agent: str,
    status: str = "dispatched",
) -> None:
    """Record the link between a benchmark and a real AgentForge task."""
    mappings = _load_mappings()
    mappings[benchmark_id] = {
        "real_task_id": real_task_id,
        "agent": agent,
        "status": status,
        "dispatched_at": datetime.utcnow().isoformat() + "Z",
        "updated_at": datetime.utcnow().isoformat() + "Z",
    }
    _save_mappings(mappings)
    print(f"[Mappings] Saved link: {benchmark_id} → {real_task_id}")


def update_status(benchmark_id: str, status: str, extra: Optional[Dict] = None) -> None:
    """Update the status of an existing mapping."""
    mappings = _load_mappings()
    if benchmark_id not in mappings:
        return
    mappings[benchmark_id]["status"] = status
    mappings[benchmark_id]["updated_at"] = datetime.utcnow().isoformat() + "Z"
    if extra:
        mappings[benchmark_id].update(extra)
    _save_mappings(mappings)


def get_mapping(benchmark_id: str) -> Optional[Dict[str, Any]]:
    """Get the mapping for a specific benchmark."""
    return _load_mappings().get(benchmark_id)


def get_all_mappings() -> Dict[str, Dict[str, Any]]:
    return _load_mappings()


def get_real_task_id(benchmark_id: str) -> Optional[str]:
    mapping = get_mapping(benchmark_id)
    return mapping["real_task_id"] if mapping else None