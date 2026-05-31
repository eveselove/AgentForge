"""
Trajectory logging utilities.

Goal (Phase 1+): Capture rich, structured traces of every agent decision,
tool call, observation, and reasoning step.

This file is a placeholder that will become much more sophisticated.
"""
import json
import time
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


class TrajectoryLogger:
    """
    Structured logger for agent trajectories.

    In Phase 0 this is very simple.
    In Phase 1+ it will support:
    - Hierarchical steps
    - LLM call metadata (model, tokens, cost, latency)
    - Tool call + result
    - Reasoning traces
    - State snapshots
    """

    def __init__(self, task_id: str, agent: str, output_dir: Optional[Path] = None):
        """output_dir defaults to package-local trajectories/ (overridable, respects env)."""
        if output_dir is None:
            default_dir = Path(
                os.environ.get(
                    "AGENTFORGE_EVAL_TRAJECTORIES_DIR",
                    str(Path(__file__).parent / "trajectories"),
                )
            )
            output_dir = default_dir
        self.task_id = task_id
        self.agent = agent
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.events: List[Dict[str, Any]] = []
        self.start_time = time.time()

    def log(self, event_type: str, data: Dict[str, Any]):
        event = {
            "ts": datetime.utcnow().isoformat(),
            "type": event_type,
            **data
        }
        self.events.append(event)

    def log_llm_call(self, prompt: str, response: str, model: str, tokens_in: int, tokens_out: int, cost: float = 0.0):
        self.log("llm_call", {
            "model": model,
            "prompt_preview": prompt[:300],
            "response_preview": response[:300],
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost_usd": cost,
        })

    def log_tool_call(self, tool: str, args: Dict[str, Any], result: Any, duration_ms: float):
        self.log("tool_call", {
            "tool": tool,
            "args": args,
            "result_preview": str(result)[:500] if result else None,
            "duration_ms": duration_ms,
        })

    def log_reasoning(self, thought: str):
        self.log("reasoning", {"thought": thought})

    def save(self) -> Path:
        duration = time.time() - self.start_time
        payload = {
            "task_id": self.task_id,
            "agent": self.agent,
            "duration_seconds": duration,
            "events": self.events,
        }

        filename = f"{self.task_id}_{self.agent}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
        path = self.output_dir / filename

        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)

        return path


# Convenience function for future use
def get_trajectory_logger(task_id: str, agent: str) -> TrajectoryLogger:
    return TrajectoryLogger(task_id, agent)


# =============================================================================
# Unified robust trajectory loader (Phase 1 MVP) 
# =============================================================================

import re
from dataclasses import asdict
from typing import Union

__all__ = ["TrajectoryLogger", "get_trajectory_logger", "load_trajectory", "normalize_event", "find_trajectory_file"]


def _get_trajectories_dir() -> Path:
    return Path(
        os.environ.get(
            "AGENTFORGE_EVAL_TRAJECTORIES_DIR",
            str(Path(__file__).parent / "trajectories"),
        )
    )


def _apply_malformed_fix(line: str) -> str:
    if ',"{' in line or ',{' in line:
        idx = line.rfind(',{')
        if idx != -1 and '"data":' not in line[:idx + 20]:
            return line[:idx] + ',"data":' + line[idx + 1:]
    return line


def _extract_json_objects(text: str) -> list[str]:
    """Brace-counting extractor tolerant of embedded newlines in log values and printf malformations."""
    candidates: list[str] = []
    starts = [m.start() for m in re.finditer(r'\{"ts":\s*"', text)]
    if not starts:
        starts = [m.start() for m in re.finditer(r'\{"(?:(?:ts|type|task_id|agent))"', text)]
    for start in starts:
        depth = 0
        in_string = False
        escape = False
        for i, ch in enumerate(text[start:], start):
            if escape:
                escape = False
                continue
            if ch == '\\':
                escape = True
                continue
            if ch == '"' and not escape:
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    candidates.append(text[start:i+1])
                    break
    return candidates


