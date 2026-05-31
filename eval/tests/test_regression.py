"""
Unit tests for regression.py

Covers:
- Core regression detection logic with synthetic history
- Edge cases (insufficient data, zero baseline, single benchmark filter)
- has_regressions helper
- Human formatting helper

All tests are hermetic: they monkey-patch history loading and never touch real FS.
"""

import unittest
from unittest.mock import patch
from typing import List, Dict, Any

# Import the module under test (works when run as part of package or with PYTHONPATH)
from agentforge.eval import regression


def _make_run(outcome: str, ts_offset: int = 0) -> Dict[str, Any]:
    """Helper to build a minimal history record."""
    return {
        "timestamp": f"2026-05-0{1 + ts_offset}T00:00:00Z",
        "benchmark_id": "test_bench",
        "agent": "grok",
        "outcome": outcome,
        "duration_seconds": 12.3,
    }


class TestDetectRegressions(unittest.TestCase):
    """Test the main detect_regressions function."""

    def test_returns_empty_when_no_benchmarks(self):
        with patch("agentforge.eval.regression.get_all_benchmarks_with_history", return_value=[]):
            with patch("agentforge.eval.regression.load_history", return_value=[]):
                result = regression.detect_regressions()
                self.assertEqual(result, [])

    def test_skips_benchmark_with_insufficient_history(self):
        # Need at least window + 5 = 13 records for default window=8
        short_history = [_make_run("success") for _ in range(10)]
        with patch("agentforge.eval.regression.get_all_benchmarks_with_history", return_value=["short"]):
            with patch("agentforge.eval.regression.load_history", return_value=short_history):
                result = regression.detect_regressions(window=8)
                self.assertEqual(result, [])

    def test_detects_regression_when_recent_drop_exceeds_threshold(self):
        # Build history: first many successes (baseline), then recent failures
        # total needed > window + baseline_window
        baseline = [_make_run("success", i) for i in range(20)]  # old
        recent_fail = [_make_run("failed", 20 + i) for i in range(8)]
        history = baseline + recent_fail

        with patch("agentforge.eval.regression.get_all_benchmarks_with_history", return_value=["perf_drop"]):
            with patch("agentforge.eval.regression.load_history", return_value=history):
                regs = regression.detect_regressions(window=8, baseline_window=20, threshold=0.15)

        self.assertEqual(len(regs), 1)
        r = regs[0]
        self.assertEqual(r["benchmark_id"], "perf_drop")
        self.assertGreaterEqual(r["absolute_drop"], 0.15)
        self.assertLess(r["recent_rate"], r["baseline_rate"])
        self.assertGreater(r["relative_drop"], 0)

    def test_no_regression_when_stable_or_improving(self):
        # All successes -> no drop
        good_history = [_make_run("success", i) for i in range(30)]

        with patch("agentforge.eval.regression.get_all_benchmarks_with_history", return_value=["stable"]):
            with patch("agentforge.eval.regression.load_history", return_value=good_history):
                regs = regression.detect_regressions(threshold=0.15)
                self.assertEqual(regs, [])

    def test_specific_benchmark_id_filter(self):
        history = [_make_run("success", i) for i in range(30)]

        with patch("agentforge.eval.regression.load_history", return_value=history) as mock_load:
            # Should only query the requested one, never call get_all
            regs = regression.detect_regressions(benchmark_id="only_this", window=5, baseline_window=10)
            mock_load.assert_called_once_with("only_this")
            self.assertEqual(regs, [])  # no drop in this synthetic case

    def test_handles_zero_baseline_rate_gracefully(self):
        # All failures in baseline + recent worse (edge)
        baseline = [_make_run("failed", i) for i in range(15)]
        recent = [_make_run("failed", 15 + i) for i in range(8)]
        history = baseline + recent

        with patch("agentforge.eval.regression.get_all_benchmarks_with_history", return_value=["zero_base"]):
            with patch("agentforge.eval.regression.load_history", return_value=history):
                regs = regression.detect_regressions(threshold=0.10)
                # Should not crash; relative_drop becomes 0 when baseline_rate == 0
                if regs:
                    self.assertEqual(regs[0]["relative_drop"], 0)

    def test_sorts_by_absolute_drop_descending(self):
        # Two benchmarks, one with bigger drop (more recent failures)
        def make_history(num_recent_success: int):
            """baseline ~15 successes, recent window has varying # of successes."""
            baseline = [_make_run("success")] * 15
            # recent 8 runs: first N success, rest failed -> different recent_rate
            recent = [_make_run("success")] * num_recent_success + [_make_run("failed")] * (8 - num_recent_success)
            return baseline + recent

        def fake_load(bid):
            if bid == "big_drop":
                # 0 successes in recent -> big drop (15/15 -> 0/8)
                return make_history(0)
            else:
                # 5/8 successes in recent -> smaller drop
                return make_history(5)

        with patch("agentforge.eval.regression.get_all_benchmarks_with_history", return_value=["big_drop", "small_drop"]):
            with patch("agentforge.eval.regression.load_history", side_effect=fake_load):
                regs = regression.detect_regressions(window=8, baseline_window=10, threshold=0.05)

        self.assertEqual(len(regs), 2)
        self.assertEqual(regs[0]["benchmark_id"], "big_drop")
        self.assertGreater(regs[0]["absolute_drop"], regs[1]["absolute_drop"])


class TestHasRegressions(unittest.TestCase):
    def test_returns_bool(self):
        with patch("agentforge.eval.regression.detect_regressions", return_value=[]):
            self.assertFalse(regression.has_regressions())

        with patch("agentforge.eval.regression.detect_regressions", return_value=[{"foo": "bar"}]):
            self.assertTrue(regression.has_regressions(threshold=0.2))


class TestFormatRegression(unittest.TestCase):
    def test_human_readable_output(self):
        reg = {
            "benchmark_id": "my_bench",
            "baseline_rate": 0.92,
            "recent_rate": 0.65,
            "absolute_drop": 0.27,
            "relative_drop": 0.293,
            "recent_runs": 8,
            "baseline_runs": 20,
        }
        line = regression.format_regression(reg)
        self.assertIn("my_bench", line)
        self.assertIn("92%", line)
        self.assertIn("65%", line)
        self.assertIn("27pp", line)
        self.assertIn("29%", line)


if __name__ == "__main__":
    unittest.main(verbosity=2)
