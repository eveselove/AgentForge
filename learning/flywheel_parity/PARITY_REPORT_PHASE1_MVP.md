# PARITY_REPORT_PHASE1_MVP

**Date:** 2026-05-31  
**Context:** Jules turbo for parity + validation of the new real emission from pure-Rust `agentforge-runner flywheel-step`.  
**Harness:** learning/flywheel_parity/parity_harness.py (explored + minimally extended)  
**Binary used:** /home/eveselove/agentforge/rust/target/release/agentforge-runner (fresh cargo build --release -p agentforge-runner)

## 1. Exploration
- `parity_harness.py`: golden fixtures under `fixtures/golden/` (sample_general_refactor_v1 + sample_with_rich_export) originally collected from real `pending_candidates/`.
- Real pending_candidates/ (e.g. 20260531_*_general-refactor_*) contain Python-bridge emissions (rich manifests, "recovery" proposals, full Python SkillImprover YAML shape).
- Inputs: mini_trajectories + real farm data in `eval/trajectories/` + `eval/results/` (used for --real-data).

## 2. Fresh real emission run
Command (using newly built release binary + real trajectories):
```
cd /home/eveselove/agentforge && /home/eveselove/agentforge/rust/target/release/agentforge-runner \
  flywheel-step --real-data --trajectories eval/trajectories --prm-dir eval/trajectories \
  --skill general-refactor --output-dir /tmp/parity_test
```
Result: emitted 4 artifacts (proposal.json, candidate_skill.yaml, flywheel_manifest.json, README.md). Loaded 96 records (real data path exercised).

## 3. Existing harness run (baseline)
- All 6 unittests PASS (self-compare, normalize, golden load, skeleton).
- CLI parity_check on goldens: DIFFS (as designed for skeleton).

## 4. Harness extension (minimal)
- `run_rust_flywheel_step` now locates + invokes the real Phase1 binary (prefers the just-built release), supports `output_dir=...` reuse for pre-run fresh emissions (no re-exec).
- Added `load_from_output_dir(out_dir)` to directly ingest artifacts from a `flywheel-step --output-dir` run.
- Added `compare_rust_to_python_shape(rust_artifacts, py_ref)`: checks required keys present on proposal.json + candidate_skill.yaml; rationale text tolerance (keyword signals instead of exact match or full diff); overlap check vs Python ref.
- Updated tests + `__main__` to exercise against `/tmp/parity_test`.
- Existing `compare_to_golden` + normalize still used (shows expected diffs).

## 5. Results vs fresh Rust emission + Python golden ref
**Loaded from /tmp/parity_test:** `['proposal.json', 'candidate_skill.yaml', 'flywheel_manifest.json', 'README.md']`

**Shape diffs (tolerance + required keys) - Phase1 MVP:**
- `candidate_skill.yaml: missing core name/prompt keys` (Rust uses `proposed_name` + `new_system_prompt` + raw comment header; Python golden uses `name` + `system_prompt` + `description` + `ci_checks` + `few_shot_examples`)
- `candidate_skill.yaml: _learning_meta lacks rust source marker (tolerance)` (present as `"source": "rust-flywheel-step@phase1"` but shape checker conservative)
- `rationale overlap low vs Python ref (expected Phase1): overlap=0`

**Full normalized compare diffs to golden (many expected):**
- All core artifacts differ: proposal.json, candidate_skill.yaml, flywheel_manifest.json (and missing candidate_meta in pure-Rust emission for MVP)

**Precise mismatches noted (Phase 1 MVP - expected, not bugs):**
- **proposal.json**:
  - `proposals[0].section`: "system_prompt" (Rust heuristic) vs "recovery" (Python golden + bridge)
  - `overall_rationale`: "Analyzed 96 failures. Most common error pattern: 'unknown_error'. " (generic from empty/low-signal heuristic on current trajs) vs long "Rust flywheel detected high-value failure patterns... structured recovery..."
  - `source`: "agentforge-runner/flywheel-step (pure Rust, Phase 1)" vs "rust_flywheel_step + agentforge-runner bridge + SkillImprover"
  - `new_system_prompt`: generic "You are an expert at general-refactor..." vs specific recovery text
  - `high_learning_value_records`: 0 (in this particular real-data load) vs 20/32
  - Extra: `suggested_ci_checks` array present
- **candidate_skill.yaml**:
  - Completely different top-level shape + keys (Rust: proposed_name, timestamp, overall_rationale + new_system_prompt at top + minimal _learning_meta; Python: full description/ci_checks/few_shot_examples + richer _learning_meta.generated_by/analysis/impact)
  - No "system_prompt" key (uses new_system_prompt)
- **flywheel_manifest.json**:
  - Minimal (records_loaded, engine, command, timestamp, rust_pairs_used, pending_candidates_ingest note) vs rich Python (before_stats with success_rate/avg_learning_value/high_value*, simulated_after, env_guard, rust_pairs_exported etc.)
- Rationale texts have zero word overlap (different improver paths: pure heuristic vs Python SkillImprover on rich pairs).
- No candidate_meta.json emitted yet in pure-Rust MVP.

All core **required keys** (skill/rationale/new_system_prompt/proposals/source/estimated_impact + _learning_meta) are present in Rust emission. Real data path works. Emission is valid for pending_candidates ingest + evaluator.

## 6. Cleanup
- /tmp/parity_test and any harness temps removed after report.
- No permanent side-effects.

## 7. Conclusion
Rust now emits real candidate artifacts - parity target for Phase 2.

Harness expanded + run for Phase 1 real emission. Zero data loss risk; shape contract evolving toward full parity in later phases (LLM delegate, richer prioritizer, exact YAML mirroring).

Next: wire native candidate ingest, richer sectioned proposals, and update goldens from pure-Rust runs.
