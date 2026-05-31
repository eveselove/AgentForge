"""
Unit tests for insights.py

Focus areas:
- generate_insights produces sensible prioritized strings
- Handles declining trends (from history)
- Integrates regression detection
- Graceful degradation when trajectory analysis fails (the try/except blocks)
- print_insights produces expected console output
"""

import unittest
from unittest.mock import patch, MagicMock
from io import StringIO
import sys

from agentforge.eval import insights


class TestGenerateInsights(unittest.TestCase):
    """Test the core insight generation logic."""

    def test_returns_at_least_one_insight_always(self):
        """Even with empty world we should get some insight (low-RAG, default, or other)."""
        # Force trajectory analysis to avoid the low-RAG side effect by returning high usage
        high_rag_stats = {"total_tasks": 10, "rag_usage": 8, "infra_steps": {}}
        with patch("agentforge.eval.insights.get_all_benchmarks_with_history", return_value=[]):
            with patch("agentforge.eval.insights.get_recent_summary", return_value={"runs": 0}):
                with patch("agentforge.eval.insights.load_trajectories", return_value=[{"x": 1}]):
                    with patch("agentforge.eval.insights.analyze", return_value=high_rag_stats):
                        with patch("agentforge.eval.insights.detect_regressions", return_value=[]):
                            res = insights.generate_insights()
                            self.assertIsInstance(res, list)
                            self.assertGreaterEqual(len(res), 1)

    def test_includes_declining_benchmarks(self):
        with patch("agentforge.eval.insights.get_all_benchmarks_with_history", return_value=["bench_a", "bench_b"]):
            def fake_summary(bid, window=6):
                if bid == "bench_a":
                    return {"trend": "declining", "runs": 5, "success_rate": 0.4}
                return {"trend": "stable", "runs": 10}

            with patch("agentforge.eval.insights.get_recent_summary", side_effect=fake_summary):
                with patch("agentforge.eval.insights.load_trajectories", side_effect=Exception("no traj")):
                    with patch("agentforge.eval.insights.detect_regressions", return_value=[]):
                        res = insights.generate_insights(limit=5)
                        self.assertTrue(any("Declining performance detected" in s and "bench_a" in s for s in res))

    def test_includes_regression_insight_when_present(self):
        fake_reg = {
            "benchmark_id": "critical_bench",
            "baseline_rate": 0.88,
            "recent_rate": 0.55,
            "absolute_drop": 0.33,
            "relative_drop": 0.375,
            "recent_runs": 8,
            "baseline_runs": 15,
        }

        with patch("agentforge.eval.insights.get_all_benchmarks_with_history", return_value=[]):
            with patch("agentforge.eval.insights.get_recent_summary", return_value={"runs": 0}):
                with patch("agentforge.eval.insights.load_trajectories", return_value=[]):
                    with patch("agentforge.eval.insights.analyze", return_value={}):
                        with patch("agentforge.eval.insights.detect_regressions", return_value=[fake_reg]):
                            res = insights.generate_insights()
                            joined = " ".join(res)
                            self.assertIn("Performance regressions detected", joined)
                            self.assertIn("critical_bench", joined)

    def test_respects_limit_parameter(self):
        # Only one "declining" insight string is ever produced (even for many benches)
        with patch("agentforge.eval.insights.get_all_benchmarks_with_history", return_value=["d1", "d2"]):
            def many_declining(bid, window):
                return {"trend": "declining", "runs": 6}

            with patch("agentforge.eval.insights.get_recent_summary", side_effect=many_declining):
                with patch("agentforge.eval.insights.load_trajectories", side_effect=Exception):
                    with patch("agentforge.eval.insights.detect_regressions", return_value=[]):
                        res = insights.generate_insights(limit=2)
                        # We only ever emit at most 1 declining signal in current impl
                        self.assertLessEqual(len(res), 2)
                        self.assertGreaterEqual(len(res), 1)

    def test_gracefully_handles_trajectory_and_regression_failures(self):
        """The many try/except blocks must never let exceptions escape."""
        with patch("agentforge.eval.insights.get_all_benchmarks_with_history", return_value=["x"]):
            with patch("agentforge.eval.insights.get_recent_summary", return_value={"runs": 7, "trend": "stable"}):
                # Force all optional data sources to explode
                with patch("agentforge.eval.insights.load_trajectories", side_effect=RuntimeError("boom")):
                    with patch("agentforge.eval.insights.detect_regressions", side_effect=RuntimeError("reg boom")):
                        # Should still succeed and return the fallback insight
                        res = insights.generate_insights()
                        self.assertTrue(any("No major red flags" in s for s in res))


class TestPrintInsights(unittest.TestCase):
    def test_print_insights_emits_header_and_numbered_list(self):
        fake_insights = ["First insight here.", "Second one."]

        with patch("agentforge.eval.insights.generate_insights", return_value=fake_insights):
            captured = StringIO()
            old_stdout = sys.stdout
            sys.stdout = captured
            try:
                insights.print_insights()
            finally:
                sys.stdout = old_stdout

            output = captured.getvalue()
            self.assertIn("=== AgentForge Evaluation Insights ===", output)
            self.assertIn("1. First insight here.", output)
            self.assertIn("2. Second one.", output)
            self.assertIn("These insights improve automatically", output)


if __name__ == "__main__":
    unittest.main(verbosity=2)
