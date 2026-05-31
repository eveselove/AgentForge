"""
Process Reward Model (PRM) for AgentForge.

Phase 1 component.

Goal:
- Score the quality of individual steps / decisions inside an agent trajectory,
  not just the final outcome.
- This enables much better training signals than outcome-only rewards.

Current implementation: Hybrid approach
- Rule-based heuristics (fast, always available)
- REAL LLM-as-Judge (when use_llm_judge=True or AGENTFORGE_PRM_USE_LLM_JUDGE=1):
  Uses the existing `grok` CLI infrastructure for a single batched structured judgment
  over the trajectory events. Produces scores + reasons + suggestions that blend with
  heuristics. Non-breaking, configurable, graceful fallback on any error/timeout.

Future: Fine-tuned small model (e.g. 7B-14B) trained on our own exported pairs + human labels.
"""

from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Union
import json
import os
import subprocess
from pathlib import Path


@dataclass
class StepScore:
    """Score for a single step in a trajectory."""
    step_index: int
    event_type: str
    score: float              # 0.0 - 1.0
    confidence: float         # 0.0 - 1.0
    reasons: List[str]
    raw_event: Dict[str, Any]


@dataclass
class TrajectoryPRMResult:
    """Full PRM evaluation of a trajectory."""
    task_id: str
    agent: str
    overall_prm_score: float          # Aggregated quality of the process
    step_scores: List[StepScore]
    num_steps: int
    num_high_quality_steps: int
    num_low_quality_steps: int
    suggestions_for_improvement: List[str]


