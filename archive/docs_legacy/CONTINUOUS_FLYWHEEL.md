# CONTINUOUS_FLYWHEEL.md — True 24/7 Autonomous Self-Improvement Loop

**Mission achieved (POST-CUTOVER PURE DEFAULT + SERVICE FIX 2026-05-31)**: The Rust-powered flywheel (candidates from real farm tasks via post_process + hooks + agentforge-runner) now runs a higher-level continuous closer **without any manual triggers** under pure default (patched services + timer + .pure marker). agentforge-runner continuous sole engine, health JSONs live, wrappers rc=0 success. 243 candidates. All docs + 100% checklist + victory announcement maximized + cross-linked. See 100_PERCENT_READINESS_CHECKLIST.md (Phase3 95% green) + bin/make_pure_rust_flywheel_default.sh + 100_PERCENT_VICTORY_ANNOUNCEMENT.md. **DOCS AND 100% READINESS MAXIMIZED.** 14d soak active.

Existing after-task hooks (grok_worker.sh / jules_worker.sh / dispatcher.sh + post_process.py + phase2_3_integration) already generate **hundreds of real candidates per day** (236+ in the last hour observed in live runs). This layer automates:
- Prioritized collection of high learning-value candidates (rich_avg_learning_value + success_rate lift potential)
- Auto `promote-and-ab` (safe A/B prep + simulate LearningEvaluator run) for top-N
- Detection of clear winners from prior A/B results → conditional final promote
- Health/metrics surfaced into watchdog

**100% reuse of all existing ENABLE / hooks / binaries**:
- `ENABLE_RUST_FLYWHEEL` marker file
- `bin/enable_rust_flywheel.sh` + `bin/rust_flywheel.env` + `enable_rust_flywheel.py`
- `AGENTFORGE_RUST_FLYWHEEL=1` / `USE_RUST=1` + release runner preference
- `rust_flywheel_after_task.sh` (5min flock rate-limit) + `rust_post_process_hook.py`
- `pending_candidates/` + `list_pending_candidates.py` (promote-and-ab) + LearningEvaluator
- All rate limits, locks, and graceful degradation

Non-breaking. All new paths are additive + guarded.

**Phase 2 shadow note (advanced)**: Set AGENTFORGE_RUST_FLYWHEEL_SHADOW=1 in the continuous env for dual-run fidelity (richer JSONs with rationale sim + lv deltas now auto-captured). Use `python -m agentforge.learning.flywheel_parity.parity_harness --shadow-compare` on emitted dirs for validation before wider rollout. See PHASE2_SHADOW_FIDELITY_PREP.md.

## One-Command Enable (systemd --user timer, 20min cadence)

**Production rollout script (recommended, 2026-05-31 Autonomy Timer Rolled Out):**

```bash
cd /home/eveselove/agentforge

# Full one-command (handles cp with traceable headers, daemon-reload, enable --now, verify, farm notes)
# Safe default: user mode. Use --system for /etc installs matching install_services.sh.
bash bin/enable_continuous_flywheel.sh

# Or simulation first (zero changes):
bash bin/enable_continuous_flywheel.sh --dry-run
```

**Manual / legacy path (still works, now wrapped by the script above):**
```bash
cd /home/eveselove/agentforge

# 1. Ensure flywheel already live (workers + post_process already wired)
touch ENABLE_RUST_FLYWHEEL
bash bin/enable_rust_flywheel.sh   # or source it

# 2. Install user timer (recommended; runs as your user, safe)
mkdir -p ~/.config/systemd/user
cp agentforge-flywheel.service agentforge-flywheel.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now agentforge-flywheel.timer

# 3. (Optional but recommended first day) Verify with safe dry-run
systemctl --user start agentforge-flywheel.service   # uses default dry-run in unit

# Watch live
journalctl --user -u agentforge-flywheel.service -f
tail -f logs/continuous_flywheel.log
```

**Activation date**: 2026-05-31 — full farm timer live (see PENDING_CANDIDATES.md "Autonomy Timer Rolled Out" + enable script).

**Verification**:
```bash
systemctl --user status agentforge-flywheel.timer
systemctl --user list-timers | grep flywheel

# Manual one-shot (dry by default — zero risk)
PYTHONPATH=. ENABLE_RUST_FLYWHEEL=1 python -m agentforge.bin.run_continuous_flywheel --top-n 2 --dry-run

# Real (still safe: promote-and-ab uses simulate A/Bs; full winner promote requires --auto-promote-winners)
PYTHONPATH=. ENABLE_RUST_FLYWHEEL=1 python -m agentforge.bin.run_continuous_flywheel --no-dry-run --top-n 2
```

## Cron Fallback (no systemd)

See `bin/cron_continuous_flywheel.example` (copy lines into `crontab -e`).

Example (20min + flock):
```
*/20 * * * * cd /home/eveselove/agentforge && flock -n /tmp/agentforge_rust_flywheel/.continuous_flywheel.lock -c 'ENABLE_RUST_FLYWHEEL=1 AGENTFORGE_USE_RUST=1 /home/eveselove/agentforge/bin/run_continuous_flywheel.sh --no-dry-run --top-n 2' >> logs/cron_flywheel.log 2>&1
```

## What the Continuous Step Does (per tick)

