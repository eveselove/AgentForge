#!/usr/bin/env python3
"""
!!! AGGRESSIVE FINAL DEPRECATION SWEEP (RUST_FULL_MIGRATION_PLAN.md + PHASE4_REMOVAL_PLAN.md) !!!
pending_candidates.py (ingest/list/promote + all Python store logic) heavily deprecated.
Replaced by native in agentforge-runner (candidate subcommands + candidates crate).
All entrypoints now emit Phase 3 warnings when !is_pure_rust_flywheel().
Strong central guard from utils. Non-breaking shim.

pending_candidates.py — Central storage + listing + promotion for flywheel candidates.

!!! AGGRESSIVE FINAL DEPRECATION SWEEP (RUST_FULL_MIGRATION_PLAN.md + PHASE4_REMOVAL_PLAN.md) !!!
!!! PYTHON PENDING_CANDIDATES STORE/INGEST/LIST/PROMOTE DEPRECATED — PHASE 4 DELETE TARGET !!!
MIGRATE TO DIRECT: agentforge-runner candidate list|prioritize|promote|ingest ...

Guard with Phase 4 hardened central ONLY (no local bypasses):
  from .utils import is_pure_rust_flywheel

All Python paths emit loud warnings. Non-breaking for !pure.
This module's orchestration is scheduled for complete removal in Phase 4.

See learning/utils.py (even stronger guards + full list of deprecated files)
See PHASE4_REMOVAL_PLAN.md (final aggressive deprecation sweep deliverable: full removal order, risks, rollback)
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import warnings

# Phase 0/3: central pure-Rust cutover (STRENGTHENED in final sweep)
from .utils import is_pure_rust_flywheel

# Central configurable location (env override supported)
PENDING_DIR = Path(
    os.environ.get(
        "AGENTFORGE_PENDING_CANDIDATES_DIR",
        os.environ.get("AGENTFORGE_PENDING_CANDIDATES", "/home/eveselove/agentforge/pending_candidates"),
    )
)
PENDING_DIR.mkdir(parents=True, exist_ok=True)

# Mirror the skills location logic for promote stub (no circular import)
SKILLS_DIR = Path(
    os.environ.get("AGENTFORGE_SKILLS_DIR", str(Path(__file__).parent.parent / "skills"))
)


def _short_hash(data: str, length: int = 8) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()[:length]


def _candidate_subdir_name(ts: str, skill: str, proposal_dict: Dict[str, Any]) -> str:
    """timestamp + skill + content hash for stable unique naming."""
    # Hash over key proposal content so identical proposals don't collide on re-runs but similar data gives stable ids
    core = json.dumps(
        {
            "skill": skill,
            "rationale": proposal_dict.get("overall_rationale", ""),
            "prompt_head": (proposal_dict.get("new_system_prompt") or "")[:120],
            "proposals": [p.get("rationale", "") for p in proposal_dict.get("proposals", [])[:2]],
        },
        sort_keys=True,
    )
    h = _short_hash(core)
    safe_skill = "".join(c if c.isalnum() or c in "-_" else "_" for c in skill)[:32]
    return f"{ts}_{safe_skill}_{h}"


def ingest_flywheel_artifacts(
    artifacts_dir: Path | str,
    proposal_dict: Dict[str, Any],
    *,
    ts: Optional[str] = None,
    also_symlink: bool = False,
) -> Path:
    """
    The key integration point.
    Called automatically after every canonical rust_flywheel_step write_artifacts.
    Copies (or symlinks) the canonical artifacts (yaml + json + manifest) into
    pending_candidates/ under a clear timestamp_skill_hash/ subdir.

    # Phase 1 migration note (see RUST_FULL_MIGRATION_PLAN.md)
    if is_pure_rust_flywheel():
        warnings.warn(
            "ingest_flywheel_artifacts is deprecated in pure Rust mode. "
            "Prefer direct Rust `flywheel-step` + future candidate store.",
            DeprecationWarning,
            stacklevel=2,
        )
        return Path(artifacts_dir)  # no-op for now under pure Rust path


    DEPRECATION (Phase 0/3 FINAL per RUST_FULL_MIGRATION_PLAN.md):
        This Python pending_candidates store/ingest is heavily deprecated.
        Replaced by pure Rust `agentforge-runner candidate ...` + native store.
        Use is_pure_rust_flywheel() (stronger guard).
    """
    if not is_pure_rust_flywheel():
        warnings.warn(
            "learning.pending_candidates (ingest + Python store) is deprecated per "
            "RUST_FULL_MIGRATION_PLAN.md PHASE 3. Prefer agentforge-runner candidate list|ingest|promote. "
            "Non-breaking for !pure.",
            DeprecationWarning,
            stacklevel=2,
        )

    artifacts_dir = Path(artifacts_dir)
    if ts is None:
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

    skill = proposal_dict.get("skill", "unknown-skill")
    subdir_name = _candidate_subdir_name(ts, skill, proposal_dict)
    dest = PENDING_DIR / subdir_name
    dest.mkdir(parents=True, exist_ok=True)

    # The canonical artifacts from rust_flywheel_step - now includes richer flywheel-export bundle when Rust rich path used
    key_files = [
        "candidate_skill.yaml",
        "proposal.json",
        "flywheel_manifest.json",
        "rust_pairs_sample.jsonl",
        "rust_rich_flywheel_export.json",
    ]

    copied = []
    for fname in key_files:
        src = artifacts_dir / fname
        if src.exists():
            dst = dest / fname
            if also_symlink:
                try:
                    if dst.exists() or dst.is_symlink():
                        dst.unlink()
                    dst.symlink_to(src.resolve())
                except Exception:
                    shutil.copy2(src, dst)  # fallback
            else:
                shutil.copy2(src, dst)
            copied.append(fname)

    # Canonical per-candidate metadata for easy listing / promotion
    meta = {
        "candidate_id": subdir_name,
        "timestamp": ts,
        "skill": skill,
        "estimated_impact": proposal_dict.get("estimated_impact", "medium"),
        "rust_pairs_used": proposal_dict.get("rust_pairs_used", 0),
        "high_learning_value_records": proposal_dict.get("high_learning_value_records", 0),
        "source_artifacts": str(artifacts_dir),
        "generated_by": "rust_flywheel_step + agentforge-runner (rich flywheel-export preferred)",
        "copied_files": copied,
        "promoted": False,
        "reviewed": False,
    }

    # Auto-use richer data when the rich export bundle is present in artifacts (from direct flywheel-export)
    rich_p = artifacts_dir / "rust_rich_flywheel_export.json"
    if rich_p.exists():
        try:
            rich = json.loads(rich_p.read_text(encoding="utf-8"))
            stats = rich.get("stats") or {}
            meta["rich_flywheel_export_used"] = True
            meta["rich_record_count"] = rich.get("record_count") or stats.get("record_count")
            meta["rich_pairs_count"] = rich.get("pairs_count") or stats.get("pairs_count")
            meta["rich_success_rate"] = stats.get("success_rate")
            meta["rich_avg_learning_value"] = stats.get("avg_learning_value") or stats.get("avg_prm")
            meta["rich_high_value_count"] = stats.get("high_value_count")
            meta["rich_source"] = rich.get("source")
            meta["rich_export_version"] = rich.get("export_version")
            # If proposal didn't have high count, pull from rich
            if not meta.get("high_learning_value_records"):
                meta["high_learning_value_records"] = meta["rich_high_value_count"]
        except Exception as e:
            meta["rich_parse_warning"] = str(e)[:120]

    (dest / "candidate_meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Also drop a tiny README for humans in the candidate dir
    readme = f"""# Pending Flywheel Candidate: {subdir_name}

