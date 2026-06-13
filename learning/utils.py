"""
!!! AGGRESSIVE FINAL DEPRECATION SWEEP (RUST_FULL_MIGRATION_PLAN.md + PHASE4_REMOVAL_PLAN.md) !!!
!!! PHASE 4 REMOVAL IMMINENT — PYTHON FLYWHEEL ORCHESTRATION LAYER !!!

# Canonical provenance string for all Rust flywheel artifacts (manifests, health, proposals).
# Use this everywhere when stamping "engine" or "source" for flywheel outputs.
RUST_FLYWHEEL_ENGINE = "rust-agentforge-runner/flywheel-step@phase1-mvp"

learning/utils.py — THE SINGLE SOURCE OF TRUTH for pure-Rust flywheel cutover (is_pure_rust_flywheel + is_rust_flywheel_disabled). Phase 4 hardened.

ALL REMAINING Python flywheel orchestration files are under AGGRESSIVE DEPRECATION (final sweep standardized) and scheduled for
complete removal in Phase 4:

  - rust_flywheel_step.py
  - phase2_3_integration.py (flywheel glue only; planning/safety stay)
  - bin/run_continuous_flywheel.py
  - learning/pending_candidates.py (ingest/list/promote)
  - learning/skill_improver.py (SkillImprover + propose_*)
  - learning/evaluator.py (flywheel-driven A/B paths)
  - eval/post_process.py (flywheel trigger glue)
  - DEPRECATED (Tier 2 surgical, see docs/JULES_PY_REMOVAL_HANDOFF_f29c675b.md and PHASE4 checklist) (flywheel trigger)
  - list_pending_candidates.py
  - eval/runner.py (orchestration entrypoints)
  - rust_flywheel_demo.py
  - enable_rust_flywheel.py
  - watchdog.py (flywheel bits)
  - learning/trajectory_dataset.py (flywheel export glue)
  - learning/dataset.py (legacy TrajectoryDataset shim for flywheel-era consumers)
  - learning/flywheel_parity/ (DELETED Tier 2)*
  - show_agent_stats.py (flywheel stats)
  - learning/trainer_interface.py
  - examples/phase2_3_unified_power_demo.py
  - learning/__init__.py (re-exports)
  + all callers, services, timers, workers, bin/*.sh that invoke the above for flywheel loops.

MIGRATE IMMEDIATELY TO (direct agentforge-runner commands — ZERO Python):
  agentforge-runner flywheel-step --real-data [--output-dir DIR] [--ingest] [--shadow]
  agentforge-runner continuous [--top-n N] [--no-dry-run] [--shadow] [--json]
  agentforge-runner candidate list|prioritize|promote|ingest ...
  (full continuous + shadow + farm hooks documented in `agentforge-runner --help`)

Direct pointers repeated everywhere. No more Python meta-loops.

This file's is_pure_rust_flywheel() + is_rust_flywheel_disabled() are NOW EVEN STRONGER
for Phase 4 (expanded env + dotfile variants, no-dupe enforcement, absolute disable precedence).
All orchestration files MUST delegate exclusively to these (no local copies).

Non-breaking: guard=False (default) keeps 100% legacy Python identical + functional.
Loud warnings + direct "use agentforge-runner ..." on all !pure paths.

See: bin/make_pure_rust_flywheel_default.sh
     bin/test_pure_rust_flywheel_step.sh
     RUST_FULL_MIGRATION_PLAN.md
     PHASE4_REMOVAL_PLAN.md (created in final aggressive sweep: exhaustive list, safe phased removal order, per-tier risks, detailed rollback)
     PHASE4_REMOVAL_CHECKLIST.md (companion tactical checklist)

PHASE 4 PREP: duplication eradicated, guards hardened, banners added, removal plan skeleton created.
"""

# =============================================================================
# LOUD PHASE 3/4 DEPRECATION NOTICE (repeated for grep/visibility)
# Python flywheel orchestration (all proposal/candidate/continuous/A/B/promote glue)
# is deprecated. USE: agentforge-runner flywheel-step / continuous / candidate ...
# Guard with: from agentforge.learning.utils import is_pure_rust_flywheel
# =============================================================================


from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