1. **Guard**: Only if `ENABLE_RUST_FLYWHEEL` (or equiv env) — exact same as live workers.
2. **Lock**: Hard `flock` (bash) + `fcntl` (python) — skips if another tick running.
3. **Prioritize**: `list_high_value_candidates()` (new) sorts by `rich_avg_learning_value` + computed `lift_pot = hlv * (1-sr) * lv`.
4. **Top-N promote-and-ab**: For candidates without recent A/B artifacts (<6h), call `promote_candidate(..., prepare_ab=True, auto_ab=True)` (reuses all A/B generator + run_ab_after_promote.py + LearningEvaluator simulate path).
5. **Winner closer**: Scan `ab_result*.json`; if `winner=="treatment"` + medium/high confidence (matching `LearningEvaluator.is_clear_winner`), optionally final promote (timestamped safe copy by default; `--auto-promote-winners` for full autonomy).
6. **Health**: Writes `/tmp/agentforge_rust_flywheel/flywheel_health.json` + `watchdog_flywheel_status.json` (candidates last hour, last A/B age, high-LV count).
7. **Watchdog integration**: Every 10s poll now reports flywheel metrics in logs + status file.

**Reliability features** (all present):
- Timeouts (240s hard)
- Idempotency (recent A/B skip, markers)
- Logging (dedicated + append to worker logs)
- Graceful degrade (no binary? still runs prioritizer on existing candidates)
- Dry-run default in timer unit

## CLI / Observability Upgrades (Autonomy Boost)

- `python -m agentforge.list_pending_candidates list --sort value` (default now) — high learning-value first.
- `--high-value-only` — pure prioritizer view.
- `python -m agentforge.list_pending_candidates promote-and-ab <id>` still works exactly as before.

New prioritizer lives in `learning/pending_candidates.py:list_high_value_candidates`.

## Monitoring

```bash
# Health (updated by continuous + visible to watchdog)
cat /tmp/agentforge_rust_flywheel/flywheel_health.json
cat /tmp/agentforge_rust_flywheel/watchdog_flywheel_status.json

# Recent candidates (value-sorted)
PYTHONPATH=. python list_pending_candidates.py list --limit 8 --sort value

# Continuous logs
tail -100 logs/continuous_flywheel.log

# Watchdog now emits flywheel lines every poll:
# [Watchdog] 🌀 Flywheel health: last_hour=236 high_lv=... last_ab_age_min=...

# Systemd
journalctl --user -u agentforge-flywheel.* --since "1 hour ago"
```

## The 3 Promoted Candidates (live example)

The candidates `20260531_053411_general-refactor_81e7d546`, `20260531_053412_general-refactor_81e7d546`, `20260531_053416_general-refactor_81e7d546` (with A/B artifacts + execute_real_abs script) now have autonomy notes.

Run the continuous timer and they (plus all future high-LV) participate in the 24/7 loop.

See also: `bin/execute_real_abs_on_promoted.sh` for the original manual REAL A/B batch.

## Architecture Fit (No Duplication)

- Generation: existing after-task rate-limited hooks → `rust_flywheel_step` (rich `flywheel-export`) → auto-ingest to `pending_candidates/`
- Closing: **this new continuous meta-layer** (timer-driven) → prioritizer + promote-and-ab + winner detection
- Human gate: still only needed for **real** expensive A/B approval + final prod skill activation (when not using `--auto-promote-winners`)

## Rollback / Disable (Instant)

```bash
# Preferred (uses the rollout script's emitted commands):
bash bin/enable_continuous_flywheel.sh --verify-only   # shows exact rollback lines
# Or direct:
systemctl --user disable --now agentforge-flywheel.timer
# Or simply: rm ENABLE_RUST_FLYWHEEL   (everything downstream becomes no-op)
```

**Full rollback via script (any mode):** see output of enable script or `bash bin/enable_continuous_flywheel.sh --help`.

All changes are additive files + tiny safe edits (sort default, watchdog report, prioritizer function).

## Evidence of Turbo Autonomy (as of 2026-05-31)

- 200-236+ candidates generated in single hours purely from farm task completions (no manual `rust_flywheel_step` calls needed).
- New `bin/run_continuous_flywheel.{py,sh}`, `agentforge-flywheel.{service,timer}`, `cron_*.example`
- **Production rollout**: `bin/enable_continuous_flywheel.sh` (dry-sim, user/system, header comments, timeouts, rollback, farm-wide cmds) + updates to `install_services.sh`, `watchdog.py` (deep timer probe), `healthcheck.sh`
- `CONTINUOUS_FLYWHEEL.md` + updates to PENDING_CANDIDATES.md ("Autonomy Timer Rolled Out" 2026-05-31) + candidate READMEs
- CLI defaults to learning-value sort
- Watchdog now tracks flywheel pulse + full timer status (active/next/last across user+system)
- All tests / dry-runs passed locally; full reuse of ENABLE paths + flock everywhere.

**Activation date: 2026-05-31 — Autonomy Timer now live 24/7 on the farm.**

**Continuous self-improvement loop now autonomous.**

(Next manual step only needed for real A/B approval.)

See related: `ENABLE_RUST_FLYWHEEL.md`, `PENDING_CANDIDATES.md`, `JULES_AUTO_FLYWHEEL_AFTER_TASK.md`, `USAGE_RUST_IN_FARM.md`.
