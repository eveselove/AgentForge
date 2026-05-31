"""
Targeted unit tests for PRM (Process Reward Model) features.
Phase 1: scoring, integration points with loader, report, analyze, history, insights.
"""

import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path
import tempfile
import json
import os

from agentforge.eval import prm as prm_mod
from agentforge.eval.prm import ProcessRewardModel, StepScore, TrajectoryPRMResult
from agentforge.eval import trajectory as traj_mod


class TestPRMScoring(unittest.TestCase):
    """Core PRM scoring logic (heuristic engine)."""

    def setUp(self):
        self.prm = ProcessRewardModel(use_llm_judge=False)

    def test_score_simple_trajectory(self):
        traj = {
            "task_id": "test-001",
            "agent": "grok",
            "events": [
                {"ts": "2026-01-01", "type": "reasoning", "thought": "Detailed plan with lots of context here for testing."},
                {"ts": "2026-01-01", "type": "tool_call", "tool": "edit", "result_preview": "successfully applied patch with 120 lines changed", "duration_ms": 1200},
                {"ts": "2026-01-01", "type": "llm_call", "tokens_out": 850, "tokens_in": 120, "cost_usd": 0.01},
            ]
        }
        res = self.prm.score_trajectory(traj)
        self.assertIsInstance(res, TrajectoryPRMResult)
        self.assertGreaterEqual(res.overall_prm_score, 0.0)
        self.assertLessEqual(res.overall_prm_score, 1.0)
        self.assertEqual(res.num_steps, 3)
        self.assertGreaterEqual(res.num_high_quality_steps + res.num_low_quality_steps, 0)

    def test_low_quality_signals(self):
        traj = {
            "task_id": "test-low",
            "events": [
                {"type": "llm_call", "tokens_out": 5000, "tokens_in": 50, "cost_usd": 0.2},  # bad: long + expensive
                {"type": "tool_call", "duration_ms": 45000, "result_preview": "error: failed to connect"},
            ]
        }
        res = self.prm.score_trajectory(traj)
        self.assertLess(res.overall_prm_score, 0.55)
        self.assertGreater(res.num_low_quality_steps, 0)

    def test_high_quality_recovery(self):
        traj = {
            "task_id": "test-hi",
            "events": [
                {"type": "tool_call", "result_preview": "success after retry", "args": {"retry": True}, "duration_ms": 800},
            ]
        }
        res = self.prm.score_trajectory(traj)
        # Recovery bonus + infra neutral-positive
        self.assertGreaterEqual(res.overall_prm_score, 0.6)

    def test_empty_trajectory(self):
        res = self.prm.score_trajectory({"task_id": "empty", "events": []})
        self.assertEqual(res.overall_prm_score, 0.0)
        self.assertEqual(res.num_steps, 0)


class TestPRMIntegrationPoints(unittest.TestCase):
    """Loader, results schema, history extra, report/analyze hooks."""

    def test_trajectory_loader_prm_hook(self):
        # Use temp file to test include_prm
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "test_traj.json"
            data = {"task_id": "t1", "agent": "test", "events": [{"type": "reasoning", "thought": "x" * 50}]}
            p.write_text(json.dumps(data))
            # Monkey patch dir for loader
            with patch.object(traj_mod, '_get_trajectories_dir', return_value=Path(tmp)):
                loaded = traj_mod.load_trajectory(str(p), include_prm=True)
                self.assertIn("prm_result", loaded)
                self.assertIn("overall_prm_score", loaded["prm_result"] or {})

    def test_evaluation_result_prm_fields_present(self):
        from agentforge.eval.schemas import EvaluationResult, TaskOutcome
        res = EvaluationResult(task_id="x", agent="grok", outcome=TaskOutcome.SUCCESS, duration_seconds=10.0,
                               prm_overall_score=0.82, prm_high_quality_steps=7, prm_low_quality_steps=1)
        self.assertEqual(res.prm_overall_score, 0.82)
        self.assertEqual(res.prm_high_quality_steps, 7)

    def test_history_records_prm_via_extra(self):
        from agentforge.eval.history import record_run, load_history
        with tempfile.TemporaryDirectory() as tmpd:
            orig = prm_mod.HISTORY_DIR if hasattr(prm_mod, 'HISTORY_DIR') else None
            # Use env override
            os.environ["AGENTFORGE_EVAL_HISTORY_DIR"] = tmpd
            # Reimport to pick up? Instead directly call with monkey on path
            from agentforge.eval import history as hist_mod
            hist_mod.HISTORY_DIR = Path(tmpd)
            record_run("bench-prm", "grok", "success", 42.0, extra={"prm_overall_score": 0.91, "prm_low_quality_steps": 0})
            recs = load_history("bench-prm")
            self.assertTrue(recs)
            self.assertIn("prm_overall_score", recs[-1])
            self.assertAlmostEqual(recs[-1]["prm_overall_score"], 0.91)

    @patch("agentforge.eval.generate_evaluation_report.load_evaluation_results")
    def test_report_includes_prm_first_class(self, mock_load):
        mock_load.return_value = [
            {"task_id": "b1", "_mode": "real", "outcome": "success", "prm_overall_score": 0.88},
            {"task_id": "b1", "_mode": "real", "outcome": "success", "prm_overall_score": 0.41},
        ]
        from agentforge.eval.generate_evaluation_report import generate_report
        out = generate_report(mock_load.return_value, {"total_tasks": 1})
        self.assertIn("Process Quality Trends (PRM)", out)
        self.assertIn("0.645", out)  # avg
        self.assertIn("Process Quality Alerts (PRM-driven)", out)
        self.assertIn("brittle", out.lower())

    @patch("agentforge.eval.analyze_trajectories.analyze_prm_quality")
    def test_analyze_trajectories_prm_integration(self, mock_prm):
        mock_prm.return_value = {
            "trajectories_analyzed": 2,
            "average_prm_score": 0.71,
            "average_step_quality": 0.68,
            "low_process_quality_count": 1,
            "high_quality_step_pct": 62.5,
        }
        from agentforge.eval.analyze_trajectories import analyze
        # minimal events to avoid full run
        stats = analyze([{"task_id": "t", "type": "reasoning"}])
        self.assertIn("prm", stats)
        # The analyze_prm is called inside analyze()