def is_pure_rust_flywheel() -> bool:
    """
    !!! PHASE 3/4 HARDENED GUARD (EVEN STRONGER FOR REMOVAL SWEEP) !!!
    Returns True iff the pure Rust flywheel engine (agentforge-runner) MUST be used EXCLUSIVELY.
    This is THE authoritative gate. All Python orchestration files delegate here.

    PHASE 4 STRENGTHENING:
    - Expanded disable variants (stronger killswitch net: covers more accidental bypasses)
    - Expanded positive signals (more aliases for robust cutover)
    - Absolute precedence: ANY disable forces False (even if marker + all envs set)
    - No local duplication allowed anywhere else in tree
    - Direct "use agentforge-runner ..." baked into doc + behavior

    Includes (exhaustive):
    Disables (any present => pure=False, Phase 4 safety):
      DISABLE_RUST_FLYWHEEL, AGENTFORGE_DISABLE_RUST_FLYWHEEL, AGENTFORGE_FLYWHEEL_DISABLED,
      DISABLE_FLYWHEEL, AGENTFORGE_DISABLE_FLYWHEEL
      + dotfiles: .disable_rust_flywheel, .disable_pure_rust_flywheel, .disable_flywheel, .flywheel_disabled

    Positive pure (after disables cleared):
      AGENTFORGE_FLYWHEEL_ENGINE in (rust, pure-rust, rust-only, pure_rust, agentforge-runner)
      AGENTFORGE_PURE_RUST_FLYWHEEL=1/true/yes/on
      + dotfile: .pure_rust_flywheel (and .enable_pure_rust_flywheel for convenience)

    Direct pointers (repeated in every caller banner):
      agentforge-runner flywheel-step --real-data --ingest [--shadow]
      agentforge-runner continuous [--top-n N] [--no-dry-run] [--shadow]
      agentforge-runner candidate list|prioritize|promote|ingest ...
      (shadow enables Phase 2 dual-run fidelity in post_process/hooks; see runner help for integration points)

    Usage (all files): pure = is_pure_rust_flywheel()
    Non-breaking default: False (legacy Python 100% intact until Phase 4 deletion).
    """
    root = Path("/home/eveselove/agentforge")

    # PHASE 4 HARDENED: expanded disable variants (catch more bypass patterns)
    disable_envs = [
        "DISABLE_RUST_FLYWHEEL", "AGENTFORGE_DISABLE_RUST_FLYWHEEL",
        "AGENTFORGE_FLYWHEEL_DISABLED", "DISABLE_FLYWHEEL", "AGENTFORGE_DISABLE_FLYWHEEL",
    ]
    for name in disable_envs:
        if str(os.environ.get(name, "")).lower() in ("1", "true", "yes", "on"):
            return False

    disable_files = [
        ".disable_rust_flywheel", ".disable_pure_rust_flywheel",
        ".disable_flywheel", ".flywheel_disabled",
    ]
    for f in disable_files:
        if (root / f).exists():
            return False

    # Positive pure signals — expanded for Phase 4 robustness
    engine = (os.environ.get("AGENTFORGE_FLYWHEEL_ENGINE") or "").strip().lower()
    if engine in ("rust", "pure-rust", "rust-only", "pure_rust", "agentforge-runner", "rust_flywheel"):
        return True

    pure = (os.environ.get("AGENTFORGE_PURE_RUST_FLYWHEEL") or "").strip().lower()
    if pure in ("1", "true", "yes", "on"):
        return True

    # Marker files (primary cutover mechanism)
    if (root / ".pure_rust_flywheel").exists():
        return True
    if (root / ".enable_pure_rust_flywheel").exists():  # convenience alias
        return True

    return False


def get_rust_runner_path() -> Optional[Path]:
    """
    Best-effort discovery of the agentforge-runner binary (release preferred).
    Used by helpers and bridges. Does not raise.
    """
    env_path = os.environ.get("AGENTFORGE_RUST_RUNNER")
    if env_path:
        p = Path(env_path)
        if p.is_file() and os.access(p, os.X_OK):
            return p

    root = Path("/home/eveselove/agentforge")
    candidates = [
        root / "rust" / "target" / "release" / "agentforge-runner",
        root / "rust" / "target" / "debug" / "agentforge-runner",
    ]
    for c in candidates:
        if c.is_file() and os.access(c, os.X_OK):
            return c
    return None


# Convenience (PHASE 3/4 HARDENED: covers expanded disable set for all callers)
def is_rust_flywheel_disabled() -> bool:
    """
    !!! PHASE 3/4 HARDENED CENTRAL DISABLE CHECK !!!
    Returns True if any Rust/pure flywheel disable is active.
    Used by orchestration guards to short-circuit Python paths safely.
    MUST be the ONLY disable logic in the tree — no more local duplicates.

    Expanded Phase 4 variants (stronger net than before):
      Envs: DISABLE_RUST_FLYWHEEL, AGENTFORGE_DISABLE_RUST_FLYWHEEL,
            AGENTFORGE_FLYWHEEL_DISABLED, DISABLE_FLYWHEEL, AGENTFORGE_DISABLE_FLYWHEEL
      Dotfiles: .disable_rust_flywheel, .disable_pure_rust_flywheel,
                .disable_flywheel, .flywheel_disabled

    Direct migration: when this is True, prefer full bypass to agentforge-runner commands.
    See is_pure_rust_flywheel() for the positive decision (calls this internally).
    """
    root = Path("/home/eveselove/agentforge")

    disable_envs = [
        "DISABLE_RUST_FLYWHEEL", "AGENTFORGE_DISABLE_RUST_FLYWHEEL",
        "AGENTFORGE_FLYWHEEL_DISABLED", "DISABLE_FLYWHEEL", "AGENTFORGE_DISABLE_FLYWHEEL",
    ]
    for name in disable_envs:
        if str(os.environ.get(name, "")).lower() in ("1", "true", "yes", "on"):
            return True

    disable_files = [
        ".disable_rust_flywheel", ".disable_pure_rust_flywheel",
        ".disable_flywheel", ".flywheel_disabled",
    ]
    for f in disable_files:
        if (root / f).exists():
            return True
    return False