def _parse_single_event(raw: str) -> Optional[Dict[str, Any]]:
    raw = raw.strip()
    if not raw:
        return None
    for att in (raw, _apply_malformed_fix(raw)):
        try:
            return json.loads(att)
        except Exception:
            continue
    return None


def normalize_event(raw_event: Dict[str, Any]) -> Dict[str, Any]:
    """Force every event dict into the clean canonical shape used by Phase 1: {"ts", "type", "data": {...}}."""
    if not isinstance(raw_event, dict):
        return {"ts": "", "type": "unknown", "data": {}}
    ev = dict(raw_event)
    ts = ev.pop("ts", None) or ev.pop("timestamp", None) or ""
    etype = ev.pop("type", None) or ev.pop("event_type", None) or "unknown"
    data: Dict[str, Any] = {}
    if isinstance(ev.get("data"), dict):
        data.update(ev.pop("data"))
    for k in list(ev.keys()):
        if k not in ("task_id", "agent"):
            data[k] = ev.pop(k)
    for common in ("model", "tokens_in", "tokens_out", "cost_usd", "tool", "duration_ms",
                   "prompt_preview", "response_preview", "result_preview", "thought",
                   "step", "path", "query_length", "feedback_count", "status",
                   "duration_seconds", "worktree", "skill", "prompt_length", "ci_result"):
        if common in ev:
            data.setdefault(common, ev.pop(common))
    norm: Dict[str, Any] = {"ts": ts, "type": etype, "data": data}
    if "task_id" in raw_event: norm["task_id"] = raw_event["task_id"]
    if "agent" in raw_event: norm["agent"] = raw_event["agent"]
    return norm


