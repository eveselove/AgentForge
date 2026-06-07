#!/usr/bin/env python3
"""
Trajectory Viewer & Summarizer for AgentForge (Phase 1 MVP).

Provides:
- summarize(trajectory) -> rich multi-line text report with PRM scores inline
- generate_html(...) -> beautiful self-contained offline HTML (timeline + PRM heatmap + JS filters)
- CLI: python -m agentforge.eval view <task_id_or_file> [--html] [--prm] [--output HTML_PATH]

This is the Langfuse-style replay tool specialized for coding-agent trajectories.
Zero external dependencies. Works on both normalized and raw trajectories.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import html as html_escape


# --- Public API -----------------------------------------------------------------

def summarize(
    trajectory: Dict[str, Any],
    prm_result: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Produce a human-readable rich text summary of a (normalized) trajectory.

    If prm_result is None and the trajectory contains "prm_result", it will be used.
    """
    if prm_result is None:
        prm_result = trajectory.get("prm_result")

    task_id = trajectory.get("task_id", "unknown")
    agent = trajectory.get("agent", "unknown")
    duration = trajectory.get("duration_seconds")
    events = trajectory.get("events", []) or []
    source = trajectory.get("source", "<unknown>")

    lines: List[str] = []
    lines.append("=" * 78)
    lines.append(f"AgentForge Trajectory View — {task_id} ({agent})")
    if duration:
        lines.append(f"Duration: {duration:.1f}s   |   Events: {len(events)}   |   Source: {source}")
    else:
        lines.append(f"Events: {len(events)}   |   Source: {source}")
    lines.append("=" * 78)

    # PRM summary block if present
    if prm_result and not prm_result.get("error"):
        overall = prm_result.get("overall_prm_score", 0.0)
        hi = prm_result.get("num_high_quality_steps", 0)
        lo = prm_result.get("num_low_quality_steps", 0)
        judge_tag = " [LLM-JUDGE]" if prm_result.get("_llm_judge_used") or prm_result.get("_source") == "llm_judge" else ""
        lines.append(f"\nProcess Quality (PRM): {overall:.3f}{judge_tag}   |   High-quality steps: {hi}   Low-quality: {lo}")
        suggs = prm_result.get("suggestions_for_improvement", [])
        if suggs:
            lines.append("Suggestions:")
            for s in suggs:
                lines.append(f"  • {s}")
        lines.append("")

    # Timeline
    lines.append("STEP TIMELINE (ts | type | PRM | preview)")
    lines.append("-" * 78)

    step_scores_by_idx: Dict[int, Dict[str, Any]] = {}
    if prm_result and prm_result.get("step_scores"):
        for ss in prm_result["step_scores"]:
            step_scores_by_idx[ss.get("step_index", -1)] = ss

    for idx, ev in enumerate(events):
        ts = ev.get("ts", "")[:19].replace("T", " ")
        etype = ev.get("type", "unknown")
        data = ev.get("data", {}) or ev  # tolerant

        prm_score = None
        reasons = ""
        ss = step_scores_by_idx.get(idx)
        if ss:
            prm_score = ss.get("score")
            reasons = " | ".join(ss.get("reasons", []))[:80]

        preview = ""
        # Heuristic nice preview
        for k in ("title", "step", "thought", "tool", "status", "model"):
            v = data.get(k)
            if v:
                preview = str(v)[:70]
                break
        if not preview:
            for k in ("prompt_preview", "response_preview", "result_preview"):
                v = data.get(k)
                if v:
                    preview = str(v)[:70]
                    break

        score_str = f"{prm_score:.2f}" if prm_score is not None else "    "
        flag = ""
        if prm_score is not None:
            if prm_score < 0.4:
                flag = " 🔴"
            elif prm_score >= 0.75:
                flag = " 🟢"

        line = f"[{idx:03d}] {ts} | {etype:20} | {score_str}{flag}"
        if reasons:
            line += f"   ({reasons})"
        if preview:
            line += f"\n      → {preview}"
        lines.append(line)

    # Red flags summary
    low_quality = [s for s in step_scores_by_idx.values() if s.get("score", 1.0) < 0.4]
    if low_quality:
        lines.append("\n" + "-" * 78)
        lines.append(f"🔴 RED FLAGS — {len(low_quality)} low-quality steps")
        for ss in low_quality[:5]:
            lines.append(f"  Step {ss.get('step_index')}: {ss.get('event_type')} — {', '.join(ss.get('reasons', []))}")

    lines.append("=" * 78)
    lines.append("Use `python -m agentforge.eval view <id> --html` for interactive replay.")
    lines.append("=" * 78 + "\n")

    return "\n".join(lines)


