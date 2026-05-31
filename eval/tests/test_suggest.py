"""
Unit tests for suggest.py

Covers prioritized suggestion generation:
- High-priority critical benchmarks (very low success)
- Declining trend suggestions
- Infrastructure overhead suggestions
- Integration with insights + regression
- Fallback suggestions when data is sparse
- print_suggestions output formatting
"""

import unittest
from unittest.mock import patch
from io import StringIO
import sys

from agentforge.eval import suggest


class TestGenerateSuggestions(unittest.TestCase):
    def test_always_returns_list_of_strings(self):
        with patch("agentforge.eval.suggest.generate_insights", return_value=[]):
            with patch("agentforge.eval.suggest.get_all_benchmarks_with_history", return_value=[]):
                with patch("agentforge.eval.suggest.load_trajectories", return_value=[]):
                    with patch("agentforge.eval.suggest.analyze", return_value={}):
                        with patch("agentforge.eval.suggest.detect_regressions", return_value=[]):
                            res = suggest.generate_suggestions(limit=10)
                            self.assertIsInstance(res, list)
                            self.assertTrue(all(isinstance(x, str) for x in res))

    def test_high_priority_critical_benchmark_bubbles_to_top(self):
        """When success < 50% on a benchmark with enough runs, it should be first suggestion."""
        def summary_for(bid, window=6):
            if bid == "broken_bench":
                return {"runs": 7, "success_rate": 0.28, "trend": "stable"}
            return {"runs": 12, "success_rate": 0.91, "trend": "stable"}

        with patch("agentforge.eval.suggest.generate_insights", return_value=["Some generic insight"]):
            with patch("agentforge.eval.suggest.get_all_benchmarks_with_history", return_value=["broken_bench", "good_bench"]):
                with patch("agentforge.eval.suggest.get_recent_summary", side_effect=summary_for):
                    with patch("agentforge.eval.suggest.load_trajectories", side_effect=Exception("no traj")):
                        res = suggest.generate_suggestions(limit=5)

        self.assertGreater(len(res), 0)
        self.assertIn("High priority: Fix performance on `broken_bench`", res[0])
        self.assertIn("28%", res[0])

    def test_declining_trend_generates_debug_suggestion(self):
        def summary_for(bid, window):
            if bid == "sliding":
                return {"runs": 9, "success_rate": 0.78, "trend": "declining"}
            return {"runs": 5, "success_rate": 0.95, "trend": "stable"}

        with patch("agentforge.eval.suggest.generate_insights", return_value=[]):
            with patch("agentforge.eval.suggest.get_all_benchmarks_with_history", return_value=["sliding"]):
                with patch("agentforge.eval.suggest.get_recent_summary", side_effect=summary_for):
                    with patch("agentforge.eval.suggest.load_trajectories", return_value=[]):
                        res = suggest.generate_suggestions()
                        self.assertTrue(any("Re-run and debug `sliding`" in s for s in res))

    def test_low_but_not_critical_benchmark_still_watched(self):
        def summary_for(bid, window):
            return {"runs": 10, "success_rate": 0.68, "trend": "stable"}

        with patch("agentforge.eval.suggest.generate_insights", return_value=[]):
            with patch("agentforge.eval.suggest.get_all_benchmarks_with_history", return_value=["mediocre"]):
                with patch("agentforge.eval.suggest.get_recent_summary", side_effect=summary_for):
                    with patch("agentforge.eval.suggest.load_trajectories", return_value=[]):
                        res = suggest.generate_suggestions()
                        self.assertTrue(any("Watch `mediocre`" in s and "68%" in s for s in res))

    def test_infra_overhead_suggestion_when_high(self):
        fake_traj = {"infra_steps": {"cargo_check": 42, "setup_venv": 3}}

        with patch("agentforge.eval.suggest.generate_insights", return_value=[]):
            with patch("agentforge.eval.suggest.get_all_benchmarks_with_history", return_value=[]):
                with patch("agentforge.eval.suggest.load_trajectories", return_value=[{"dummy": 1}]):
                    with patch("agentforge.eval.suggest.analyze", return_value=fake_traj):
                        res = suggest.generate_suggestions(limit=6)
                        self.assertTrue(any("cargo_check" in s and "optimizing" in s.lower() for s in res))

    def test_fallback_suggestion_when_very_little_data(self):
        with patch("agentforge.eval.suggest.generate_insights", return_value=[]):
            with patch("agentforge.eval.suggest.get_all_benchmarks_with_history", return_value=[]):
                with patch("agentforge.eval.suggest.load_trajectories", return_value=[]):
                    with patch("agentforge.eval.suggest.analyze", return_value={}):
                        res = suggest.generate_suggestions(limit=4)
                        self.assertTrue(any("broader set of real benchmarks" in s for s in res))

    def test_limit_is_respected(self):
        with patch("agentforge.eval.suggest.generate_insights", return_value=["i1", "i2", "i3", "i4"]):
            with patch("agentforge.eval.suggest.get_all_benchmarks_with_history", return_value=[]):
                with patch("agentforge.eval.suggest.load_trajectories", return_value=[]):
                    res = suggest.generate_suggestions(limit=2)
                    self.assertEqual(len(res), 2)


class TestPrintSuggestions(unittest.TestCase):
    def test_print_suggestions_formats_numbered_list(self):
        fake = ["Do this first.", "Then consider that."]

        with patch("agentforge.eval.suggest.generate_suggestions", return_value=fake):
            captured = StringIO()
            old = sys.stdout
            sys.stdout = captured
            try:
                suggest.print_suggestions()
            finally:
                sys.stdout = old

            out = captured.getvalue()
            self.assertIn("=== Suggested Next Actions ===", out)
            self.assertIn("1. Do this first.", out)
            self.assertIn("2. Then consider that.", out)
            self.assertIn("These suggestions are generated from recent", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
