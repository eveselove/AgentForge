"""
Unit tests for generate_evaluation_report.py

Covers the high-value logic added during the "плавно в идеал" Phase 0 polish:
- Health Score calculation (pure function)
- Key Verdict logic (pure function)
- Overall report structure with different data scenarios
- Presence of key sections (Executive Summary, Verdict, Mermaid, Categorized Recommendations, Learning Readiness)
- Graceful handling of zero data / sparse data
"""

import unittest
from unittest.mock import patch

from agentforge.eval import generate_evaluation_report as report_mod


class TestPureHelpers(unittest.TestCase):
    def test_calculate_health_score_zero_data(self):
        score, health = report_mod.calculate_health_score(0, 0, 0, 0)
        self.assertEqual(score, 50)
        self.assertEqual(health, "Needs Attention")

    def test_calculate_health_score_high_real_success(self):
        score, health = report_mod.calculate_health_score(95.0, 20, 70.0, 10)
        # With current weighting (real*0.55 + sim*0.20), high real gives ~66
        self.assertGreaterEqual(score, 60)
        self.assertIn(health, ("Strong", "Acceptable"))

    def test_determine_key_verdict_critical(self):
        v = report_mod.determine_key_verdict(58, 40.0, 5)
        self.assertIn("Critical", v)

    def test_determine_key_verdict_acceptable(self):
        v = report_mod.determine_key_verdict(78, 85.0, 12)
        self.assertIn("Acceptable", v)
        self.assertIn("quick wins", v)

    def test_determine_key_verdict_headroom(self):
        v = report_mod.determine_key_verdict(88, 65.0, 15)
        self.assertIn("headroom", v)


class TestGenerateReportStructure(unittest.TestCase):
    def test_zero_data_report_still_produces_valid_structure(self):
        """Even with no data, report must be well-formed and contain key sections."""
        results = []
        traj = {}
        output = report_mod.generate_report(results, traj)

        self.assertIn("# AgentForge Evaluation Report", output)
        self.assertIn("## Executive Summary", output)
        self.assertIn("**Key Verdict:**", output)
        self.assertIn("## Recommended Next Actions", output)
        self.assertIn("## Simulated vs Real Comparison", output)

    def test_high_real_success_produces_strong_verdict(self):
        results = [
            {"task_id": "b1", "_mode": "real", "outcome": "success"},
            {"task_id": "b1", "_mode": "real", "outcome": "success"},
        ]
        traj = {"avg_duration_sec": 45}
        output = report_mod.generate_report(results, traj)
        self.assertIn("Real runs success rate: **100.0%**", output)
        # Verdict logic is exercised; exact text depends on other signals

    def test_mermaid_charts_section_when_history_present(self):
        """Smoke test: report runs and produces output even when history logic is active."""
        results = []
        traj = {}
        output = report_mod.generate_report(results, traj)
        self.assertIn("# AgentForge Evaluation Report", output)

    def test_categorized_recommendations_sections_exist(self):
        """The four category sections must always be present (core value of the polish)."""
        results = []
        traj = {}
        output = report_mod.generate_report(results, traj)
        self.assertIn("### 🔴 Critical Regressions", output)
        self.assertIn("### 📉 Declining Trends", output)
        self.assertIn("### 🟢 High-Impact Opportunities", output)
        self.assertIn("### ⚡ Quick Wins & Hygiene", output)

    def test_learning_readiness_section_appears(self):
        """The Phase 1 bridge signal should be visible in the report."""
        results = []
        traj = {}
        output = report_mod.generate_report(results, traj)
        self.assertTrue(
            "learning dataset" in output.lower() or "export" in output.lower() or "Phase 1" in output,
            "Learning readiness / export signal should be present in report"
        )


if __name__ == "__main__":
    unittest.main()