def generate_html(
    trajectory: Dict[str, Any],
    output_path: Optional[Path] = None,
    include_prm: bool = True,
) -> Path:
    """
    Generate a beautiful, completely self-contained single-file HTML report
    (timeline, PRM heatmap, type filters, score slider, search).

    Returns the Path to the written HTML file.
    """
    if output_path is None:
        tid = trajectory.get("task_id", "traj")
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        output_path = Path(f"trajectory_{tid}_{ts}.html").absolute()
    else:
        output_path = Path(output_path)

    prm = trajectory.get("prm_result") if include_prm else None
    if not prm and include_prm:
        # Try to compute on the fly (uses loader under the hood via PRM)
        try:
            from .prm import ProcessRewardModel
            prm = ProcessRewardModel().score_trajectory(trajectory)
            if hasattr(prm, "__dataclass_fields__"):
                from dataclasses import asdict
                prm = asdict(prm)
        except Exception:
            prm = None

    events = trajectory.get("events", []) or []
    task_id = trajectory.get("task_id", "unknown")
    agent = trajectory.get("agent", "?")
    duration = trajectory.get("duration_seconds", "?")

    # Build step scores lookup
    step_scores: List[Dict[str, Any]] = (prm or {}).get("step_scores", []) if prm else []
    score_map = {s.get("step_index"): s for s in step_scores}

    # Serialize data for the inline JS
    events_json = json.dumps([
        {
            "idx": i,
            "ts": e.get("ts", ""),
            "type": e.get("type", "unknown"),
            "data": e.get("data", e),
            "score": score_map.get(i, {}).get("score"),
            "reasons": score_map.get(i, {}).get("reasons", []),
        }
        for i, e in enumerate(events)
    ], ensure_ascii=False)

    prm_json = json.dumps(prm or {}, ensure_ascii=False)

    # --- HTML generation (pure, nice, functional) ---
    title = f"Trajectory {task_id} — {agent}"
    overall = (prm or {}).get("overall_prm_score", 0.0) if prm else None

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{html_escape.escape(title)}</title>
<style>
:root {{ --bg:#0f172a; --card:#1e2937; --text:#e2e8f0; --accent:#22c55e; --red:#ef4444; --amber:#f59e0b; }}
body {{ background:var(--bg); color:var(--text); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; margin:0; padding:20px; line-height:1.5; }}
h1,h2 {{ color:#f1f5f9; }}
.container {{ max-width: 1100px; margin: 0 auto; }}
.card {{ background:var(--card); border-radius:12px; padding:16px 20px; margin-bottom:16px; box-shadow:0 10px 15px -3px rgb(0 0 0 / 0.3); }}
.header {{ display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px; }}
.meta {{ opacity:0.8; font-size:0.9rem; }}
.timeline {{ display:flex; flex-direction:column; gap:4px; }}
.step {{ display:flex; gap:12px; padding:8px 12px; border-radius:8px; background:#0f172a; border-left:4px solid #64748b; }}
.step.high {{ border-left-color:#22c55e; }}
.step.low {{ border-left-color:#ef4444; }}
.step .idx {{ width:42px; font-weight:700; color:#94a3b8; flex-shrink:0; }}
.step .ts {{ width:170px; color:#64748b; flex-shrink:0; font-size:0.85rem; }}
.step .type {{ font-family:ui-monospace; min-width:160px; color:#c0c7d1; }}
.step .score {{ font-weight:700; width:52px; text-align:right; }}
.step.high .score {{ color:#22c55e; }}
.step.low .score {{ color:#ef4444; }}
.step .preview {{ flex:1; opacity:0.9; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
.controls {{ display:flex; gap:12px; flex-wrap:wrap; align-items:center; margin:12px 0; }}
input[type="text"], select {{ background:#0f172a; color:#e2e8f0; border:1px solid #475569; padding:6px 10px; border-radius:6px; }}
input[type="range"] {{ accent-color:#22c55e; }}
button {{ background:#22c55e; color:#0f172a; border:none; padding:6px 14px; border-radius:6px; font-weight:600; cursor:pointer; }}
button.secondary {{ background:#475569; color:#e2e8f0; }}
#timeline {{ max-height:70vh; overflow:auto; padding-right:8px; }}
.badge {{ display:inline-block; padding:2px 8px; border-radius:999px; font-size:0.75rem; margin-left:6px; }}
.badge.green {{ background:#166534; color:#86efac; }}
.badge.red {{ background:#7f1d1d; color:#fda4af; }}
.badge.amber {{ background:#78350f; color:#fcd34d; }}
.stats {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(140px,1fr)); gap:12px; }}
.stat {{ background:#0f172a; padding:10px; border-radius:8px; }}
</style>
</head>
<body>
<div class="container">
  <div class="card">
    <div class="header">
      <div>
        <h1 style="margin:0 0 4px 0;">{html_escape.escape(title)}</h1>
        <div class="meta">AgentForge Phase 1 Trajectory Replay &nbsp;•&nbsp; {len(events)} steps &nbsp;•&nbsp; duration: {duration}s</div>
      </div>
      <div style="text-align:right;">
        {"<div class='badge green'>PRM overall: " + f"{overall:.3f}" + "</div>" if overall is not None else ""}
        <div style="font-size:0.8rem; opacity:0.6; margin-top:4px;">{html_escape.escape(str(trajectory.get('source','')))}</div>
      </div>
    </div>
  </div>

  <div class="card">
    <div class="controls">
      <input id="search" type="text" placeholder="Filter by text (type, thought, tool...)" style="width:260px" oninput="filterSteps()">
      <select id="typeFilter" onchange="filterSteps()">
        <option value="">All event types</option>
      </select>
      <label style="display:flex; align-items:center; gap:8px;">
        Min PRM score: <input id="minScore" type="range" min="0" max="1" step="0.05" value="0" oninput="filterSteps()">
        <span id="minScoreVal">0.00</span>
      </label>
      <button onclick="resetFilters()">Reset</button>
      <button class="secondary" onclick="downloadJSON()">Export JSON</button>
    </div>

    <div class="stats">
      <div class="stat"><strong>Events</strong><br><span style="font-size:1.4rem">{len(events)}</span></div>
      <div class="stat"><strong>High-quality steps</strong><br><span style="font-size:1.4rem; color:#22c55e">{(prm or {}).get('num_high_quality_steps', '—')}</span></div>
      <div class="stat"><strong>Low-quality steps</strong><br><span style="font-size:1.4rem; color:#ef4444">{(prm or {}).get('num_low_quality_steps', '—')}</span></div>
      <div class="stat"><strong>Process Score</strong><br><span style="font-size:1.4rem">{f"{overall:.3f}" if overall is not None else "—"}</span></div>
    </div>
  </div>

  <div class="card">
    <h2 style="margin-top:0;">Step Timeline &amp; PRM Heatmap</h2>
    <div id="timeline" class="timeline"></div>
  </div>

  <div class="card" style="font-size:0.85rem; opacity:0.8;">
    Generated by AgentForge <code>trajectory_viewer</code> • PRM scores are heuristic (0.0–1.0). 🟢 ≥0.75 &nbsp; 🔴 &lt;0.40
  </div>
</div>

<script>
const EVENTS = {events_json};
const PRM = {prm_json};

function escapeHtml(str) {{
  return String(str).replace(/[&<>"']/g, s => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[s]));
}}

function renderTimeline(filtered) {{
  const container = document.getElementById('timeline');
  container.innerHTML = '';
  if (!filtered.length) {{
    container.innerHTML = '<div style="padding:20px;opacity:0.6;">No steps match the current filters.</div>';
    return;
  }}
  const frag = document.createDocumentFragment();
  filtered.forEach(ev => {{
    const div = document.createElement('div');
    div.className = 'step';
    const sc = ev.score;
    if (sc != null) {{
      if (sc >= 0.75) div.classList.add('high');
      else if (sc < 0.4) div.classList.add('low');
    }}
    const scoreHtml = sc != null ? `<span class="score">${{sc.toFixed(2)}}</span>` : '<span class="score" style="opacity:0.4">—</span>';
    const preview = ev.data && (ev.data.thought || ev.data.title || ev.data.tool || ev.data.step || ev.data.prompt_preview || ev.data.result_preview || '');
    const reasons = (ev.reasons && ev.reasons.length) ? `<span style="color:#64748b;font-size:0.8rem"> — ${{escapeHtml(ev.reasons.join(' | '))}}</span>` : '';
    div.innerHTML = `
      <div class="idx">[${{String(ev.idx).padStart(3,'0')}}]</div>
      <div class="ts">${{escapeHtml((ev.ts||'').replace('T',' ').slice(0,19))}}</div>
      <div class="type">${{escapeHtml(ev.type)}}</div>
      ${{scoreHtml}}
      <div class="preview">${{escapeHtml(preview)}} ${{reasons}}</div>
    `;
    // Click to expand raw data
    div.onclick = () => {{
      const pre = document.createElement('pre');
      pre.style.cssText = 'background:#0f172a;padding:8px;margin:4px 0 12px;border-radius:6px;font-size:0.75rem;white-space:pre-wrap;';
      pre.textContent = JSON.stringify(ev.data || ev, null, 2);
      if (div.nextSibling && div.nextSibling.tagName === 'PRE') div.nextSibling.remove();
      else div.parentNode.insertBefore(pre, div.nextSibling);
    }};
    frag.appendChild(div);
  }});
  container.appendChild(frag);
}}

let currentFilter = {{}};

function filterSteps() {{
  const q = (document.getElementById('search').value || '').toLowerCase();
  const type = document.getElementById('typeFilter').value;
  const min = parseFloat(document.getElementById('minScore').value || '0');
  document.getElementById('minScoreVal').textContent = min.toFixed(2);

  const filtered = EVENTS.filter(ev => {{
    if (type && ev.type !== type) return false;
    if (ev.score != null && ev.score < min) return false;
    if (!q) return true;
    const hay = JSON.stringify(ev).toLowerCase();
    return hay.includes(q);
  }});
  renderTimeline(filtered);
}}

function resetFilters() {{
  document.getElementById('search').value = '';
  document.getElementById('typeFilter').value = '';
  document.getElementById('minScore').value = '0';
  document.getElementById('minScoreVal').textContent = '0.00';
  renderTimeline(EVENTS);
}}

function populateTypeFilter() {{
  const sel = document.getElementById('typeFilter');
  const types = [...new Set(EVENTS.map(e => e.type))].sort();
  types.forEach(t => {{
    const opt = document.createElement('option');
    opt.value = t;
    opt.textContent = t;
    sel.appendChild(opt);
  }});
}}

function downloadJSON() {{
  const blob = new Blob([JSON.stringify({{task_id: "{task_id}", agent: "{agent}", events: EVENTS, prm: PRM}}, null, 2)], {{type:'application/json'}});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `trajectory_{task_id}.json`;
  a.click();
}}

function init() {{
  populateTypeFilter();
  // initial render
  renderTimeline(EVENTS);
  // wire range label live
  const range = document.getElementById('minScore');
  range.oninput = () => {{
    document.getElementById('minScoreVal').textContent = parseFloat(range.value).toFixed(2);
  }};
  // keyboard nice-to-have
  document.addEventListener('keydown', e => {{
    if (e.key === '/' && document.activeElement.tagName === 'BODY') {{
      e.preventDefault();
      document.getElementById('search').focus();
    }}
  }});
}}
window.onload = init;
</script>
</body>
</html>
"""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html_content, encoding="utf-8")
    return output_path


# --- CLI entry -----------------------------------------------------------------

def main(argv: Optional[List[str]] = None):
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        prog="agentforge-eval view",
        description="View / replay a trajectory with optional PRM scores (text or beautiful self-contained HTML)"
    )
    parser.add_argument("task_or_file", help="Task ID (partial match) or path to .json/.jsonl trajectory")
    parser.add_argument("--html", action="store_true", help="Generate self-contained HTML replay instead of text")
    parser.add_argument("--prm", action="store_true", help="Include / compute Process Reward Model scores")
    parser.add_argument("--output", type=Path, help="Output path for HTML (default: trajectory_<id>_<ts>.html in cwd)")
    args = parser.parse_args(argv)

    # Use the canonical loader
    from .trajectory import load_trajectory

    traj = load_trajectory(args.task_or_file, include_prm=args.prm)

    if args.html:
        out = generate_html(traj, output_path=args.output, include_prm=args.prm)
        print(f"[viewer] HTML written → {out}")
        print(f"         Open it in any browser (fully offline).")
    else:
        prm = traj.get("prm_result") if args.prm else None
        print(summarize(traj, prm_result=prm))


if __name__ == "__main__":
    main()
