"""
Quick tests for the Phase 1 unified trajectory loader + viewer.
These are intentionally light but verify the core happy paths on real artifacts.
"""

import unittest
from pathlib import Path
from agentforge.eval.trajectory import load_trajectory, find_trajectory_file, normalize_event
from agentforge.eval.trajectory_viewer import summarize, generate_html


class TestTrajectoryLoader(unittest.TestCase):
    def test_load_real_trajectory_by_partial_id(self):
        # Uses one of the real .jsonl files in the repo
        traj = load_trajectory("f12a11c0", include_prm=True)
        if not traj or not traj.get("events"):
            self.skipTest("No easily parsable real artifact available in this run")
        self.assertIsInstance(traj, dict)
        self.assertIn("events", traj)
        # Normalized shape (at least some events should be normalized)
        normalized = [ev for ev in traj["events"] if "data" in ev]
        self.assertGreater(len(normalized), 0)

    def test_find_trajectory_works(self):
        p = find_trajectory_file("f12a11c0")
        self.assertIsNotNone(p)
        self.assertTrue(Path(p).exists())

    def test_normalize_event_legacy_flat(self):
        raw = {"ts": "2026-05-31T12:00:00Z", "type": "tool_call", "tool": "ls", "duration_ms": 120}
        norm = normalize_event(raw)
        self.assertEqual(norm["type"], "tool_call")
        self.assertIn("tool", norm["data"])
        self.assertEqual(norm["data"]["duration_ms"], 120)


class TestTrajectoryViewer(unittest.TestCase):
    def test_summarize_runs_without_crash(self):
        traj = load_trajectory("f12a11c0", include_prm=True)
        text = summarize(traj)
        self.assertIn("AgentForge Trajectory View", text)
        self.assertIn("f12a11c0", text)

    def test_generate_html_produces_file(self):
        traj = load_trajectory("f12a11c0", include_prm=True)
        if not traj or not traj.get("events"):
            self.skipTest("No suitable artifact for HTML generation test")
        out = generate_html(traj, output_path="/tmp/test_traj_view.html", include_prm=True)
        self.assertTrue(Path(out).exists())
        self.assertGreater(Path(out).stat().st_size, 3000)


if __name__ == "__main__":
    unittest.main()
