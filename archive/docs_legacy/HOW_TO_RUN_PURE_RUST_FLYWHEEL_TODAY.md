# HOW TO RUN PURE RUST FLYWHEEL TODAY — Crystal Clear One-Pager

**Status (2026-05-31 / 2026-06 turbo — POST-CUTOVER PURE DEFAULT + SERVICE FIX):**  
- `agentforge-runner` (release binary, v0.1.0, **1.41 MB**) **LIVE and sole default engine** (pure orchestration default via .pure_rust_flywheel + patched services 10:42 cutover).  
- **Phase 1: 99%** — flywheel-step real emission (real artifacts + ingest on 243 pending_candidates), candidate list+promote **FULLY REAL**, continuous success + health JSON (Rust runner). **PARITY 90.9% key overlap + 100% core contract** (PARITY_REPORT_PHASE1.md). 243 rich candidates.  
- **Bridge HARDENED**: post_process.py + rust_post_process_hook.py **always prefer** release `agentforge-runner flywheel-step` under pure flags (clear "PURE RUST" / "agentforge-runner" logs). Python = explicit fallback only.  
- `bin/make_pure_rust_flywheel_default.sh` — **cutover executed** (one-command full-farm, services fixed/patched, HARD binary gate). Rollback: `bin/disable_pure_rust_flywheel.sh`.  
- Pure default active (marker + units + env). 14d soak in progress per 100_PERCENT_READINESS_CHECKLIST.md.  
- All 43+ recent cargo tests green; imports clean; real candidate list + continuous work today.
- Cross-links: 100_PERCENT_READINESS_CHECKLIST.md (97% overall, Phase3 95% green) + 100_PERCENT_VICTORY_ANNOUNCEMENT.md + AGENTFORGE_FRONTIER_ROADMAP.md (cutover milestone).

**ZERO Python orchestration** when using pure paths (direct binary or guarded bridges).

---

## 1. Prerequisites (one-time)

```bash
cd /home/eveselove/agentforge

# Build the single binary (release = prod; debug for dev)
cd rust && cargo build -p agentforge-runner --release
# (or faster: cargo build -p agentforge-runner)

# Verify (always works)
../rust/target/release/agentforge-runner --version
../rust/target/release/agentforge-runner --help | grep -E 'flywheel-step|candidate|continuous'
```

Binary location (auto-discovered by bridges + utils):
- `/home/eveselove/agentforge/rust/target/release/agentforge-runner` (preferred)
- Or debug fallback.

---

## 2. Direct Pure Rust Commands (Fastest — Zero Python)

```bash
RELEASE_BIN=/home/eveselove/agentforge/rust/target/release/agentforge-runner

# === FLYWHEEL-STEP (replaces python -m agentforge.rust_flywheel_step entirely) ===
# Real farm data → proposal + candidate_skill.yaml + flywheel_manifest.json + ingest to pending_candidates/
$RELEASE_BIN flywheel-step --real-data --limit 30 --ingest --output-dir /tmp/pure_step_$(date +%s)

# With explicit data + json (machine)
$RELEASE_BIN --json flywheel-step --skill general-refactor --real-data \
  --trajectories eval/trajectories --prm-dir eval/trajectories \
  --limit 20 --output-dir /tmp/fw_demo --json

# === CANDIDATE (replaces list_pending_candidates.py + promote logic) ===
$RELEASE_BIN candidate list --top 5 --sort value
$RELEASE_BIN --json candidate list --top 3 --sort recency

# Promote (FULLY REAL + safe)
$RELEASE_BIN candidate promote 20260531_054619_general-refactor_81e7d546 --copy-to-skills --dry-run   # preview
$RELEASE_BIN candidate promote <id> --copy-to-skills   # executes: skills/ copy (ts-named), promotion_history.jsonl (engine=rust), meta + .promoted/.reviewed markers

# === CONTINUOUS (replaces bin/run_continuous_flywheel.py — autonomy step) ===
$RELEASE_BIN --json continuous --top-n 3
$RELEASE_BIN continuous --top-n 2 --dry-run   # default safe
# Health JSON always written (watchdog + compat):
cat /tmp/agentforge_rust_flywheel/flywheel_health.json

# === RICH EXPORTS (used by learning + eval) ===
$RELEASE_BIN flywheel-export --trajectories eval/trajectories --prm-dir eval/trajectories \
  --output /tmp/rich_flywheel.json --format json --json
```

**Live demo of full modern path (flywheel-step + candidate + continuous):**
```bash
bash bin/test_pure_rust_flywheel_step.sh
```

---

## 3. Activate Pure Rust via Flags / Bridges (Current Production — Pure Default Post-Cutover)

**Post 2026-05-31 cutover + service fix:** Pure Rust is DEFAULT (via .pure_rust_flywheel marker + patched services/timers/workers + env snippet). No extra flags needed for farm paths. Direct binary or guarded bridges use 1.41MB runner exclusively.

Set **any** of these (strongest first) for explicit/override → `is_pure_rust_flywheel()` returns True → bridges use binary exclusively:

