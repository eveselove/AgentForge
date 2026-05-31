"""
!!! AGGRESSIVE FINAL DEPRECATION SWEEP (RUST_FULL_MIGRATION_PLAN.md + PHASE4_REMOVAL_PLAN.md) !!!
!!! skill_improver.py (SkillImprover + propose_*) PYTHON FLYWHEEL ORCHESTRATION DEPRECATED !!!
PHASE 4 DELETION TARGET.
MIGRATE TO: agentforge-runner flywheel-step --real-data --ingest   (Rust native)

Guard EXCLUSIVELY with Phase 4 EVEN STRONGER central:
  from .utils import is_pure_rust_flywheel

Loud warnings on every Python path. Non-breaking !pure. Complete removal Phase 4.

See learning/utils.py (hardened guards + full remaining Python flywheel orchestration file list)
See PHASE4_REMOVAL_PLAN.md (safe phased removal + risks + rollback strategy)
"""

# MIGRATED / DEPRECATED: Full description moved to RUST_FULL_MIGRATION_PLAN.md + class docs below.
# All new flywheel logic lives in agentforge-runner (flywheel-step / SkillImprover parity in Rust).
# This file remains only for !is_pure_rust_flywheel() non-breaking fallback + deprecation warnings.
# See top banner + utils.is_pure_rust_flywheel() + runner --help for canonical usage.

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

import warnings

# Phase 0/3: central pure-Rust cutover detector (RUST_FULL_MIGRATION_PLAN.md) — STRENGTHENED
from .utils import is_pure_rust_flywheel

# Reuse our rich stack
try:
    from agentforge.eval.trajectory import load_trajectory
    from agentforge.eval.prm import ProcessRewardModel
except Exception:
    load_trajectory = None
    ProcessRewardModel = None

# Where production skills live
SKILLS_DIR = Path(os.environ.get("AGENTFORGE_SKILLS_DIR", str(Path(__file__).parent.parent / "skills")))


@dataclass
class ImprovementProposal:
    """One concrete, reviewable improvement to a skill."""
    section: str                 # "system_prompt", "few_shot", "verification", "recovery"
    original_snippet: str
    proposed_snippet: str
    rationale: str
    confidence: float            # 0-1
    source: str                  # "llm" | "heuristic" | "pattern_mining"


@dataclass
class ProposedSkill:
    """Full proposed new version of a skill."""
    original_skill_name: str
    proposed_name: str
    timestamp: str
    analysis: Dict[str, Any]               # failure modes, top low-PRM step types, etc.
    proposals: List[ImprovementProposal]
    new_system_prompt: Optional[str] = None
    suggested_few_shots: List[Dict[str, str]] = field(default_factory=list)
    suggested_ci_checks: List[str] = field(default_factory=list)
    overall_rationale: str = ""
    estimated_impact: str = "medium"       # low | medium | high

    def to_yaml(self) -> str:
        """Produce a ready-to-use YAML candidate (partial or full)."""
        base = {
            "name": self.proposed_name,
            "description": f"Auto-proposed improvement over {self.original_skill_name} at {self.timestamp}",
            "system_prompt": self.new_system_prompt or "",
            "required_tags": [],  # caller should merge
            "ci_checks": self.suggested_ci_checks,
            "few_shot_examples": self.suggested_few_shots,
            "_learning_meta": {
                "generated_by": "agentforge.learning.skill_improver",
                "source_skill": self.original_skill_name,
                "analysis": self.analysis,
                "impact": self.estimated_impact,
            },
        }
        return yaml.safe_dump(base, sort_keys=False, allow_unicode=True, width=120)

    def save_candidate_yaml(self, path: Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_yaml(), encoding="utf-8")
        print(f"[SkillImprover] Candidate saved → {path}")
        return path

    def diff_against_original(self, original_yaml_path: Optional[Path] = None) -> str:
        """Simple textual diff of the key changed sections."""
        orig_path = original_yaml_path or (SKILLS_DIR / f"{self.original_skill_name}.yaml")
        lines = [f"=== Proposed improvement for skill: {self.original_skill_name} ==="]
        lines.append(f"Generated: {self.timestamp}")
        lines.append(f"Overall rationale: {self.overall_rationale}")
        lines.append("")

        for p in self.proposals:
            lines.append(f"--- SECTION: {p.section} (confidence={p.confidence:.2f}, source={p.source})")
            lines.append(f"RATIONALE: {p.rationale}")
            lines.append("ORIGINAL (excerpt):")
            lines.append(p.original_snippet[:600] + ("..." if len(p.original_snippet) > 600 else ""))
            lines.append("PROPOSED:")
            lines.append(p.proposed_snippet[:800] + ("..." if len(p.proposed_snippet) > 800 else ""))
            lines.append("")
        return "\n".join(lines)


