"""
evaluator.py — Automatic A/B testing harness for skills, prompts, and agent variants.

Phase 2 Learning Flywheel component.

Uses the existing production-grade Evaluation Framework (runner, schemas, history, PRM)
to run controlled comparisons:

- Old skill vs New proposed skill (or prompt variant)
- Different versions of the same skill
- Prompt ablations
- Full agent version comparisons

Key capabilities:
- Run the exact same set of benchmarks on both arms (hermetic where possible)
- Rich metrics: success_rate, avg_prm, avg_duration, avg_cost, recovery_rate, quality
- Simple statistical signals (win rate, delta, directional consistency)
- Automatic trajectory + PRM capture on both arms
- Produces ABResult that can be fed back into the flywheel (or used by suggest/insights)
- Supports "prompt injection" testing without modifying production skill files (via temp skills or extra_context)

Pragmatic design:
- Reuses eval.runner.run_benchmark_task + post_process_run heavily
- For real skill testing: supports dispatching with SKILL=... or temp YAML override
- For fast iteration: supports "virtual" prompt variants via benchmark extra_context
- Never blocks on real runs unless explicitly requested

Typical usage in the loop:
    from agentforge.learning.skill_improver import SkillImprover
    from agentforge.learning.evaluator import LearningEvaluator, ABTestConfig

!!! AGGRESSIVE FINAL DEPRECATION SWEEP (RUST_FULL_MIGRATION_PLAN.md + PHASE4_REMOVAL_PLAN.md) !!!
!!! PYTHON FLYWHEEL-DRIVEN EVALUATOR ORCHESTRATION ENTRYPOINTS DEPRECATED — PHASE 4 DELETE !!!
MIGRATE TO: agentforge-runner continuous (drives native Rust A/B + promote + candidate)

Guard with Phase 4 hardened central ONLY:
  from agentforge.learning.utils import is_pure_rust_flywheel

Python A/B harness remains useful for hybrid/eval but flywheel orchestration paths deprecated.
Non-breaking for !pure and direct eval use.

See learning/utils.py (even stronger guards + exhaustive deprecated list)
See PHASE4_REMOVAL_PLAN.md (Tier 2 removal, risks detailed: A/B delegation to Rust continuous).

Typical continued example (inside docstring):
    proposal = SkillImprover().propose_improvements("rust-fix", failures)
    evaluator = LearningEvaluator()

    result = evaluator.ab_test_skill_versions(
        benchmark_ids=["example_rust_refactor", "lancedb_parser_bottleneck"],
        old_skill="rust-fix",
        new_skill_or_prompt=proposal.new_system_prompt,   # or a temp yaml path
        agent="grok",
        n_runs_per_arm=1,
        wait_for_real=True,
    )
    print(result.summary())
    if result.is_clear_winner("new"):
        proposal.save_candidate_yaml(...)   # promote
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Literal, Union, Tuple

# Deep integration with the eval framework (Phase 1 is solid)
try:
    from agentforge.eval.runner import run_benchmark_task, post_process_run
    from agentforge.eval.schemas import BenchmarkTask, EvaluationResult, TaskOutcome
    from agentforge.eval.history import record_run, get_recent_summary
    from agentforge.eval.prm import ProcessRewardModel
except Exception as e:
    print(f"[learning.evaluator] Warning: limited eval integration: {e}")
    run_benchmark_task = None  # type: ignore
    EvaluationResult = dict  # type: ignore
    ProcessRewardModel = None  # type: ignore

# Phase 3: central strong guard (for future runtime skips + callers)
try:
    from agentforge.learning.utils import is_pure_rust_flywheel
except Exception:
    try:
        from .utils import is_pure_rust_flywheel  # type: ignore
    except Exception:
        is_pure_rust_flywheel = lambda: False  # type: ignore  # Phase 4 safe fallback ONLY (central impl in utils.py; never a local dupe guard)

# For loading real benchmark tasks
EVAL_EXAMPLES_DIR = Path(__file__).parent.parent / "eval" / "examples"


@dataclass
class ArmResult:
    """Metrics for one side of an A/B test."""
    name: str
    runs: List[EvaluationResult]
    success_rate: float
    avg_prm: Optional[float]
    avg_duration: float
    avg_cost: float
    avg_steps: float
    avg_tool_calls: float
    recovery_rate: float
    total_cost: float
    prm_distribution: List[float] = field(default_factory=list)


@dataclass
class ABResult:
    """Complete, comparable result of an A/B test."""
    test_id: str
    config: "ABTestConfig"
    baseline: ArmResult
    treatment: ArmResult
    timestamp: str
    deltas: Dict[str, float]                # success_rate, avg_prm, etc.
    winner: Optional[Literal["baseline", "treatment", "tie"]] = None
    confidence: str = "low"                 # low | medium | high (heuristic)
    notes: List[str] = field(default_factory=list)

    def summary(self) -> str:
        b, t = self.baseline, self.treatment
        d = self.deltas
        lines = [
            f"AB Test {self.test_id} — {self.config.name}",
            f"Baseline ({b.name}): {b.success_rate*100:.1f}% success | PRM {b.avg_prm or 0:.2f} | {b.avg_duration:.1f}s | ${b.avg_cost:.4f}",
            f"Treatment ({t.name}): {t.success_rate*100:.1f}% success | PRM {t.avg_prm or 0:.2f} | {t.avg_duration:.1f}s | ${t.avg_cost:.4f}",
            f"Deltas: success {d.get('success_rate', 0)*100:+.1f}pp | PRM {d.get('avg_prm', 0):+.2f} | time {d.get('avg_duration', 0):+.1f}s | cost {d.get('avg_cost', 0):+.4f}",
            f"Winner: {self.winner} (confidence: {self.confidence})",
        ]
        return "\n".join(lines)

    def is_clear_winner(self, arm: Literal["baseline", "treatment"]) -> bool:
        if self.winner != arm:
            return False
        return self.confidence in ("medium", "high")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "test_id": self.test_id,
            "timestamp": self.timestamp,
            "baseline": asdict(self.baseline),
            "treatment": asdict(self.treatment),
            "deltas": self.deltas,
            "winner": self.winner,
            "confidence": self.confidence,
            "notes": self.notes,
            "config": asdict(self.config),
        }


@dataclass
class ABTestConfig:
    name: str = "skill_ab_test"
    agent: str = "grok"
    n_runs_per_arm: int = 1
    wait_for_real: bool = False
    simulate: bool = False
    min_prm_threshold: Optional[float] = None
    timeout_minutes: int = 60
    use_temp_skill_files: bool = True   # recommended for clean A/B
    extra_context: Dict[str, Any] = field(default_factory=dict)


class LearningEvaluator:
    """
    The A/B testing engine that closes the learning loop.

    Designed to be called from SkillImprover consumers, CI, or manual "promote candidate" flows.
    """

    def __init__(self, default_config: Optional[ABTestConfig] = None):
        self.default_config = default_config or ABTestConfig()
        # Robust: ProcessRewardModel may be undefined if eval import failed (common in direct runs)
        try:
            self.prm = ProcessRewardModel() if 'ProcessRewardModel' in globals() and ProcessRewardModel else None
        except NameError:
            self.prm = None
        self._temp_files: List[Path] = []  # for cleanup

    def ab_test_skill_versions(
        self,
        benchmark_ids: List[str],
        old_skill: str,
        new_skill_or_prompt: Union[str, Path, Dict[str, Any]],
        config: Optional[ABTestConfig] = None,
        **override_kwargs,
    ) -> ABResult:
        """
        The primary method. Runs the same benchmarks on both the old and new skill/prompt.

        new_skill_or_prompt can be:
          - name of an existing skill
          - full new system_prompt text (will be written to a temp skill)
          - path to a candidate YAML
        """
        cfg = config or self.default_config
        for k, v in override_kwargs.items():
            if hasattr(cfg, k):
                setattr(cfg, k, v)

        test_id = f"ab-{uuid.uuid4().hex[:10]}"
        print(f"\n[LearningEvaluator] Starting A/B test {test_id}")
        print(f"  Benchmarks: {benchmark_ids}")
        print(f"  Old skill : {old_skill}")
        print(f"  New       : {type(new_skill_or_prompt)}")

        # Resolve the treatment skill representation
        treatment_skill_ref = self._materialize_treatment_skill(new_skill_or_prompt, cfg)

        baseline_runs: List[EvaluationResult] = []
        treatment_runs: List[EvaluationResult] = []

        # Run both arms (simple sequential for now; parallel possible later via threads)
        for bid in benchmark_ids:
            task = self._load_benchmark(bid)
            if not task:
                print(f"  [skip] Benchmark not found: {bid}")
                continue

            # Baseline arm (old skill)
            for _ in range(cfg.n_runs_per_arm):
                r = self._run_one(task, agent=cfg.agent, skill=old_skill, simulate=cfg.simulate, wait=cfg.wait_for_real, timeout=cfg.timeout_minutes)
                baseline_runs.append(r)

            # Treatment arm
            for _ in range(cfg.n_runs_per_arm):
                r = self._run_one(task, agent=cfg.agent, skill=treatment_skill_ref, simulate=cfg.simulate, wait=cfg.wait_for_real, timeout=cfg.timeout_minutes, is_treatment=True)
                treatment_runs.append(r)

        # Aggregate
        baseline_arm = self._aggregate_arm("baseline", baseline_runs)
        treatment_arm = self._aggregate_arm("treatment", treatment_runs)

        deltas = self._compute_deltas(baseline_arm, treatment_arm)
        winner, confidence = self._decide_winner(baseline_arm, treatment_arm, deltas)

        result = ABResult(
            test_id=test_id,
            config=cfg,
            baseline=baseline_arm,
            treatment=treatment_arm,
            timestamp=datetime.utcnow().isoformat() + "Z",
            deltas=deltas,
            winner=winner,
            confidence=confidence,
            notes=[f"Ran {len(benchmark_ids)} benchmarks × {cfg.n_runs_per_arm} per arm"],
        )

        # Record the comparison into longitudinal history for the flywheel
        self._record_ab_result(result)

        print(result.summary())
        return result

    def ab_test_prompt_variant(
        self,
        benchmark_ids: List[str],
        base_skill: str,
        variant_prompt_addition: str,
        config: Optional[ABTestConfig] = None,
    ) -> ABResult:
        """Convenience wrapper for testing a small prompt delta without full skill rewrite."""
        new_prompt = f"{base_skill}_variant_{datetime.utcnow().strftime('%H%M')}"
        # In practice we would write a temp skill that inherits + appends the delta
        return self.ab_test_skill_versions(
            benchmark_ids, base_skill, {"name": new_prompt, "system_prompt": variant_prompt_addition}, config=config
        )

    # ------------------------------------------------------------------
    # Internals — execution + aggregation
    # ------------------------------------------------------------------
    def _materialize_treatment_skill(self, new_thing: Union[str, Path, Dict], cfg: ABTestConfig) -> str:
        """Return a skill name or path that the runner can consume."""
        if isinstance(new_thing, (str, Path)) and Path(new_thing).exists():
            return str(new_thing)  # already a yaml path

        if isinstance(new_thing, dict):
            # Create a temp YAML skill
            name = new_thing.get("name", f"temp-skill-{uuid.uuid4().hex[:6]}")
            tmp = Path(tempfile.mkdtemp(prefix="agentforge_skill_")) / f"{name}.yaml"
            with open(tmp, "w", encoding="utf-8") as f:
                import yaml
                yaml.safe_dump(new_thing, f, sort_keys=False)
            self._temp_files.append(tmp)
            return str(tmp)

        if isinstance(new_thing, str) and len(new_thing) > 80:
            # Treat as raw prompt text — create a minimal temp skill
            name = f"prompt-variant-{uuid.uuid4().hex[:6]}"
            payload = {
                "name": name,
                "description": "Auto-generated prompt variant from Learning Flywheel",
                "system_prompt": new_thing,
                "required_tags": ["learning-ab-test"],
            }
            tmp = Path(tempfile.mkdtemp(prefix="agentforge_skill_")) / f"{name}.yaml"
            import yaml
            tmp.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
            self._temp_files.append(tmp)
            return str(tmp)

        # Assume it's an existing skill name
        return str(new_thing)

    def _load_benchmark(self, bid: str) -> Optional[BenchmarkTask]:
        # Try examples first (real ones from history)
        for ext in (".json",):
            p = EVAL_EXAMPLES_DIR / f"{bid}{ext}"
            if p.exists():
                try:
                    data = json.loads(p.read_text())
                    return BenchmarkTask(**data)
                except Exception:
                    pass

        # Fallback: construct a minimal task (still useful for prompt testing)
        return BenchmarkTask(
            id=bid,
            title=bid.replace("_", " ").title(),
            description=f"Learning flywheel A/B benchmark for {bid}",
            difficulty="medium",
            category="learning",
            verification="manual_review",
        )

    def _run_one(
        self,
        task: BenchmarkTask,
        agent: str,
        skill: str,
        simulate: bool,
        wait: bool,
        timeout: int,
        is_treatment: bool = False,
    ) -> EvaluationResult:
        """Dispatch via the canonical eval runner. Skill is passed through env or extra_context."""
        # The current runner supports SKILL via the underlying dispatch for real runs.
        # For maximum compatibility we set the env var that grok_runner.sh reads.
        original_skill = os.environ.get("SKILL")
        try:
            if not simulate and skill:
                os.environ["SKILL"] = str(skill)

            if run_benchmark_task:
                result = run_benchmark_task(
                    task,
                    agent=agent,
                    timeout_minutes=timeout,
                    simulate=simulate,
                    wait=wait,
                )
            else:
                # Minimal fallback result
                result = EvaluationResult(  # type: ignore
                    task_id=task.id, agent=agent, outcome="failed", duration_seconds=0.1
                )

            # Ensure PRM + trajectory are attached even on fast paths
            try:
                if hasattr(result, "trajectory_path"):
                    result = post_process_run(result, force_prm=True)
            except Exception:
                pass

            return result
        finally:
            if original_skill is not None:
                os.environ["SKILL"] = original_skill
            else:
                os.environ.pop("SKILL", None)

    def _aggregate_arm(self, name: str, runs: List[EvaluationResult]) -> ArmResult:
        if not runs:
            return ArmResult(name=name, runs=[], success_rate=0.0, avg_prm=None,
                             avg_duration=0, avg_cost=0, avg_steps=0, avg_tool_calls=0,
                             recovery_rate=0, total_cost=0)

        successes = sum(1 for r in runs if getattr(r, "outcome", None) == TaskOutcome.SUCCESS or getattr(r, "outcome", "") == "success")
        total = len(runs)
        sr = successes / total

        prms = [getattr(r, "prm_overall_score", None) for r in runs if getattr(r, "prm_overall_score", None) is not None]
        avg_prm = sum(prms) / len(prms) if prms else None

        durations = [getattr(r, "duration_seconds", 0) or 0 for r in runs]
        costs = [getattr(r, "cost_usd", 0) or 0 for r in runs]
        steps = [getattr(r, "steps_taken", 0) or 0 for r in runs]
        tools = [getattr(r, "tool_calls", 0) or 0 for r in runs]

        recoveries = sum(1 for r in runs if getattr(r, "recovery_attempts", 0) > 0)

        return ArmResult(
            name=name,
            runs=runs,
            success_rate=round(sr, 4),
            avg_prm=round(avg_prm, 3) if avg_prm is not None else None,
            avg_duration=round(sum(durations) / len(durations), 1),
            avg_cost=round(sum(costs) / len(costs), 5),
            avg_steps=round(sum(steps) / len(steps), 1),
            avg_tool_calls=round(sum(tools) / len(tools), 1),
            recovery_rate=round(recoveries / total, 3),
            total_cost=round(sum(costs), 4),
            prm_distribution=[round(p, 3) for p in prms],
        )

    def _compute_deltas(self, b: ArmResult, t: ArmResult) -> Dict[str, float]:
        return {
            "success_rate": round(t.success_rate - b.success_rate, 4),
            "avg_prm": round((t.avg_prm or 0) - (b.avg_prm or 0), 3),
            "avg_duration": round(t.avg_duration - b.avg_duration, 1),
            "avg_cost": round(t.avg_cost - b.avg_cost, 5),
            "recovery_rate": round(t.recovery_rate - b.recovery_rate, 3),
        }

    def _decide_winner(self, b: ArmResult, t: ArmResult, deltas: Dict[str, float]) -> Tuple[Optional[str], str]:
        sr_delta = deltas.get("success_rate", 0)
        prm_delta = deltas.get("avg_prm", 0)

        if abs(sr_delta) < 0.05 and abs(prm_delta) < 0.08:
            return "tie", "low"

        # Simple but effective rule
        if sr_delta > 0.08 or (sr_delta > 0.03 and prm_delta > 0.06):
            return "treatment", "medium" if sr_delta > 0.12 or prm_delta > 0.12 else "low"
        if sr_delta < -0.08 or (sr_delta < -0.03 and prm_delta < -0.06):
            return "baseline", "medium" if sr_delta < -0.12 or prm_delta < -0.12 else "low"

        return "tie", "low"

    def _record_ab_result(self, result: ABResult):
        """Persist the comparison into history so the rest of the system sees learning progress."""
        try:
            record_run(
                benchmark_id=f"ab_test_{result.test_id[:8]}",
                agent=result.config.agent,
                outcome="success" if result.winner == "treatment" else "partial",
                duration_seconds=result.treatment.avg_duration,
                mode="learning_ab",
                extra={
                    "ab_test": result.test_id,
                    "winner": result.winner,
                    "success_delta": result.deltas.get("success_rate"),
                    "prm_delta": result.deltas.get("avg_prm"),
                    "baseline_sr": result.baseline.success_rate,
                    "treatment_sr": result.treatment.success_rate,
                },
            )
        except Exception:
            pass

    def cleanup(self):
        for p in self._temp_files:
            try:
                if p.exists():
                    p.unlink()
                    p.parent.rmdir()
            except Exception:
                pass
        self._temp_files.clear()


# Convenience top-level function
def run_ab_test(
    benchmark_ids: List[str],
    old_skill: str,
    new_skill_or_prompt: Union[str, Path],
    **kwargs,
) -> ABResult:
    return LearningEvaluator().ab_test_skill_versions(benchmark_ids, old_skill, new_skill_or_prompt, **kwargs)


__all__ = ["LearningEvaluator", "ABResult", "ArmResult", "ABTestConfig", "run_ab_test"]