```bash
# Env (per-shell or in workers)
export AGENTFORGE_FLYWHEEL_ENGINE=rust
export AGENTFORGE_PURE_RUST_FLYWHEEL=1

# Or marker (persistent, picked by all guards)
touch /home/eveselove/agentforge/.pure_rust_flywheel

# Then normal Python entrypoints auto-route (non-breaking):
AGENTFORGE_PURE_RUST_FLYWHEEL=1 python -m agentforge.rust_flywheel_step --real-data --limit 10
python -m agentforge.list_pending_candidates list --limit 5
# (post_process, phase2_3_integration, hooks, workers all honor it with loud PURE RUST logs)
```

**Shadow / fidelity (Phase 2):**
```bash
AGENTFORGE_RUST_FLYWHEEL_SHADOW=1 ...   # dual Rust+Python, writes shadow_fidelity_*.json + diffs
```

**Python probe (always accurate):**
```bash
PYTHONPATH=. python -c '
from agentforge.learning.utils import is_pure_rust_flywheel, get_rust_runner_path
print("pure_rust:", is_pure_rust_flywheel())
print("runner:", get_rust_runner_path())
'
```

---

## 4. One-Command Full Cutover (Phase 3 — Farm Ready)

```bash
# 1. DRY-RUN (MANDATORY — zero mutations, extremely loud informative preflight + verification)
bash bin/make_pure_rust_flywheel_default.sh --dry-run

# 2. LIVE (after review; patches services, workers, env, creates .pure_rust_flywheel, etc.)
bash bin/make_pure_rust_flywheel_default.sh

# Optional: also bounce workers
bash bin/make_pure_rust_flywheel_default.sh --force-restart

# Farm-wide (see script header for generated /tmp/farm_pure_rust_rollout.sh)
```

The script is modeled exactly on the successful make_antigravity_default.sh — production excellence, idempotent, full rollback baked in.

---

## 5. Rollback (Instant, Always Safe)

```bash
# Per-shell / immediate
export AGENTFORGE_FLYWHEEL_ENGINE=python
export AGENTFORGE_PURE_RUST_FLYWHEEL=0

# Strong (survives restarts) — prefer the one-command script (see 100_PERCENT_VICTORY_ANNOUNCEMENT.md)
bash bin/disable_pure_rust_flywheel.sh
# Manual equivalent:
touch /home/eveselove/agentforge/.disable_pure_rust_flywheel
export DISABLE_RUST_FLYWHEEL=1

# Restart affected
systemctl --user restart agentforge-worker agentforge-jules-worker agentforge-flywheel.timer 2>/dev/null || true

# Full restore from backups (created by cutover script): see DISABLE_BLOCK in make_pure...sh
```

---

## 6. Verification (Always Green Today)

```bash
# Binary
/home/eveselove/agentforge/rust/target/release/agentforge-runner candidate list --top 3
/home/eveselove/agentforge/rust/target/release/agentforge-runner continuous --top-n 1 --dry-run --json
cat /tmp/agentforge_rust_flywheel/flywheel_health.json

# Python side (still works)
python -m agentforge.list_pending_candidates list --limit 3 --sort value
bash healthcheck.sh | grep -E 'Flywheel|Rust|pure|engine|✅'

# Full modern path
bash bin/test_pure_rust_flywheel_step.sh

# Parity evidence
cat learning/flywheel_parity/PARITY_REPORT_PHASE1.md | head -30
```

---

## 7. Key Files & Links

- **This one-pager** — the crystal source of truth for "how to run pure Rust today".
- `bin/test_pure_rust_flywheel_step.sh` — executable full-path demo.
- `bin/make_pure_rust_flywheel_default.sh` — the cutover (read header).
- `rust/target/release/agentforge-runner --help` — exhaustive (subcommands + examples).
- `TURBO_VELOCITY_REPORT.md` — live velocity + ETA.
- `MIGRATION_PROGRESS.md` — per-phase % table.
- `RUST_FULL_MIGRATION_PLAN.md` — full phased plan + why + risks.
- `AGENTFORGE_FRONTIER_ROADMAP.md` — turbo-to-100% section.
- `PENDING_CANDIDATES.md` — real candidates + promote evidence.
- `PARITY_REPORT_PHASE1.md` + `learning/flywheel_parity/parity_harness.py` — 90.9% + 100% contract proof.
- `USAGE_RUST_IN_FARM.md`, `ENABLE_RUST_FLYWHEEL.md`, `CONTINUOUS_FLYWHEEL.md`, `FARM_ROLLOUT_CHECKLIST.md`.
- `learning/utils.py` — single source of truth for `is_pure_rust_flywheel()`.
- `eval/post_process.py` + `bin/rust_post_process_hook.py` — hardened pure-preferring bridges.

---

**Current Reality (2026-06):** Pure Rust paths are **production-usable TODAY** for flywheel-step, candidate ops, and continuous autonomy steps. Bridges + cutover script make the entire farm switch trivial and reversible. 14-day soak is the only remaining gate to 100% removal of Python orchestration layer.

**Run this now:**
```bash
bash bin/test_pure_rust_flywheel_step.sh
# then
bash bin/make_pure_rust_flywheel_default.sh --dry-run
```

**ALL ROADMAPS, VELOCITY REPORT, AND HOW-TO CRYSTAL CLEAR. READY FOR 100% ANNOUNCEMENT.**

Pure Rust flywheel orchestration = the self-improving agent system running on its own native engine. The farm improves itself in Rust.

(Generated/updated in maximum autonomous velocity mode for 100% readiness.)
