#!/usr/bin/env python3
"""
!!! AGGRESSIVE FINAL DEPRECATION SWEEP (RUST_FULL_MIGRATION_PLAN.md + PHASE4_REMOVAL_PLAN.md) !!!
!!! PHASE 4 REMOVAL TARGET: enable_rust_flywheel.py (Python flywheel enable shim / glue) !!!
DEPRECATED as orchestration entrypoint / activator. This Python module sets env + patches for
enabling Rust-powered flywheel from Python callers during transition ONLY.

Replaced exclusively by: direct env vars in services/timers, the bin/make_pure_rust_flywheel_default.sh + disable_* (the cutover/rollback weapons), and eventual Rust-native.
Services like agentforge-flywheel.* now prefer pure Rust via agentforge-runner.

Import still works (non-breaking during soak) but:
- Prefer setting AGENTFORGE_RUST_FLYWHEEL=1 etc directly or via the .sh enablers + make_pure.
- When is_pure_rust_flywheel() from learning/utils.py, Python orchestration is short-circuited in favor of agentforge-runner flywheel-step/continuous/candidate.
- Central guard ONLY: no local is_pure... logic anywhere (sweep verified).

This file is Tier 1 removal candidate (low risk shim). See full:
- PHASE4_REMOVAL_PLAN.md (exhaustive targets, safe tiered order, risks, 5-layer rollback via .disable_pure_rust_flywheel + env + git pre-tag + services)
- PHASE4_REMOVAL_CHECKLIST.md (tactical per-file deletion criteria + verification)
- learning/utils.py (THE source of truth guard, Phase 4 hardened with expanded env/dotfile killswitches, absolute precedence)

(Part of final aggressive deprecation sweep in FULL AUTONOMOUS MAXIMUM MODE: uniform loud banners + direct pointers + crystal-clear safe removal path everywhere.)

Tiny, robust, idempotent activation for the live Rust flywheel on the AgentForge farm.

Import at the very top of any Python entry (or via python -c from shell scripts)
to guarantee:

  AGENTFORGE_RUST_FLYWHEEL=1
  AGENTFORGE_USE_RUST=1
  AGENTFORGE_RUST_RUNNER=... (auto-detected debug or release binary)

- Checks binary existence with helpful build hint.
- Idempotent runtime patch of post_process.post_process_task (forces env + calls through).
- Safe to import multiple times / from workers / dispatcher / eval.
- Also usable as script: python -m agentforge.enable_rust_flywheel

Designed for one-command whole-farm enable (see ENABLE_RUST_FLYWHEEL.md and the .sh wrapper).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional


ROOT = Path("/home/agx/agentforge")
DEFAULT_DEBUG = ROOT / "rust/target/debug/agentforge-runner"
DEFAULT_RELEASE = ROOT / "rust/target/release/agentforge-runner"


def _discover_runner() -> str:
    env_val = os.environ.get("AGENTFORGE_RUST_RUNNER")
    if env_val and Path(env_val).exists():
        return env_val
    if DEFAULT_RELEASE.exists():
        return str(DEFAULT_RELEASE)
    if DEFAULT_DEBUG.exists():
        return str(DEFAULT_DEBUG)
    # fallback to debug path (will warn later)
    return str(DEFAULT_DEBUG)


def activate(
    *,
    force: bool = False,
    patch_post_process: bool = True,
    quiet: bool = False,
) -> bool:
    """
    Activate Rust flywheel for this process + children.

    Idempotent: safe to call repeatedly.
    Returns True if activation performed (or already active).
    """
    already = (
        os.environ.get("AGENTFORGE_RUST_FLYWHEEL") == "1"
        and os.environ.get("AGENTFORGE_USE_RUST") == "1"
    )

    if force or not already:
        os.environ["AGENTFORGE_RUST_FLYWHEEL"] = "1"
        os.environ["AGENTFORGE_USE_RUST"] = "1"

    runner = _discover_runner()
    if not os.environ.get("AGENTFORGE_RUST_RUNNER"):
        os.environ["AGENTFORGE_RUST_RUNNER"] = runner

    if not quiet:
        print(f"[enable_rust_flywheel] AGENTFORGE_RUST_FLYWHEEL=1 AGENTFORGE_USE_RUST=1")
        print(f"[enable_rust_flywheel] runner: {os.environ['AGENTFORGE_RUST_RUNNER']}")

    # Binary check (robust)
    bin_path = Path(os.environ["AGENTFORGE_RUST_RUNNER"])
    if not bin_path.is_file():
        msg = (
            f"[enable_rust_flywheel] WARNING: binary not found at {bin_path}\n"
            f"  Build with:  cd /home/agx/agentforge/rust && cargo build -p agentforge-runner --release\n"
            f"  (or --debug for faster iteration)"
        )
        if not quiet:
            print(msg, file=sys.stderr)
        # Do not fail activation; flywheel gracefully degrades in Python paths
    else:
        if not quiet:
            print(f"[enable_rust_flywheel] binary OK ({bin_path.stat().st_size} bytes)")

    # Idempotent post_process patch (monkey-patch to guarantee env + future-proofing)
    if patch_post_process:
        try:
            # Ensure package on path (when imported from arbitrary cwd)
            pkg_parent = ROOT.parent
            if str(pkg_parent) not in sys.path:
                sys.path.insert(0, str(pkg_parent))

            import agentforge.eval.post_process as pp  # type: ignore

            if not getattr(pp, "_rust_flywheel_enable_patched", False):
                orig = pp.post_process_task

                def _patched_post_process_task(task_id: str, *a, **k):
                    # Guarantee the flywheel envs right before any post-process
                    os.environ.setdefault("AGENTFORGE_RUST_FLYWHEEL", "1")
                    os.environ.setdefault("AGENTFORGE_USE_RUST", "1")
                    if os.environ.get("AGENTFORGE_RUST_RUNNER"):
                        # propagate if set
                        pass
                    return orig(task_id, *a, **k)

                pp.post_process_task = _patched_post_process_task  # type: ignore
                pp._rust_flywheel_enable_patched = True  # type: ignore[attr-defined]
                if not quiet:
                    print("[enable_rust_flywheel] idempotent patch applied to post_process.post_process_task")
        except Exception as e:
            if not quiet:
                print(f"[enable_rust_flywheel] post_process patch skipped (non-fatal): {e}")

    if not quiet:
        print("[enable_rust_flywheel] ACTIVATED — next real task completions will feed Rust learning flywheel.")

    return True


# Auto-activate only when explicitly requested (never by surprise on plain import)
if os.environ.get("AGENTFORGE_AUTO_ENABLE_RUST_FLYWHEEL", "0") == "1":
    activate(quiet=True)


def main() -> int:
    import argparse

    p = argparse.ArgumentParser(description="Enable AgentForge Rust flywheel (one-shot or importable)")
    p.add_argument("--force", action="store_true", help="Force re-set env even if already 1")
    p.add_argument("--no-patch", action="store_true", help="Skip the post_process monkey-patch")
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args()

    ok = activate(force=args.force, patch_post_process=not args.no_patch, quiet=args.quiet)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