Skill: {skill}
Generated: {ts}
Impact: {meta['estimated_impact']}

This directory was auto-populated by the canonical Rust flywheel step.

Contents:
- candidate_skill.yaml : Ready-to-review proposed skill definition
- proposal.json        : Full rationale, new prompt, concrete changes
- flywheel_manifest.json : Reproducible stats + before/after simulation
- (optional) rust_pairs_sample.jsonl

Next: Use LearningEvaluator A/B test on this candidate, then promote via
  python -m agentforge.list_pending_candidates promote {subdir_name} --copy-to-skills
"""
    (dest / "README.md").write_text(readme, encoding="utf-8")

    print(f"[pending_candidates] Ingested Rust flywheel candidate → {dest}")
    return dest


# Back-compat with earlier stub
def drop_candidate(
    proposal: Dict[str, Any], candidate_yaml_path: Optional[str], artifacts_dir: str, run_id: Optional[str] = None
) -> Path:
    """Legacy shim - prefer ingest_flywheel_artifacts."""
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    if run_id:
        # Use provided run_id as subdir (may not be pretty)
        dest = PENDING_DIR / run_id
        dest.mkdir(parents=True, exist_ok=True)
        if candidate_yaml_path and Path(candidate_yaml_path).exists():
            shutil.copy2(candidate_yaml_path, dest / "candidate_skill.yaml")
        ppath = Path(artifacts_dir) / "proposal.json"
        if ppath.exists():
            shutil.copy2(ppath, dest / "proposal.json")
        (dest / "manifest.json").write_text(
            json.dumps({"legacy": True, "proposal": proposal}, indent=2), encoding="utf-8"
        )
        return dest
    # Delegate to new path
    return ingest_flywheel_artifacts(artifacts_dir, proposal, ts=ts)


def cleanup_old_flywheel_artifacts(max_age_hours: int = 48) -> int:
    """Robustness helper: purge old /tmp/agentforge_rust_flywheel/ ts-dirs (step artifacts)
    and stale rate files. Called automatically on step runs and listing to keep /tmp lean.
    Returns count cleaned. Safe, best-effort, never raises.
    """
    cleaned = 0
    state_dir = Path("/tmp/agentforge_rust_flywheel")
    if not state_dir.exists():
        return 0
    cutoff = time.time() - (max_age_hours * 3600)
    for p in list(state_dir.iterdir()):
        try:
            if p.stat().st_mtime < cutoff:
                if p.is_dir():
                    shutil.rmtree(p, ignore_errors=True)
                else:
                    p.unlink(missing_ok=True)
                cleaned += 1
        except Exception:
            pass
    return cleaned


def list_pending_candidates() -> List[Dict[str, Any]]:
    """Rich listing with parsed summaries from meta + proposal.

    TODO(Phase 0/3, RUST_FULL_MIGRATION_PLAN.md): superseded by `agentforge-runner candidate list`.
    """
    if not is_pure_rust_flywheel():
        warnings.warn(
            "learning.pending_candidates.list_pending_candidates is deprecated per "
            "RUST_FULL_MIGRATION_PLAN.md PHASE 3 FINAL. Use agentforge-runner candidate list.",
            DeprecationWarning,
            stacklevel=2,
        )
    candidates: List[Dict[str, Any]] = []
    for d in sorted([p for p in PENDING_DIR.iterdir() if p.is_dir()], key=lambda p: p.name, reverse=True):
        meta_p = d / "candidate_meta.json"
        proposal_p = d / "proposal.json"
        manifest_p = d / "flywheel_manifest.json"
        yaml_p = d / "candidate_skill.yaml"

        entry: Dict[str, Any] = {
            "candidate_id": d.name,
            "path": str(d),
            "has_yaml": yaml_p.exists(),
            "has_proposal": proposal_p.exists(),
            "has_manifest": manifest_p.exists(),
        }

        if meta_p.exists():
            try:
                entry.update(json.loads(meta_p.read_text(encoding="utf-8")))
            except Exception:
                pass

        if proposal_p.exists() and "skill" not in entry:
            try:
                p = json.loads(proposal_p.read_text(encoding="utf-8"))
                entry["skill"] = p.get("skill")
                entry["overall_rationale"] = p.get("overall_rationale", "")
                entry["estimated_impact"] = p.get("estimated_impact", entry.get("estimated_impact"))
                entry["rust_pairs_used"] = p.get("rust_pairs_used", entry.get("rust_pairs_used", 0))
            except Exception:
                pass

        if manifest_p.exists():
            try:
                m = json.loads(manifest_p.read_text(encoding="utf-8"))
                entry.setdefault("records_loaded", m.get("records_loaded"))
                entry.setdefault("before_success_rate", m.get("before_stats", {}).get("success_rate"))
            except Exception:
                pass

        candidates.append(entry)
    return candidates


def print_pending_summary(limit: int = 20, sort_by: str = "value") -> None:
    """Human readable summary for CLI and logs. Auto-triggers cleanup for robustness.
    sort_by: "value" (default: rich_avg_learning_value + lift potential first, for autonomy)
             or "recency" (dir name reverse).
    This small change makes high-learning-value candidates surface first, increasing
    visibility of best autonomous improvement opportunities.
    """
    # Small robustness: clean old artifacts on every listing (CLI users see lean /tmp)
    try:
        n_clean = cleanup_old_flywheel_artifacts(48)
        if n_clean:
            print(f"[pending_candidates] Auto-cleaned {n_clean} old artifact/rate files from /tmp (robustness)")
    except Exception:
        pass

    cands = list_pending_candidates()
    if sort_by == "value":
        def _lv_key(c: Dict[str, Any]) -> float:
            lv = float(c.get("rich_avg_learning_value") or c.get("avg_learning_value") or 0.0)
            hlv = int(c.get("high_learning_value_records") or c.get("rich_high_value_count") or 0)
            sr = float(c.get("rich_success_rate") or c.get("before_success_rate") or 0.5)
            # Lift potential: high value signals on lower-success batches = high priority for flywheel
            lift_pot = float(hlv) * (1.0 - sr) * max(lv, 0.05)
            # Secondary recency (newer names first) for stability
            name = c.get("candidate_id", "")
            ts = name.split("_")[0] if "_" in name else "0"
            return (lv * 100 + lift_pot, float(ts) if ts.isdigit() else 0.0)
        cands = sorted(cands, key=_lv_key, reverse=True)
    else:
        # recency (original)
        cands = sorted(cands, key=lambda p: p.get("candidate_id", ""), reverse=True)

    cands = cands[:limit]
    if not cands:
        print("[pending_candidates] No candidates yet in", PENDING_DIR)
        print("  Run: AGENTFORGE_RUST_FLYWHEEL=1 python -m agentforge.rust_flywheel_step --real-data --use-rust --no-env-guard")
        return

    print(f"\n=== PENDING FLYWHEEL CANDIDATES ({len(cands)} total, showing {min(limit, len(cands))}) ===")
    print(f"Location: {PENDING_DIR}")
    print(f"Sort: {sort_by} (learning_value + success_rate_lift_potential prioritized for continuous autonomy)")
    print("-" * 90)
    for c in cands:
        cid = c.get("candidate_id", c.get("path", "?"))
        skill = c.get("skill", "?")
        impact = c.get("estimated_impact", "?")
        pairs = c.get("rust_pairs_used", c.get("rust_pairs_exported", "?"))
        recs = c.get("records_loaded", c.get("high_learning_value_records", "?"))
        # Rich stats polish: surface real farm success_rate / learning_value from rich export or manifest
        succ = c.get("rich_success_rate") or c.get("before_success_rate")
        succ_str = f" succ={float(succ):.3f}" if succ is not None else ""
        avg_lv = c.get("rich_avg_learning_value")
        lv_str = f" avg_lv={float(avg_lv):.2f}" if avg_lv is not None else ""
        rat = (c.get("overall_rationale") or "")[:80].replace("\n", " ")
        reviewed = "reviewed" if c.get("reviewed") or (d := Path(c["path"])).joinpath(".reviewed").exists() else ""
        print(f"{cid}")
        print(f"  skill={skill}  impact={impact}  rust_pairs={pairs}  records={recs}{succ_str}{lv_str}  {reviewed}")
        if rat:
            print(f"  rationale: {rat}...")
        print()
    print("Next: feed any candidate into LearningEvaluator A/B, then `promote`.")
    print("=" * 90 + "\n")


def list_high_value_candidates(limit: int = 10, min_avg_lv: float = 0.0) -> List[Dict[str, Any]]:
    """Prioritizer for continuous autonomy: rank by learning_value + success_rate lift potential.
    Used by run_continuous_flywheel to select top candidates for auto promote-and-ab.
    Non-breaking addition; falls back gracefully if rich fields absent.
    """
    cands = list_pending_candidates()
    def _priority(c: Dict[str, Any]) -> float:
        lv = float(c.get("rich_avg_learning_value") or c.get("avg_learning_value") or 0.0)
        hlv = int(c.get("high_learning_value_records") or c.get("rich_high_value_count") or 0)
        sr = float(c.get("rich_success_rate") or c.get("before_success_rate") or 0.5)
        lift_pot = float(hlv) * (1.0 - sr) * max(lv, 0.05)
        return lv * 10.0 + lift_pot
    filtered = [c for c in cands if float(c.get("rich_avg_learning_value") or 0.0) >= min_avg_lv]
    filtered.sort(key=_priority, reverse=True)
    return filtered[:limit]


# =============================================================================
# A/B integration + safe promotion extensions (A/B skeleton on pending candidates)
# =============================================================================

DEFAULT_AB_BENCHMARKS: List[str] = [
    "example_rust_refactor",
    "lancedb_parser_bottleneck",
    "adaptive_throttle_tuning",
]


def _extract_source_skill(cand_path: Path) -> str:
    """Best-effort extraction of the base skill this candidate improves upon."""
    yaml_p = cand_path / "candidate_skill.yaml"
    if yaml_p.exists():
        try:
            import yaml  # type: ignore

            data = yaml.safe_load(yaml_p.read_text(encoding="utf-8")) or {}
            meta = data.get("_learning_meta") or {}
            src = meta.get("source_skill")
            if src:
                return str(src)
            # Fallback: if name looks like variant of something
            name = data.get("name", "")
            if "rust" in name.lower():
                return "rust-fix"
        except Exception:
            pass

    prop_p = cand_path / "proposal.json"
    if prop_p.exists():
        try:
            p = json.loads(prop_p.read_text(encoding="utf-8"))
            s = p.get("skill")
            if s:
                return str(s)
        except Exception:
            pass

    # Look in meta
    meta_p = cand_path / "candidate_meta.json"
    if meta_p.exists():
        try:
            m = json.loads(meta_p.read_text(encoding="utf-8"))
            if m.get("skill"):
                return str(m["skill"])
        except Exception:
            pass

    return "general-refactor"


def _generate_ab_artifacts(
    cand_path: Path,
    promoted_yaml: Optional[Path],
    source_skill: str,
    benchmarks: Optional[List[str]] = None,
    *,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Create a proper A/B test config + exact runnable command snippet + config file
    for LearningEvaluator integration on this candidate vs the current/base skill.
    Always safe / non-destructive. Writes artifacts into the candidate dir.
    """
    benchmarks = benchmarks or DEFAULT_AB_BENCHMARKS
    yaml_for_ab = promoted_yaml or (cand_path / "candidate_skill.yaml")
    cid = cand_path.name

    ab_config = {
        "test_name": f"ab-promote-{cid}",
        "candidate_id": cid,
        "old_skill": source_skill,
        "new_skill_or_prompt": str(yaml_for_ab),
        "benchmarks": benchmarks,
        "config": {
            "name": f"promote-ab-{cid}",
            "agent": "grok",
            "n_runs_per_arm": 1,
            "wait_for_real": False,
            "simulate": True,
            "use_temp_skill_files": True,
            "timeout_minutes": 30,
            "min_prm_threshold": None,
        },
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "how_to_run_real": "Set wait_for_real=True + simulate=False (and ensure eval runner + farm access)",
    }

    # Write machine readable A/B config (proper ABTestConfig shape + context)
    ab_cfg_path = cand_path / "ab_test_config.json"
    if not dry_run:
        ab_cfg_path.write_text(json.dumps(ab_config, indent=2, ensure_ascii=False), encoding="utf-8")

    # Exact copy-pasteable command / snippet for user or automation
    snippet = f'''#!/usr/bin/env python3
"""
Auto-generated A/B test harness for promoted candidate: {cid}
Run this (or the one-liner below) after promotion to validate vs baseline skill.
"""
from pathlib import Path
from learning.evaluator import LearningEvaluator, ABTestConfig

candidate_yaml = Path(r"{yaml_for_ab}")
old_skill = "{source_skill}"
benchmarks = {benchmarks!r}

print(f"[A/B] Running LearningEvaluator on candidate {cid}")
print(f"  old={source_skill}  new_yaml={yaml_for_ab}")

e = LearningEvaluator()
cfg = ABTestConfig(
    name="ab-after-promote-{cid}",
    agent="grok",
    n_runs_per_arm=1,
    wait_for_real=False,   # flip to True + simulate=False for REAL farm runs
    simulate=True,
    use_temp_skill_files=True,
    timeout_minutes=45,
)

result = e.ab_test_skill_versions(
    benchmark_ids=benchmarks,
    old_skill=old_skill,
    new_skill_or_prompt=str(candidate_yaml),
    config=cfg,
)

print("\\n" + result.summary())
print("Winner:", result.winner, "confidence:", result.confidence)
print("Deltas:", result.deltas)

# To persist: result.to_dict()  --> feed back to flywheel / history
# For real eval (production gate): edit above + re-run with real data.
'''

    ab_script_path = cand_path / "run_ab_after_promote.py"
    if not dry_run:
        ab_script_path.write_text(snippet, encoding="utf-8")
        try:
            ab_script_path.chmod(0o755)
        except Exception:
            pass

    # Human friendly one-liner + instructions
    oneliner = (
        f'python -c \''
        f'from learning.evaluator import LearningEvaluator, ABTestConfig; '
        f'from pathlib import Path; '
        f'e=LearningEvaluator(); '
        f'cfg=ABTestConfig(name="cli-ab-{cid}", agent="grok", n_runs_per_arm=1, simulate=True, wait_for_real=False); '
        f'print(e.ab_test_skill_versions({benchmarks!r}, "{source_skill}", str(Path(r"{yaml_for_ab}")), cfg).summary())\''
    )

    cmd_file = cand_path / "suggested_ab_command.txt"
    cmd_content = f"""# Exact command / snippet for A/B on this candidate ({cid}) vs {source_skill}
# Generated during promote-and-ab (or promote with A/B prep)

# 1. Recommended: run the generated python script (safest, full logging)
python {ab_script_path}

# 2. One-liner (quick, for paste into terminal)
{oneliner}

# 3. Full control (edit and run):
python -m agentforge.list_pending_candidates promote-and-ab {cid} --auto-ab

# For REAL (non-sim) A/B validation before full prod promote of the skill:
#   - Edit the script: set simulate=False, wait_for_real=True, n_runs_per_arm=2+
#   - Ensure AGENTFORGE_RUST_FLYWHEEL etc and eval runner can dispatch real tasks
#   - Then: python {ab_script_path}

# After A/B shows clear winner on treatment: consider full promotion (overwrite prod skill yaml, update agent cards, etc.)
"""
    if not dry_run:
        cmd_file.write_text(cmd_content, encoding="utf-8")

    print(f"[pending_candidates] A/B artifacts prepared for {cid}:")
    print(f"  - {ab_cfg_path}")
    print(f"  - {ab_script_path}")
    print(f"  - {cmd_file}")
    print(f"  Suggested one-liner (simulate): {oneliner[:120]}...")

    return {
        "ab_config_path": str(ab_cfg_path),
        "ab_script_path": str(ab_script_path),
        "suggested_command_file": str(cmd_file),
        "oneliner": oneliner,
        "old_skill": source_skill,
        "new_yaml": str(yaml_for_ab),
        "benchmarks": benchmarks,
    }