def _load_from_file(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Trajectory file not found: {path}")
    text = path.read_text(encoding="utf-8", errors="replace")

    if path.suffix.lower() == ".json":
        try:
            payload = json.loads(text)
            if isinstance(payload, dict):
                payload["_source_file"] = str(path)
                return payload
        except Exception:
            pass

    events_raw: List[Dict[str, Any]] = []
    for line in text.splitlines():
        ev = _parse_single_event(line)
        if ev:
            events_raw.append(ev)
    if len(events_raw) < 2:
        for obj_str in _extract_json_objects(text):
            ev = _parse_single_event(obj_str)
            if ev:
                events_raw.append(ev)

    seen = set()
    unique: List[Dict[str, Any]] = []
    for e in events_raw:
        key = (e.get("ts"), e.get("type"), str(e.get("data", {}))[:60])
        if key not in seen:
            seen.add(key)
            unique.append(e)

    task_id = agent = None
    for e in unique:
        task_id = task_id or e.get("task_id") or (e.get("data") or {}).get("task_id")
        agent = agent or e.get("agent") or (e.get("data") or {}).get("agent")
        if task_id and agent:
            break
    if not task_id:
        parts = path.stem.split("_")
        task_id = parts[0] if parts else "unknown"
    if not agent and len(path.stem.split("_")) > 1:
        agent = path.stem.split("_")[1]

    payload: Dict[str, Any] = {"task_id": task_id or "unknown", "agent": agent or "unknown",
                               "events": unique, "_source_file": str(path)}
    try:
        durs = [d for d in ((e.get("duration_seconds") or (e.get("data") or {}).get("duration_seconds")) for e in unique)
                if isinstance(d, (int, float))]
        if durs:
            payload["duration_seconds"] = max(durs)
    except Exception:
        pass
    return payload


def load_trajectory(
    source: Union[str, Path, Dict[str, Any], None] = None,
    *,
    include_prm: bool = False,
    trajectories_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    **The** canonical robust loader for AgentForge trajectories (Phase 1 foundation).

    Accepts:
      - str or Path to a .json (Python TrajectoryLogger) or .jsonl (bash)
      - partial task_id (e.g. "f12a11c0" or "adaptive_throttle_tuning") — does glob match
      - pre-loaded dict (normalizes its events)
      - None → returns the newest file in the trajectories dir

    Guarantees:
      - events always list of {"ts": , "type": , "data": {payload...}}
      - top level has task_id, agent, duration_seconds (best-effort), source
      - include_prm=True attaches "prm_result" (serializable)

    This is now the single source of truth. PRM, viewer, export, analyze, runner integration
    should all go through load_trajectory.
    """
    if trajectories_dir is None:
        trajectories_dir = _get_trajectories_dir()

    if isinstance(source, dict):
        traj = dict(source)
        traj["events"] = [normalize_event(e) for e in traj.get("events", [])]
        traj.setdefault("task_id", "unknown")
        traj.setdefault("agent", "unknown")
        traj["source"] = traj.get("_source_file", "<dict>")
        if include_prm:
            traj["prm_result"] = _compute_prm_for_traj(traj)  # auto-respects LLM judge env
        return traj

    if source is None:
        cands = sorted(
            list(trajectories_dir.glob("*.json")) + list(trajectories_dir.glob("*.jsonl")),
            key=lambda p: p.stat().st_mtime, reverse=True
        )
        if not cands:
            raise FileNotFoundError(f"No trajectory files found in {trajectories_dir}")
        path = cands[0]
    else:
        p = Path(str(source))
        if p.exists():
            path = p
        else:
            tid = str(source)
            cands = list(trajectories_dir.glob("*.json")) + list(trajectories_dir.glob("*.jsonl"))
            matches = [c for c in cands if tid in c.name or tid in c.stem]
            if not matches:
                raise FileNotFoundError(f"No trajectory matching id '{tid}' in {trajectories_dir}")
            matches.sort(key=lambda c: (0 if tid in c.name else 1, -c.stat().st_mtime))
            path = matches[0]

    raw = _load_from_file(path)
    raw["events"] = [normalize_event(e) for e in raw.get("events", [])]
    raw["source"] = str(path)

    if raw.get("duration_seconds") in (None, 0, ""):
        try:
            from datetime import datetime as dt
            tss = [e.get("ts") for e in raw["events"] if e.get("ts")]
            if len(tss) >= 2:
                def _p(ts: str):
                    return dt.fromisoformat(ts.replace("Z", "+00:00").replace(" ", "T"))
                raw["duration_seconds"] = round((_p(tss[-1]) - _p(tss[0])).total_seconds(), 1)
        except Exception:
            pass

    if include_prm:
        raw["prm_result"] = _compute_prm_for_traj(raw)  # auto-respects LLM judge env

    return raw


def _compute_prm_for_traj(traj: Dict[str, Any], use_llm_judge: Optional[bool] = None) -> Optional[Dict[str, Any]]:
    """Lazy to avoid import-time cycles. Respects AGENTFORGE_PRM_USE_LLM_JUDGE when not explicit."""
    try:
        from .prm import ProcessRewardModel
        if use_llm_judge is None:
            envv = os.environ.get("AGENTFORGE_PRM_USE_LLM_JUDGE", os.environ.get("AGENTFORGE_PRM_LLM_JUDGE", "0"))
            use_llm_judge = str(envv).lower() in ("1", "true", "yes", "on")
        prm = ProcessRewardModel(use_llm_judge=bool(use_llm_judge))
        res = prm.score_trajectory(traj)
        d = asdict(res)
        if getattr(prm, "_llm_judge_used", False):
            d["_llm_judge_used"] = True
        return d
    except Exception as e:
        return {"error": str(e)}


def find_trajectory_file(task_id: str, trajectories_dir: Optional[Path] = None) -> Optional[Path]:
    """Reusable by export, runner post-processing, etc."""
    if trajectories_dir is None:
        trajectories_dir = _get_trajectories_dir()
    cands = list(trajectories_dir.glob("*.json")) + list(trajectories_dir.glob("*.jsonl"))
    matches = [c for c in cands if task_id in c.name or task_id in c.stem]
    if not matches:
        return None
    matches.sort(key=lambda c: (0 if task_id in c.name else 1, -c.stat().st_mtime))
    return matches[0]