class TestPRMInInsightsAndSuggest(unittest.TestCase):
    def test_insights_detects_low_prm_success(self):
        with patch("agentforge.eval.insights.load_evaluation_results") as m:
            m.return_value = [{"task_id": "fragile1", "outcome": "success", "prm_overall_score": 0.33}]
            from agentforge.eval.insights import generate_insights
            ins = generate_insights(limit=5)
            joined = " ".join(ins).lower()
            self.assertTrue("low process" in joined or "brittle" in joined or "prm" in joined)

    def test_suggest_prioritizes_prm(self):
        with patch("agentforge.eval.suggest.load_evaluation_results") as m:
            m.return_value = [{"task_id": "crit", "outcome": "success", "prm_overall_score": 0.29}]
            from agentforge.eval.suggest import generate_suggestions
            suggs = generate_suggestions(limit=5)
            self.assertTrue(any("PRIORITY" in s or "low PRM" in s or "prm" in s.lower() for s in suggs))


class TestLLMJudgePath(unittest.TestCase):
    """Basic tests for the new real LLM-as-Judge implementation (mocked)."""

    def test_llm_judge_disabled_by_default(self):
        prm = ProcessRewardModel()
        self.assertFalse(prm.use_llm_judge)

    def test_llm_judge_enabled_via_ctor_and_env(self):
        prm = ProcessRewardModel(use_llm_judge=True)
        self.assertTrue(prm.use_llm_judge)
        with patch.dict(os.environ, {"AGENTFORGE_PRM_USE_LLM_JUDGE": "1"}):
            prm2 = ProcessRewardModel()
            self.assertTrue(prm2.use_llm_judge)

    @patch("agentforge.eval.prm.ProcessRewardModel._invoke_grok_judge")
    def test_llm_judge_blends_scores_and_marks_used(self, mock_invoke):
        mock_invoke.return_value = {
            "overall_prm_score": 0.91,
            "step_scores": [
                {"index": 0, "score": 0.95, "reasons": ["excellent reasoning", "clear plan"], "confidence": 0.85},
                {"index": 2, "score": 0.88, "reasons": ["strong recovery"], "confidence": 0.8},
            ],
            "suggestions_for_improvement": ["Great use of protocol logging"],
            "num_high_quality_steps": 2,
            "num_low_quality_steps": 0,
        }

        traj = {
            "task_id": "judge-test-42",
            "agent": "grok",
            "events": [
                {"type": "reasoning", "data": {"thought": "detailed plan here with alternatives"}},
                {"type": "tool_call", "data": {"tool": "edit"}},
                {"type": "llm_turn", "data": {"focus": "verify"}},
            ],
        }
        prm = ProcessRewardModel(use_llm_judge=True)
        res = prm.score_trajectory(traj)
        self.assertTrue(prm._llm_judge_used)
        self.assertGreaterEqual(res.overall_prm_score, 0.88)
        # LLM reasons should have been blended into at least one step
        has_llm_reason = any("[LLM-JUDGE]" in (r or "") for s in res.step_scores for r in (s.reasons or []))
        self.assertTrue(has_llm_reason or res.overall_prm_score > 0.85)
        self.assertIn("Great use of protocol logging", res.suggestions_for_improvement)

    @patch("agentforge.eval.prm.ProcessRewardModel._invoke_grok_judge")
    def test_llm_judge_graceful_fallback_on_error(self, mock_invoke):
        mock_invoke.return_value = {"_error": "timeout"}
        traj = {"task_id": "fb", "events": [{"type": "tool_call", "data": {"result_preview": "success"}}]}
        prm = ProcessRewardModel(use_llm_judge=True)
        res = prm.score_trajectory(traj)
        # Still produces valid heuristic result
        self.assertIsInstance(res, TrajectoryPRMResult)
        self.assertGreaterEqual(res.overall_prm_score, 0.0)


if __name__ == "__main__":
    unittest.main()