class SkillImprover:
    """
    The autonomous skill critic + rewriter.

    Uses failure trajectories (especially low-PRM steps) + successful counter-examples
    to generate targeted, high-leverage improvements.
    """

    def __init__(self, use_llm: bool = True, model: str = "grok"):
        self.use_llm = use_llm
        self.model = model
        self.prm = ProcessRewardModel(use_llm_judge=use_llm) if ProcessRewardModel else None

    def propose_improvements(
        self,
        skill_name: str,
        failure_trajectories: List[Union[str, Path, Dict[str, Any]]],
        success_trajectories: Optional[List[Union[str, Path, Dict[str, Any]]]] = None,
        min_prm_for_success: float = 0.68,
        max_failures: int = 12,
    ) -> ProposedSkill:
        """
        Main entry point. Returns a fully populated ProposedSkill ready for review or auto-testing.

        TODO(Phase 0, RUST_FULL_MIGRATION_PLAN.md): SkillImprover Python impl will be
        ported to agentforge-learning crate (RichImprover). Deprecation active.
        """
        if not is_pure_rust_flywheel():
            warnings.warn(
                "learning.skill_improver.SkillImprover (Python orchestration) is deprecated per "
                "RUST_FULL_MIGRATION_PLAN.md PHASE 3 FINAL SWEEP. "
                "Direct: agentforge-runner flywheel-step (Rust RichImprover). "
                "Python path only on !pure (non-breaking).",
                DeprecationWarning,
                stacklevel=2,
            )
        print(f"[SkillImprover] Analyzing failures for skill '{skill_name}' ({len(failure_trajectories)} trajectories)")

        # 1. Load + enrich all failures
        failures = []
        for t in failure_trajectories[:max_failures]:
            try:
                traj = self._load(t)
                failures.append(traj)
            except Exception as e:
                print(f"  [warn] failed to load one trajectory: {e}")

        # 2. Mine failure patterns (PRM is gold here)
        analysis = self._analyze_failures(failures)

        # 3. Mine positive examples from successes (for few-shot)
        good_examples = []
        if success_trajectories:
            for t in success_trajectories[:6]:
                try:
                    traj = self._load(t)
                    prm = traj.get("prm_result", {}).get("overall_prm_score", 0.5)
                    if prm >= min_prm_for_success:
                        good_examples.append(self._extract_teachable_example(traj))
                except Exception:
                    continue

        # 4. Generate proposals (LLM first, then heuristics)
        proposals: List[ImprovementProposal] = []
        new_prompt = None

        original_skill = self._load_original_skill(skill_name)
        original_prompt = (original_skill or {}).get("system_prompt", "") if original_skill else ""

        if self.use_llm and failures:
            llm_proposals, new_prompt = self._llm_generate_proposals(
                skill_name, analysis, failures, good_examples, original_prompt
            )
            proposals.extend(llm_proposals)

        # 5. Always run strong heuristic proposals (they are deterministic and excellent)
        heuristic_proposals = self._heuristic_proposals(analysis, original_prompt)
        proposals.extend(heuristic_proposals)

        # Dedup by section
        seen = set()
        unique_proposals = []
        for p in proposals:
            if p.section not in seen:
                seen.add(p.section)
                unique_proposals.append(p)

        proposed_name = f"{skill_name}-improved-{datetime.utcnow().strftime('%Y%m%d%H%M')}"

        ps = ProposedSkill(
            original_skill_name=skill_name,
            proposed_name=proposed_name,
            timestamp=datetime.utcnow().isoformat() + "Z",
            analysis=analysis,
            proposals=unique_proposals,
            new_system_prompt=new_prompt or self._apply_proposals_to_prompt(original_prompt, unique_proposals),
            suggested_few_shots=good_examples[:3],
            suggested_ci_checks=self._suggest_ci_checks(analysis),
            overall_rationale=self._synthesize_overall_rationale(analysis, unique_proposals),
            estimated_impact=self._estimate_impact(analysis),
        )
        return ps

    # ------------------------------------------------------------------
    # Internal analysis & generation
    # ------------------------------------------------------------------
    def _load(self, src: Union[str, Path, Dict]) -> Dict[str, Any]:
        if isinstance(src, dict):
            return src
        if load_trajectory:
            return load_trajectory(src, include_prm=True)
        # Fallback raw load
        p = Path(src)
        return json.loads(p.read_text(encoding="utf-8", errors="replace"))

    def _analyze_failures(self, failures: List[Dict]) -> Dict[str, Any]:
        """Extract the most actionable signals from low-quality steps."""
        low_step_types: Dict[str, int] = {}
        common_errors: List[str] = []
        low_prm_examples = []
        recovery_attempts = 0

        for traj in failures:
            pr = traj.get("prm_result") or {}
            steps = pr.get("step_scores", []) or []
            for s in steps:
                if getattr(s, "score", 1.0) < 0.45:
                    et = getattr(s, "event_type", "unknown")
                    low_step_types[et] = low_step_types.get(et, 0) + 1
                    if getattr(s, "reasons", []):
                        low_prm_examples.append({
                            "type": et,
                            "score": round(getattr(s, "score", 0), 3),
                            "reasons": getattr(s, "reasons", [])[:2],
                        })

            events = traj.get("events", [])
            for ev in events:
                data = ev.get("data", ev)
                if "error" in str(data).lower() or ev.get("type") == "error":
                    common_errors.append(str(data)[:160])
                if "retry" in str(data).lower() or "recover" in str(data).lower():
                    recovery_attempts += 1

        top_fail_modes = sorted(low_step_types.items(), key=lambda x: -x[1])[:5]

        return {
            "num_failures_analyzed": len(failures),
            "top_low_quality_step_types": top_fail_modes,
            "common_error_signatures": list(set(common_errors))[:6],
            "recovery_signals_seen": recovery_attempts,
            "example_low_prm_steps": low_prm_examples[:5],
            "avg_prm_on_failures": round(
                sum(
                    (float((t.get("prm_result") or {}).get("overall_prm_score") or 0.3))
                    for t in failures
                ) / max(1, len(failures)),
                3,
            ),
        }

    def _extract_teachable_example(self, traj: Dict) -> Dict[str, str]:
        """Turn a high-quality success trajectory into a compact few-shot teaching example."""
        events = traj.get("events", [])[-12:]
        trace = []
        for ev in events:
            et = ev.get("type", "")
            d = ev.get("data", ev)
            if et in ("reasoning", "llm_call", "tool_call", "decision"):
                preview = d.get("thought") or d.get("response_preview") or str(d.get("result_preview", ""))[:90]
                trace.append(f"[{et}] {preview}")
        return {
            "task_context": traj.get("task_id", "unknown"),
            "good_trace": "\n".join(trace[:8]),
            "outcome": "success",
            "prm": str((traj.get("prm_result") or {}).get("overall_prm_score", "high")),
        }

    def _llm_generate_proposals(
        self,
        skill_name: str,
        analysis: Dict,
        failures: List[Dict],
        good_examples: List[Dict],
        original_prompt: str,
    ) -> Tuple[List[ImprovementProposal], Optional[str]]:
        """Use the real grok CLI (same reliable pattern as PRM) to get excellent rewrites."""
        prompt = self._build_improver_prompt(skill_name, analysis, failures[:4], good_examples[:2], original_prompt)

        try:
            result = self._invoke_grok_for_improvement(prompt)
            if not result:
                return [], None

            proposals = []
            for p in result.get("proposals", []):
                proposals.append(
                    ImprovementProposal(
                        section=p.get("section", "system_prompt"),
                        original_snippet=p.get("original", "")[:1200],
                        proposed_snippet=p.get("proposed", ""),
                        rationale=p.get("rationale", ""),
                        confidence=float(p.get("confidence", 0.7)),
                        source="llm",
                    )
                )

            new_full_prompt = result.get("improved_system_prompt")
            return proposals, new_full_prompt
        except Exception as e:
            print(f"[SkillImprover] LLM proposal generation failed gracefully: {e}")
            return [], None

    def _build_improver_prompt(self, skill, analysis, failures, goods, original) -> str:
        return f"""You are an expert agent-skill engineer for AgentForge.

Your job: propose targeted, high-impact improvements to the YAML skill "{skill}" based on real failure trajectories.

=== FAILURE ANALYSIS (from PRM + events) ===
{json.dumps(analysis, indent=2)[:2200]}

=== SAMPLE FAILURE TRACES (abbreviated) ===
{json.dumps([f.get('task_id') for f in failures], indent=2)}

=== HIGH-QUALITY SUCCESS EXAMPLES (for few-shot mining) ===
{json.dumps(goods[:2], indent=2)[:1400]}

=== CURRENT SYSTEM PROMPT (excerpt) ===
{original[:1800]}

Return ONLY valid JSON with this exact shape:
{{
  "proposals": [
    {{
      "section": "system_prompt" | "few_shot" | "verification" | "recovery",
      "original": "exact short excerpt from current prompt",
      "proposed": "the improved version (precise, concrete, actionable)",
      "rationale": "why this fixes the observed failure modes",
      "confidence": 0.0-1.0
    }}
  ],
  "improved_system_prompt": "full rewritten system prompt incorporating the best proposals (ready to paste into YAML)",
  "suggested_few_shots": ["concise example 1", "example 2"],
  "estimated_impact": "high|medium|low"
}}

Be ruthless about specificity. Never add fluff. Focus on the exact pain points visible in the low-PRM steps and errors."""

    def _invoke_grok_for_improvement(self, prompt: str, timeout: int = 70) -> Optional[Dict[str, Any]]:
        """Identical reliable headless grok invocation pattern used in PRM."""
        pid = os.getpid()
        tmp_prompt = f"/tmp/skill_improver_{pid}.txt"
        tmp_out = f"/tmp/skill_improver_out_{pid}.log"

        try:
            Path(tmp_prompt).write_text(prompt[:24000], encoding="utf-8")

            bash_cmd = (
                f'cat > /tmp/skill_impr_{pid}.sh << "JSH"\n'
                f'#!/bin/bash\n'
                f'PROMPT_CONTENT=$(cat "{tmp_prompt}" | head -c 23000)\n'
                f'grok --always-approve -p "$PROMPT_CONTENT" 2>&1 | tee "{tmp_out}"\n'
                f'JSH\n'
                f'bash /tmp/skill_impr_{pid}.sh'
            )

            result = subprocess.run(
                ["bash", "-c", bash_cmd],
                capture_output=True, text=True, timeout=timeout,
                env={**os.environ, "GROK_FLAGS": "--always-approve"},
            )
            raw = (result.stdout or "") + (result.stderr or "")
            if Path(tmp_out).exists():
                raw += "\n" + Path(tmp_out).read_text(encoding="utf-8", errors="ignore")

            # Robust JSON extraction (same technique as PRM)
            import re
            candidates = []
            depth = 0
            start = -1
            for i, ch in enumerate(raw):
                if ch == "{":
                    if depth == 0: start = i
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0 and start != -1:
                        candidates.append(raw[start:i+1])
                        start = -1

            for cand in reversed(candidates):
                try:
                    parsed = json.loads(cand)
                    if isinstance(parsed, dict) and ("proposals" in parsed or "improved_system_prompt" in parsed):
                        return parsed
                except Exception:
                    continue

            m = re.search(r"```json\s*(\{.*?\})\s*```", raw, re.DOTALL | re.IGNORECASE)
            if m:
                try:
                    return json.loads(m.group(1))
                except Exception:
                    pass
            return None
        except Exception:
            return None

    def _heuristic_proposals(self, analysis: Dict, original_prompt: str) -> List[ImprovementProposal]:
        """Always-on high-signal deterministic improvements."""
        proposals = []
        low_types = dict(analysis.get("top_low_quality_step_types", []))

        if "tool_call" in low_types and low_types["tool_call"] >= 2:
            proposals.append(
                ImprovementProposal(
                    section="recovery",
                    original_snippet="",
                    proposed_snippet="After every tool call that returns an error or empty result, explicitly reason for 1-2 sentences about the failure mode, then decide whether to retry with different arguments or fall back to an alternative approach. Log the decision.",
                    rationale="Multiple low-quality tool_call steps observed. Strong pattern of unhandled tool failures.",
                    confidence=0.85,
                    source="heuristic",
                )
            )

        if "reasoning" in low_types:
            proposals.append(
                ImprovementProposal(
                    section="system_prompt",
                    original_snippet=original_prompt[:300] if original_prompt else "",
                    proposed_snippet="At every major decision point, produce a short structured reasoning block:\n1. Current hypothesis\n2. Evidence so far\n3. Next action + why it is the highest-leverage step\n4. What would falsify this hypothesis",
                    rationale="Weak or short reasoning steps are a top source of low PRM scores.",
                    confidence=0.78,
                    source="heuristic",
                )
            )

        if analysis.get("recovery_signals_seen", 0) < 1 and len(analysis.get("common_error_signatures", [])) > 1:
            proposals.append(
                ImprovementProposal(
                    section="recovery",
                    original_snippet="",
                    proposed_snippet="When you encounter an error, ALWAYS attempt exactly one structured recovery action before giving up. Document the recovery attempt explicitly.",
                    rationale="Very few recovery behaviors observed despite multiple errors — major learning opportunity.",
                    confidence=0.8,
                    source="heuristic",
                )
            )

        return proposals

    def _apply_proposals_to_prompt(self, original: str, proposals: List[ImprovementProposal]) -> str:
        prompt = original or ""
        for p in proposals:
            if p.section == "system_prompt" and p.proposed_snippet:
                prompt = prompt + "\n\n" + "# === LEARNING FLYWHEEL AUTO-IMPROVEMENT ===\n" + p.proposed_snippet
        return prompt.strip()

    def _suggest_ci_checks(self, analysis: Dict) -> List[str]:
        checks = []
        if "tool_call" in str(analysis.get("top_low_quality_step_types", [])):
            checks.append("echo 'Added extra verification after tool failures (learning improvement)'")
        return checks or ["# No new CI checks suggested by analysis"]

    def _synthesize_overall_rationale(self, analysis: Dict, proposals: List) -> str:
        modes = ", ".join([t[0] for t in analysis.get("top_low_quality_step_types", [])[:3]])
        return f"Targeted fixes for weak steps in: {modes}. {len(proposals)} concrete proposals generated from real PRM-labeled failures."

    def _estimate_impact(self, analysis: Dict) -> str:
        if analysis.get("num_failures_analyzed", 0) >= 5 and len(analysis.get("top_low_quality_step_types", [])) >= 2:
            return "high"
        return "medium"

    def _load_original_skill(self, name: str) -> Optional[Dict[str, Any]]:
        for ext in (".yaml", ".yml"):
            p = SKILLS_DIR / f"{name}{ext}"
            if p.exists():
                try:
                    return yaml.safe_load(p.read_text(encoding="utf-8"))
                except Exception:
                    return None
        return None


# ------------------------------------------------------------------
# Top-level convenience
# ------------------------------------------------------------------
def propose_skill_improvement(
    skill_name: str,
    failure_sources: List[Union[str, Path, Dict]],
    success_sources: Optional[List] = None,
    **kwargs,
) -> ProposedSkill:
    # PHASE 3 deprecation (RUST_FULL_MIGRATION_PLAN.md)
    if not is_pure_rust_flywheel():
        warnings.warn(
            "propose_skill_improvement (Python) deprecated per RUST_FULL_MIGRATION_PLAN.md PHASE 3. "
            "Served by agentforge-runner flywheel-step / candidate. Non-breaking on !pure.",
            DeprecationWarning,
            stacklevel=2,
        )
    return SkillImprover().propose_improvements(skill_name, failure_sources, success_sources, **kwargs)


__all__ = ["SkillImprover", "ProposedSkill", "ImprovementProposal", "propose_skill_improvement"]
