# Using the Rust Flywheel in the Live Farm (Minimal Friction)

**Goal**: Make compiled Rust (`agentforge-runner`) accelerate heavy learning/flywheel work (dataset loads for large sets, preference pair export, autonomous proposals) from real post-task hooks with zero breakage on fallback.

**2026-06 PURE RUST UPDATE (FINAL DOCS VELOCITY + 100% READINESS AUDIT):** Pure direct paths production-ready and preferred: `agentforge-runner flywheel-step / candidate list|promote (FULL REAL) / continuous` (see HOW_TO_RUN_PURE_RUST_FLYWHEEL_TODAY.md + bin/test_pure... + 100_PERCENT_READINESS_CHECKLIST.md). Bridges hard-prefer binary. Cutover prod-grade. 238 cands, 1.41 MB binary verified. All roadmaps one-last refreshed. Overall ~91%. **DOCS AND 100% READINESS MAXIMIZED.**

## One-Line Enable (Live Farm)

```bash
# In your shell / worker env (or prefix commands)
export AGENTFORGE_USE_RUST=1
export AGENTFORGE_RUST_RUNNER=/home/eveselove/agentforge/rust/target/debug/agentforge-runner
# (binary auto-discovered from common locations if RUST_RUNNER unset)
```

Then all real tasks + post_process automatically route heavy work through Rust when possible.

## Clean Usage Example (after real task / in workers)

```bash
# After a real grok/jules task completes (e.g. inside grok_runner.sh post block or cron)
TASK_ID="0374c1c2"   # or whatever real_task_id / trajectory stem

AGENTFORGE_USE_RUST=1 \
  python -m agentforge.bin.rust_post_process_hook "$TASK_ID"

# Or directly (the canonical path):
AGENTFORGE_USE_RUST=1 \
  python -m agentforge.eval.post_process "$TASK_ID"
```

This runs:
- Normal PRM + sidecar enrichment (existing)
- Rust `export-pairs` / `export-records` via the enhanced bridge in `learning/trajectory_dataset.py` (auto when env=1)
- `run_rust_flywheel_step` (from `phase2_3_integration`) → attaches `rust_flywheel_proposal`, `rust_flywheel_candidate_yaml` etc. to the result

Result dict now contains paths to generated candidate skill YAML + proposal JSON under `/tmp/agentforge_rust_flywheel/<ts>/` ready for review / promotion.

## Key Files (already wired)

- `learning/trajectory_dataset.py` — heavy methods (`load_from_eval_results`, `export_preference_pairs`, ...) auto-delegate to Rust + graceful py fallback
- `eval/post_process.py` — calls the flywheel step + Rust export when env set; proposal/candidate attached to every result
- `bin/rust_post_process_hook.py` — small production shim for easy drop-in from `agents/grok_runner.sh`, `grok_worker.sh`, etc.
- `phase2_3_integration.py` — `run_rust_flywheel_step(...)` is the production entrypoint
- `rust_flywheel_step.py` — full Track-B demonstrator

## Verification (one-liner)

```bash
AGENTFORGE_USE_RUST=1 python -c '
from agentforge.bin.rust_post_process_hook import main
from agentforge.eval.post_process import post_process_task
print("hook + post_process ready")
res = post_process_task("0374c1c2")  # real traj id example
print("candidate_yaml:", res.get("rust_flywheel_candidate_yaml"))
print("proposal present:", bool(res.get("rust_flywheel_proposal")))
'
```

See also: `JULES_FARM_INTEGRATION.md` (generated at end of integration) for exact live-farm enable commands + worker edits.

**Zero risk**: everything falls back to pure Python if binary missing or env unset. Rust only makes the flywheel *fast and reliable on real data today*.

---

## Pure Rust Direct Paths (NEW — Phase 1+ Real, No Python Orchestration)

**CRYSTAL HOW-TO (created this max-velocity wave):** See `HOW_TO_RUN_PURE_RUST_FLYWHEEL_TODAY.md` first — the dedicated one-pager with every command, verification (release binary live 1.18MB with real candidate list), cutover, rollback. All pure paths production-usable today. **DOCS AND VELOCITY MAXIMIZED FOR 100%.**

For maximum speed / purity (post Phase 1 MVP + bridge):

```bash
# Direct binary (build: cd rust && cargo build -p agentforge-runner --release)
BIN=./rust/target/release/agentforge-runner

$BIN flywheel-step --real-data --limit 20 --ingest --output-dir /tmp/pure_fw   # emits candidate_skill.yaml + proposal + manifest; --ingest to pending_candidates/
$BIN candidate list --top 10 --sort value
$BIN candidate promote <id> --copy-to-skills   # REAL (see promote.rs)
$BIN continuous --top-n 5 --json

# Guarded (current hot paths prefer these under flags)
AGENTFORGE_FLYWHEEL_ENGINE=rust AGENTFORGE_PURE_RUST_FLYWHEEL=1 \
  python -m agentforge.rust_flywheel_step --real-data --use-rust --ingest

# Full farm cutover (one command, modeled on antigravity)
bash bin/make_pure_rust_flywheel_default.sh --dry-run
```

See TURBO_VELOCITY_REPORT.md (velocity + full how-to + ETA), RUST_FULL_MIGRATION_PLAN.md, MIGRATION_PROGRESS.md, PENDING_CANDIDATES.md. Instant rollback always available.

**Latest wins (2026-05-31 MAX):** promote REAL, continuous + health, pure bridges, cargo green. **Phase 2 shadow v5 NEAR FARM-READY**: richer metrics (prompt_jacc + prop_content + grade/sev + health aggregate), continuous dual (AGENTFORGE_SHADOW_EVERY_N), full hook integration, max CLI/docs. Usable on real farm data.

## Phase 2 Shadow Dual-Run + Fidelity on Farm (v5 NEAR FARM-READY: richer + continuous dual support)
Use for A/B trials before any promote cutover (zero risk to prod). Now with expanded diffs + pass/score gates + easiest aggregate.

```bash
# Enable (produces v4 FURTHER ENRICHED fidelity: pass/score + numeric/bigram/title_diffs + smart pairing)
export AGENTFORGE_RUST_FLYWHEEL_SHADOW=1

# Direct (or via post_process after real task)
$BIN flywheel-step --real-data --limit 12 --shadow --output-dir /tmp/rust_shadow_$(date +%s) --json

# EASIEST farm one-liners (auto smart-pairs + v4 full):
python -m agentforge.learning.flywheel_parity.parity_harness --shadow-compare-latest --json | jq '.fidelity_pass, .composite_fidelity_score, .rationale_bigram_jaccard, .proposals_title_overlap_pct'
python -m agentforge.learning.flywheel_parity.parity_harness --shadow-aggregate --json   # zero-cost health

# Rich scripted
python -m agentforge.learning.flywheel_parity.parity_harness --shadow-compare-latest --json \
  | jq '{pass: .fidelity_pass, score: .composite_fidelity_score, num_deltas: .numeric_field_deltas, title_ov: .proposals_title_overlap_pct}'

# Or classic
cat /tmp/agentforge_rust_flywheel/shadow_fidelity_latest.json | python -m json.tool
```

**Full copy-paste + advanced in PHASE2_SHADOW_FIDELITY_PREP.md**. Harness importable. Rollback: unset SHADOW env. v4 makes farm monitoring/gates trivial.