class ProcessRewardModel:
    """
    Scores trajectories at the step level.

    This is one of the most important missing pieces for moving from
    "we can evaluate" to "we can learn effectively".
    """

    def __init__(self, use_llm_judge: bool = False, judge_model: str = "grok"):
        # Auto-enable via env for easy real-run activation (non-breaking default=False)
        env_flag = os.getenv("AGENTFORGE_PRM_USE_LLM_JUDGE", os.getenv("AGENTFORGE_PRM_LLM_JUDGE", "0"))
        if str(env_flag).lower() in ("1", "true", "yes", "on"):
            use_llm_judge = True
        self.use_llm_judge = use_llm_judge
        self.judge_model = judge_model
        self._llm_judge_used = False  # for introspection / logging

    def score_trajectory(self, trajectory: Union[Dict[str, Any], str, Path]) -> TrajectoryPRMResult:
        """
        Main entry point. Now accepts:
          - normalized (or raw) trajectory dict
          - path (str or Path) to .json / .jsonl  → uses the canonical robust loader

        This makes PRM work reliably on real (sometimes malformed) artifacts.
        """
        # Lazy import to avoid cycles at import time (loader lives in same package)
        if isinstance(trajectory, (str, Path)):
            from .trajectory import load_trajectory
            traj = load_trajectory(trajectory, include_prm=False)
        elif isinstance(trajectory, dict):
            from .trajectory import load_trajectory
            traj = load_trajectory(trajectory, include_prm=False)  # normalizes events
        else:
            traj = {"task_id": "unknown", "agent": "unknown", "events": []}

        events = traj.get("events", [])
        task_id = traj.get("task_id", "unknown")
        agent = traj.get("agent", "unknown")

        step_scores: List[StepScore] = []
        overall = None
        suggestions = None
        high_quality = 0
        low_quality = 0

        for i, event in enumerate(events):
            score = self._score_single_event(event, i, events)
            step_scores.append(score)

        # === LLM-as-Judge augmentation (real capability when enabled) ===
        llm_blob = None
        if self.use_llm_judge:
            try:
                llm_blob = self._apply_llm_judge(events, task_id, agent)
                if llm_blob:
                    self._llm_judge_used = True
                    # Blend: prefer LLM scores + reasons where provided; keep heuristic coverage
                    llm_by_idx = {s["step_index"]: s for s in llm_blob.get("step_scores", []) if isinstance(s, dict)}
                    for sc in step_scores:
                        if sc.step_index in llm_by_idx:
                            lj = llm_by_idx[sc.step_index]
                            sc.score = round(float(lj.get("score", sc.score)), 3)
                            if lj.get("reasons"):
                                sc.reasons = lj["reasons"][:4] + ["[LLM-JUDGE]"]
                            sc.confidence = max(sc.confidence, float(lj.get("confidence", 0.65)))
                    # Use LLM overall + suggestions when available (higher authority)
                    if "overall_prm_score" in llm_blob:
                        overall = llm_blob["overall_prm_score"]
                    if llm_blob.get("suggestions_for_improvement"):
                        suggestions = llm_blob["suggestions_for_improvement"]
                    high_quality = sum(1 for s in step_scores if s.score >= 0.75)
                    low_quality = sum(1 for s in step_scores if s.score < 0.4)
            except Exception:
                pass  # never break on judge failure

        # Aggregate (heuristic path, or already overridden by LLM above)
        if "overall" not in locals() or overall is None:
            if step_scores:
                overall = sum(s.score for s in step_scores) / len(step_scores)
                high_quality = sum(1 for s in step_scores if s.score >= 0.75)
                low_quality = sum(1 for s in step_scores if s.score < 0.4)
            else:
                overall = 0.0
                high_quality = 0
                low_quality = 0

        if "suggestions" not in locals() or suggestions is None:
            suggestions = self._generate_suggestions(step_scores)

        return TrajectoryPRMResult(
            task_id=task_id,
            agent=agent,
            overall_prm_score=round(overall, 3),
            step_scores=step_scores,
            num_steps=len(step_scores),
            num_high_quality_steps=high_quality,
            num_low_quality_steps=low_quality,
            suggestions_for_improvement=suggestions,
        )

    def _score_single_event(self, event: Dict[str, Any], index: int, all_events: List[Dict]) -> StepScore:
        """Score one event using heuristics (+ optional LLM later).

        Transparent to both legacy flat events and the new normalized shape
        {"ts", "type", "data": {...}} produced by load_trajectory.
        """
        # Support normalized shape
        payload = event.get("data", {}) if isinstance(event.get("data"), dict) else {}
        def _get(key, default=0):
            return event.get(key, payload.get(key, default))

        event_type = event.get("type") or payload.get("type", "unknown")
        reasons = []
        base_score = 0.6

        # === Heuristic rules (very useful already) ===

        if event_type == "llm_call":
            tokens_in = _get("tokens_in", 0)
            tokens_out = _get("tokens_out", 0)
            cost = _get("cost_usd", 0.0)

            # Penalize very long useless outputs
            if tokens_out > 4000 and tokens_in < 200:
                base_score -= 0.25
                reasons.append("Very long output with little input context")

            # Reward good token efficiency
            if 200 < tokens_out < 1200:
                base_score += 0.15
                reasons.append("Reasonable output length")

            if cost > 0.05:
                base_score -= 0.1
                reasons.append("Expensive call")

        elif event_type == "tool_call":
            duration = _get("duration_ms", 0)
            result = _get("result_preview", "") or ""

            if duration > 30000:  # 30 seconds
                base_score -= 0.2
                reasons.append("Very slow tool call")

            if "error" in result.lower() or "failed" in result.lower():
                base_score -= 0.3
                reasons.append("Tool call returned error/failure")

            if "success" in result.lower() or len(result) > 100:
                base_score += 0.2
                reasons.append("Tool produced substantial output")

            # Recovery signal (very important for learning)
            if "retry" in str(_get("args", {})).lower() or "recover" in result.lower():
                base_score += 0.15
                reasons.append("Recovery/retry behavior observed")

        elif event_type == "reasoning":
            thought = _get("thought", "")
            if len(thought) < 30:
                base_score -= 0.15
                reasons.append("Very short reasoning step")
            elif len(thought) > 200:
                base_score += 0.1
                reasons.append("Detailed reasoning")

        elif event_type in ("infra_step", "worktree_created", "rag_context"):
            # Infrastructure steps are usually neutral-positive if they succeed
            base_score = 0.65
            reasons.append("Standard infrastructure step")

        elif event_type == "hitl_feedback":
            # Human feedback is very valuable signal
            base_score = 0.85
            reasons.append("Human-in-the-loop feedback present")

        # Clamp
        final_score = max(0.0, min(1.0, base_score))

        return StepScore(
            step_index=index,
            event_type=event_type,
            score=round(final_score, 3),
            confidence=0.65,  # Heuristic confidence
            reasons=reasons,
            raw_event=event,
        )

    def _generate_suggestions(self, step_scores: List[StepScore]) -> List[str]:
        suggestions = []

        low_quality_steps = [s for s in step_scores if s.score < 0.4]
        if len(low_quality_steps) >= 3:
            suggestions.append(
                f"High number of low-quality steps ({len(low_quality_steps)}). "
                "Consider adding more structured reasoning or better tool selection."
            )

        llm_calls = [s for s in step_scores if s.event_type == "llm_call"]
        if llm_calls:
            def _tok(s):
                p = s.raw_event.get("data", {}) if isinstance(s.raw_event.get("data"), dict) else s.raw_event
                return p.get("tokens_out", 0) or s.raw_event.get("tokens_out", 0)
            avg_tokens = sum(_tok(s) for s in llm_calls) / len(llm_calls)
            if avg_tokens > 2500:
                suggestions.append(
                    "Agent is producing very long LLM responses on average. "
                    "May benefit from stronger output formatting or step decomposition."
                )

        error_steps = [s for s in step_scores if "error" in str(s.raw_event).lower()]
        if len(error_steps) > 2:
            suggestions.append(
                "Multiple steps contain errors. Strong signal to improve error recovery or pre-validation."
            )

        if not suggestions:
            suggestions.append("Trajectory process quality looks reasonable.")

        return suggestions

    # =====================================================================
    # NEW: Basic working LLM-as-Judge (Phase 1 completion)
    # =====================================================================

    def _invoke_grok_judge(self, prompt: str, timeout_s: int = 55) -> Optional[Dict[str, Any]]:
        """Call existing grok infrastructure (CLI) for structured judgment.
        Non-interactive, always-approve, captures final JSON response.
        Returns parsed dict or None on any failure (caller falls back).
        """
        if not prompt or len(prompt) < 10:
            return None
        pid = os.getpid()
        tmp_prompt = f"/tmp/prm_judge_prompt_{pid}.txt"
        tmp_out = f"/tmp/prm_judge_out_{pid}.log"
        try:
            # Write prompt safely (heredoc avoids shell escaping nightmares for long JSON+instructions)
            with open(tmp_prompt, "w", encoding="utf-8") as f:
                f.write(prompt)

            # Invoke grok headless. Use bash wrapper so -p gets the full content.
            # We deliberately keep timeout tight and truncate insane prompts.
            safe_prompt_path = tmp_prompt
            bash_cmd = (
                f'cat > /tmp/prm_judge_{pid}.sh << "JSH"\n'
                f'#!/bin/bash\n'
                f'PROMPT_CONTENT=$(cat "{safe_prompt_path}" | head -c 24000)\n'
                f'grok --always-approve -p "$PROMPT_CONTENT" 2>&1 | tee "{tmp_out}"\n'
                f'JSH\n'
                f'bash /tmp/prm_judge_{pid}.sh'
            )
            result = subprocess.run(
                ["bash", "-c", bash_cmd],
                capture_output=True,
                text=True,
                timeout=timeout_s,
                env={**os.environ, "GROK_FLAGS": "--always-approve"},  # hint only
            )
            raw = (result.stdout or "") + (result.stderr or "")
            if os.path.exists(tmp_out):
                raw += "\n" + open(tmp_out, encoding="utf-8", errors="ignore").read()

            # Robust JSON extraction from potentially chatty agent output
            json_candidates = []
            depth = 0
            start = -1
            for i, ch in enumerate(raw):
                if ch == "{":
                    if depth == 0:
                        start = i
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0 and start != -1:
                        cand = raw[start : i + 1]
                        json_candidates.append(cand)
                        start = -1

            for cand in reversed(json_candidates):  # prefer last complete JSON
                try:
                    parsed = json.loads(cand)
                    if isinstance(parsed, dict) and ("overall" in parsed or "overall_prm_score" in parsed or "step_scores" in parsed):
                        return parsed
                except Exception:
                    continue

            # Fallback: sometimes the model emits ```json ... ```
            import re
            m = re.search(r"```json\s*(\{.*?\})\s*```", raw, re.DOTALL | re.IGNORECASE)
            if m:
                try:
                    return json.loads(m.group(1))
                except Exception:
                    pass

            return None
        except subprocess.TimeoutExpired:
            return {"_error": "judge_timeout"}
        except Exception as e:
            return {"_error": f"judge_exception:{str(e)[:120]}"}
        finally:
            for p in (tmp_prompt, tmp_out, f"/tmp/prm_judge_{pid}.sh"):
                try:
                    if os.path.exists(p):
                        os.unlink(p)
                except Exception:
                    pass

    def _build_judge_prompt(self, events: List[Dict[str, Any]], task_id: str, agent: str) -> str:
        """Compact but rich summary for a single efficient LLM judge call."""
        compact_events = []
        for i, ev in enumerate(events[:80]):  # cap for cost/latency
            et = ev.get("type") or (ev.get("data", {}) or {}).get("type", "unknown")
            d = ev.get("data", ev) if isinstance(ev.get("data"), dict) else {}
            preview = ""
            for k in ("thought", "tool", "result_preview", "rationale", "summary", "decision", "focus"):
                if d.get(k):
                    preview = str(d.get(k))[:220]
                    break
            if not preview:
                preview = str({kk: d.get(kk) for kk in list(d.keys())[:3]})[:180]
            compact_events.append({"i": i, "t": et, "p": preview})

        summary = json.dumps(compact_events, ensure_ascii=False)
        return f"""You are an expert Process Reward Model (PRM) judge for coding agents.

Task: {task_id}   Agent: {agent}

Below is a compact event stream from a real agent trajectory (types + short previews of reasoning/tool/decision/error steps).

Your job: score PROCESS QUALITY (not final outcome). Focus on:
- Soundness and detail of reasoning
- Appropriateness and efficiency of tool choices + follow-through
- Quality of error detection + recovery behavior
- Decision transparency and rationale
- Progress velocity vs wasted steps

Return ONLY one valid minified JSON object (no markdown, no extra text):

{{
  "overall_prm_score": 0.0-1.0 (average process quality),
  "step_scores": [   // one entry per interesting step (you choose which; at least 5-12)
    {{"index": 0, "score": 0.82, "reasons": ["detailed reasoning present", "good tool choice"], "confidence": 0.7}},
    ...
  ],
  "suggestions_for_improvement": ["...", "..."],
  "num_high_quality_steps": <int>,
  "num_low_quality_steps": <int>
}}

Events (JSON array of {{i, t=type, p=preview}}):
{summary}

Judge strictly but fairly. Output the JSON now."""

    def _apply_llm_judge(self, events: List[Dict[str, Any]], task_id: str, agent: str) -> Optional[Dict[str, Any]]:
        """Run LLM judge and return normalized result dict compatible with TrajectoryPRMResult fields."""
        if not self.use_llm_judge:
            return None
        prompt = self._build_judge_prompt(events, task_id, agent)
        raw_j = self._invoke_grok_judge(prompt)
        if not raw_j or raw_j.get("_error"):
            return None

        # Normalize keys (model may use slight variants)
        overall = float(raw_j.get("overall_prm_score") or raw_j.get("overall") or 0.5)
        step_scores_raw = raw_j.get("step_scores") or raw_j.get("steps") or []
        suggestions = raw_j.get("suggestions_for_improvement") or raw_j.get("suggestions") or []

        norm_steps = []
        for s in step_scores_raw:
            if not isinstance(s, dict):
                continue
            idx = int(s.get("index", s.get("step_index", -1)))
            norm_steps.append({
                "step_index": idx,
                "score": max(0.0, min(1.0, float(s.get("score", 0.5)))),
                "reasons": s.get("reasons", []) or [str(s.get("reason", "LLM judged"))],
                "confidence": max(0.0, min(1.0, float(s.get("confidence", 0.6)))),
            })

        high = sum(1 for s in norm_steps if s["score"] >= 0.75)
        low = sum(1 for s in norm_steps if s["score"] < 0.4)

        return {
            "overall_prm_score": round(overall, 3),
            "step_scores": norm_steps,
            "num_steps": len(events),
            "num_high_quality_steps": high,
            "num_low_quality_steps": low,
            "suggestions_for_improvement": suggestions[:6],
            "_source": "llm_judge",
        }

# Convenience function (now uses the robust loader under the hood)
def score_trajectory_file(path: str) -> TrajectoryPRMResult:
    prm = ProcessRewardModel()
    return prm.score_trajectory(path)  # str/Path → load_trajectory inside
