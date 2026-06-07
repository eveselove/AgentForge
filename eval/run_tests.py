#!/usr/bin/env python3
"""
Convenience runner for the Evaluation Framework test suite (23 tests).

This makes it trivial to run the full hermetic test battery from anywhere:

    python -m agentforge.eval.run_tests
    # or
    python agentforge/eval/run_tests.py

All tests use mocks and never touch real files, AgentForge API, or external services.
"""

import sys
import unittest
from pathlib import Path

# Robust path setup so the runner works in all common invocation styles:
#   1. python -m agentforge.eval.run_tests          (from /home/eveselove)
#   2. python eval/run_tests.py                     (from inside agentforge/)
#   3. python -m agentforge.eval.run_tests          (from inside agentforge/ — falls back)
HERE = Path(__file__).resolve().parent          # .../agentforge/eval
AGENTFORGE_ROOT = HERE.parent                   # .../agentforge

# Try several candidates
candidates = [
    AGENTFORGE_ROOT,                     # normal case
    AGENTFORGE_ROOT.parent,              # if we are deeper
    Path.cwd().parent if (Path.cwd() / "agentforge").exists() else None,
    Path.cwd(),
]
for cand in candidates:
    if cand and (cand / "agentforge" / "eval").exists():
        if str(cand) not in sys.path:
            sys.path.insert(0, str(cand))
        break

# Last-resort: if 'agentforge' still not importable, add parent of cwd
try:
    import agentforge  # noqa
except ImportError:
    if str(Path.cwd().parent) not in sys.path:
        sys.path.insert(0, str(Path.cwd().parent))

if __name__ == "__main__":
    print("Running AgentForge Evaluation Framework tests (23 hermetic tests)...\n")
    loader = unittest.TestLoader()
    suite = loader.discover(str(HERE / "tests"), pattern="test_*.py")
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    print("\n" + "=" * 60)
    if result.wasSuccessful():
        print("✅ ALL TESTS PASSED (23/23)")
        sys.exit(0)
    else:
        print(f"❌ SOME TESTS FAILED ({len(result.failures)} failures, {len(result.errors)} errors)")
        sys.exit(1)