def promote_candidate(
    candidate_id_or_path: str,
    *,
    copy_to_skills: bool = False,
    mark_reviewed: bool = True,
    dry_run: bool = False,
    target_name: Optional[str] = None,
    # New A/B + safe promotion extensions
    prepare_ab: bool = True,
    auto_ab: bool = False,
    benchmarks: Optional[List[str]] = None,
    use_timestamped_promoted_name: bool = True,
) -> Optional[Path]:
    """
    Extended promotion logic with A/B testing skeleton + seamless safe promotion.

    TODO(Phase 0, RUST_FULL_MIGRATION_PLAN.md): deprecate in favor of pure Rust
    candidate promote. Warning emitted below for visibility during transition.

    - mark_reviewed=True  : touch .reviewed marker + update meta
    - copy_to_skills=True : safe-copy candidate_skill.yaml into skills/ as
                            <name>.promoted.<timestamp>.yaml  (or exact target_name)
                            NEVER clobbers production skills by default.
    - prepare_ab=True     : ALWAYS generate proper A/B test config (ab_test_config.json)
                            + exact runnable Python snippet (run_ab_after_promote.py)
                            + suggested_ab_command.txt with one-liner + instructions.
                            This wires directly to LearningEvaluator.ab_test_skill_versions
                            using the candidate YAML as treatment vs extracted source_skill.
    - auto_ab             : if True, after preparing artifacts, attempt to *call*
                            LearningEvaluator (defaults to simulate=True for safety;
                            use real flags only when you mean it).
    - use_timestamped_promoted_name=True : extra safety (timestamp in filename)

    Also:
    - Appends to central promotion log (PENDING_DIR/promotions.jsonl) - creates if needed.
    - Updates candidate_meta.json with promoted + ab_prepared info.
    - If any other index files exist in skills/ or pending, they get touched/updated.

    Returns the promoted yaml path (if copied) or the pending dir.
    """
    if not is_pure_rust_flywheel():
        warnings.warn(
            "learning.pending_candidates.promote_candidate (Python) is deprecated per "
            "RUST_FULL_MIGRATION_PLAN.md PHASE 3 FINAL. Pure Rust: agentforge-runner candidate promote.",
            DeprecationWarning,
            stacklevel=2,
        )

    cand_path = Path(candidate_id_or_path)
    if not cand_path.exists():
        # treat as id under PENDING_DIR
        cand_path = PENDING_DIR / candidate_id_or_path
    if not cand_path.is_dir():
        print(f"[pending_candidates] ERROR: candidate dir not found: {cand_path}")
        return None

    yaml_src = cand_path / "candidate_skill.yaml"
    meta_p = cand_path / "candidate_meta.json"

    promoted_path: Optional[Path] = None
    cid = cand_path.name

    if copy_to_skills and yaml_src.exists():
        try:
            import yaml  # lazy

            data = yaml.safe_load(yaml_src.read_text(encoding="utf-8")) or {}
            base_name = target_name or data.get("name") or cid

            # Real safe copy: always use timestamped .promoted. name unless explicit target
            if not target_name and use_timestamped_promoted_name:
                ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
                dest_name = f"{base_name}.promoted.{ts}.yaml"
            else:
                dest_name = f"{base_name}.promoted.yaml" if not target_name else f"{target_name}.yaml"

            dest = SKILLS_DIR / dest_name
            SKILLS_DIR.mkdir(parents=True, exist_ok=True)
            if not dry_run:
                shutil.copy2(yaml_src, dest)
            promoted_path = dest
            print(f"[pending_candidates] PROMOTE (safe copy_to_skills): {yaml_src} → {dest}")
        except Exception as e:
            print(f"[pending_candidates] Promote copy failed: {e}")

    if mark_reviewed:
        marker = cand_path / ".reviewed"
        reviewed_at = datetime.utcnow().isoformat() + "Z"
        if not dry_run:
            marker.touch(exist_ok=True)
            if meta_p.exists():
                try:
                    meta = json.loads(meta_p.read_text(encoding="utf-8"))
                    meta["reviewed"] = True
                    meta["reviewed_at"] = reviewed_at
                    if promoted_path:
                        meta["promoted_to"] = str(promoted_path)
                    meta_p.write_text(json.dumps(meta, indent=2), encoding="utf-8")
                except Exception:
                    pass
        print(f"[pending_candidates] Marked reviewed: {marker}")

    # === Core new behavior: A/B skeleton + LearningEvaluator wiring ===
    ab_info: Optional[Dict[str, Any]] = None
    if prepare_ab:
        try:
            source_skill = _extract_source_skill(cand_path)
            ab_info = _generate_ab_artifacts(
                cand_path,
                promoted_path,
                source_skill,
                benchmarks=benchmarks,
                dry_run=dry_run,
            )
            # Update meta with A/B prep info
            if not dry_run and meta_p.exists():
                try:
                    meta = json.loads(meta_p.read_text(encoding="utf-8"))
                    meta["ab_prepared"] = True
                    meta["ab_prepared_at"] = datetime.utcnow().isoformat() + "Z"
                    meta["ab_old_skill"] = ab_info.get("old_skill")
                    meta["ab_new_yaml"] = ab_info.get("new_yaml")
                    if "ab_config_path" in ab_info:
                        meta["ab_config_path"] = ab_info["ab_config_path"]
                    meta_p.write_text(json.dumps(meta, indent=2), encoding="utf-8")
                except Exception:
                    pass
        except Exception as e:
            print(f"[pending_candidates] A/B artifact generation failed (non-fatal): {e}")

    # === Auto call into LearningEvaluator if requested (safe defaults) ===
    if auto_ab and ab_info and not dry_run:
        try:
            from .evaluator import LearningEvaluator, ABTestConfig  # local import

            print(f"[pending_candidates] --auto-ab: invoking LearningEvaluator (safe/simulate mode)...")
            e = LearningEvaluator()
            cfg = ABTestConfig(
                name=f"auto-ab-{cid}",
                agent="grok",
                n_runs_per_arm=1,
                wait_for_real=False,
                simulate=True,  # never real unless caller overrides externally
                use_temp_skill_files=True,
                timeout_minutes=20,
            )
            # Use the prepared yaml (promoted or original candidate)
            new_ref = ab_info.get("new_yaml") or str(cand_path / "candidate_skill.yaml")
            ab_result = e.ab_test_skill_versions(
                benchmark_ids=ab_info.get("benchmarks", DEFAULT_AB_BENCHMARKS),
                old_skill=ab_info.get("old_skill", "general-refactor"),
                new_skill_or_prompt=new_ref,
                config=cfg,
            )
            # Persist result next to candidate for review
            result_path = cand_path / f"ab_result_{ab_result.test_id}.json"
            result_path.write_text(json.dumps(ab_result.to_dict(), indent=2, default=str), encoding="utf-8")
            print(f"[pending_candidates] auto-ab result persisted → {result_path}")
            print(ab_result.summary())
        except Exception as e:
            print(f"[pending_candidates] auto_ab invocation skipped/failed (ok for skeleton): {e}")

    # === Update promotion index / log (creates if not exists; updates the canonical one) ===
    if not dry_run:
        try:
            log_path = PENDING_DIR / "promotions.jsonl"
            log_entry = {
                "candidate_id": cid,
                "promoted_at": datetime.utcnow().isoformat() + "Z",
                "promoted_to": str(promoted_path) if promoted_path else None,
                "copy_to_skills": bool(promoted_path),
                "reviewed": mark_reviewed,
                "ab_prepared": bool(ab_info),
                "ab_old_skill": (ab_info or {}).get("old_skill"),
                "source_path": str(cand_path),
            }
            with log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
            print(f"[pending_candidates] Updated promotion log: {log_path}")

            # Also update/create a small index in skills/ if the dir exists (or always touch our canonical)
            skills_idx = SKILLS_DIR / "promotion_history.json"
            try:
                SKILLS_DIR.mkdir(parents=True, exist_ok=True)
                hist: List[Dict[str, Any]] = []
                if skills_idx.exists():
                    try:
                        hist = json.loads(skills_idx.read_text(encoding="utf-8"))
                        if not isinstance(hist, list):
                            hist = []
                    except Exception:
                        hist = []
                hist.append(
                    {
                        "candidate_id": cid,
                        "promoted_to": str(promoted_path) if promoted_path else None,
                        "at": log_entry["promoted_at"],
                        "ab_prepared": bool(ab_info),
                    }
                )
                # Keep last 50
                if len(hist) > 50:
                    hist = hist[-50:]
                skills_idx.write_text(json.dumps(hist, indent=2), encoding="utf-8")
                print(f"[pending_candidates] Updated skills promotion index: {skills_idx}")
            except Exception:
                pass

            # Touch any other pre-existing index files (best-effort, non-fatal)
            for extra_idx in (
                PENDING_DIR / "promotion_index.json",
                SKILLS_DIR / "index.json",
            ):
                if extra_idx.exists():
                    try:
                        extra_idx.touch()
                    except Exception:
                        pass
        except Exception as e:
            print(f"[pending_candidates] Index/log update warning: {e}")

    if dry_run:
        print("[pending_candidates] (dry_run=True - no files written)")

    return promoted_path or cand_path


# Convenience re-exports for the CLI module
def get_pending_dir() -> Path:
    return PENDING_DIR


if __name__ == "__main__":
    print_pending_summary()
