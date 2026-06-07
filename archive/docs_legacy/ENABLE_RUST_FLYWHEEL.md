# ENABLE_RUST_FLYWHEEL — Operational Activation Guide (Rust Flywheel for Antigravity — Now DEFAULT)

# ============================================================
# 🚀 ANTIGRAVITY DEFAULT ACHIEVED — FINAL ONE-COMMAND LOCKDOWN (2026-05-31)
# THE SCRIPT: bash /home/eveselove/agentforge/bin/make_antigravity_default.sh   (or --dry-run)
# Does in one shot: touch ENABLE, enable_rust + enable_continuous, safe service notes, healthcheck, full verify.
# Victory + Timer + Real A/B: VICTORY_SUMMARY.md + HOW_WE_FINISHED_WITH_AGENTS.md + bin/trigger_real_ab_on_farm.sh
# Full farm (main + remotes) + DISABLE path printed by the script itself.
# Only killswitch ever: DISABLE_RUST_FLYWHEEL=1 (or touch .disable_rust_flywheel).
# Now the canonical "make default" story. See also ANTIGRAVITY_DEFAULT.md + new banner in AGENTFORGE_FRONTIER_ROADMAP.md
# ============================================================

**Major milestone (2026-05-31 turbo):** The full Rust-powered self-improving flywheel is now **ON BY DEFAULT** for Antigravity tasks and the entire live farm.

> **Story & full communication package**: See the new dedicated `ANTIGRAVITY_DEFAULT.md` (what changed, how to disable cleanly, benefits, continuous behavior, and the "What this means for Antigravity tasks" blurb). This file remains the precise ops reference (commands, systemd, timers, rollback).

## Quick Status
- Default: Enabled (no env var needed)
- Disable globally: `DISABLE_RUST_FLYWHEEL=1`
- Legacy explicit enable still works

---

## Old one-command activation (still valid for explicit control)

**Goal**: Turn on the full Rust-powered autonomous learning flywheel (core + learning crate + runner) for the entire live AgentForge farm with **one command**.

All real task completions will then:
- Run through post_process (with Rust acceleration + PRM)
- Feed TrajectoryDataset + export pairs via the Rust binary
- Trigger bounded `run_rust_flywheel_step` (proposals + candidate YAML skills)
- Improve the farm over time with zero manual intervention.

## Prerequisites
- Rust toolchain + `cargo` available
- Binary built at least once: `cd /home/eveselove/agentforge/rust && cargo build -p agentforge-runner --release`
- (Recommended) Release binary for prod speed.

## Single Command Enable (Recommended)

From `/home/eveselove`:

```bash
PYTHONPATH=. python -c 'import agentforge.enable_rust_flywheel as e; e.activate()'
```

This:
- Sets `AGENTFORGE_RUST_FLYWHEEL=1`, `AGENTFORGE_USE_RUST=1`, `AGENTFORGE_RUST_RUNNER=...` (prefers release)
- Verifies the binary (prints build hint if missing)
- Applies **idempotent monkey-patch** to `agentforge.eval.post_process.post_process_task`
- Safe to run repeatedly.

## Shell Wrapper (still supported, now calls the Python module)

```bash
bash /home/eveselove/agentforge/bin/enable_rust_flywheel.sh
# or (safe to source in workers):
source /home/eveselove/agentforge/bin/enable_rust_flywheel.sh 2>/dev/null || true
```

It also writes `/home/eveselove/agentforge/bin/rust_flywheel.env` for easy sourcing.

## Make It Permanent Across the Farm (Workers + Services)

**One-command for all workers (systemd preferred for prod farm):**
See `FARM_ROLLOUT_CHECKLIST.md` for the complete production checklist (includes timer for continuous flywheel, monitoring additions to healthcheck/show_agent_stats/list_pending, rollback, Autonomy agent cross-ref).

### Option A: Source the env snippet early (easiest for .sh files)

Edit these files and add near the top (after PATH exports):

```bash
source /home/eveselove/agentforge/bin/rust_flywheel.env 2>/dev/null || true
```

Affected files (at minimum):
- `grok_worker.sh`
- `jules_worker.sh`
- `dispatcher.sh`
- `agents/grok_runner.sh` (and siblings)
- `watchdog.sh`

Then restart the running processes.

### Option B: Python import at top of any worker Python sections

In any embedded python -c or .py called by workers:

```python
import sys
sys.path.insert(0, "/home/eveselove")
import agentforge.enable_rust_flywheel as e
e.activate()
```

### Option C: Systemd services (for agentforge-worker, jules etc.)

Edit the unit (e.g. via `systemctl edit agentforge-worker.service`) or the source `install_services.sh`:

Add under `[Service]`:

```
Environment=AGENTFORGE_RUST_FLYWHEEL=1
Environment=AGENTFORGE_USE_RUST=1
Environment=AGENTFORGE_RUST_RUNNER=/home/eveselove/agentforge/rust/target/release/agentforge-runner
```

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl restart agentforge-worker.service agentforge-jules-worker.service ...
```

### Option D: Cron / systemd timer example (periodic re-arm + flywheel nudge)

Create `/etc/systemd/system/agentforge-rust-flywheel.timer`:

```ini
[Unit]
Description=AgentForge Rust Flywheel periodic arm + nudge

[Timer]
OnBootSec=2min
OnUnitActiveSec=15min
Persistent=true

[Install]
WantedBy=timers.target
```

And matching `.service`:

```ini
[Unit]
Description=AgentForge Rust Flywheel activation + bounded step
After=network.target

[Service]
Type=oneshot
User=agx
WorkingDirectory=/home/eveselove/agentforge
Environment=PYTHONPATH=/home/eveselove
ExecStart=/usr/bin/python3 -c "
import sys
sys.path.insert(0, '/home/eveselove')
import agentforge.enable_rust_flywheel as e
e.activate(quiet=True)
import subprocess, os
# optional: nudge a bounded step (rate-limited inside)
if os.environ.get('AGENTFORGE_RUST_FLYWHEEL') == '1':
    subprocess.call(['python3', '-m', 'agentforge.rust_flywheel_step', '--real-data', '--use-rust', '--limit', '8'], cwd='/home/eveselove/agentforge')
"
```

Enable:

```bash
sudo cp /home/eveselove/agentforge/ENABLE_RUST_FLYWHEEL.md /tmp/  # (copy units if you put them in repo)
sudo systemctl enable --now agentforge-rust-flywheel.timer
```

Simple cron alternative (crontab -e):

```
*/20 * * * * PYTHONPATH=/home/eveselove /usr/bin/python3 -c 'import sys;sys.path.insert(0,"/home/eveselove");import agentforge.enable_rust_flywheel as e;e.activate(quiet=True)' >> /home/eveselove/agentforge/logs/flywheel-arm.log 2>&1
```

## Verify It's Working

After a real task completes (or use `--test-post-process`):

```bash
# Quick check
env | grep AGENTFORGE_RUST

# Force a post-process + flywheel
PYTHONPATH=. python -c '
import os
os.environ["AGENTFORGE_RUST_FLYWHEEL"]="1"
from agentforge.eval.post_process import post_process_task
print(post_process_task("some-recent-task-id"))
'

# Or direct
PYTHONPATH=. python -m agentforge.rust_flywheel_step --real-data --use-rust --limit 5
```

Look for `rust_bridge_used`, `rust_flywheel_triggered`, `candidate_yaml_path` in output.

## Rollback (instant)

```bash
unset AGENTFORGE_RUST_FLYWHEEL AGENTFORGE_USE_RUST AGENTFORGE_RUST_RUNNER
# Or kill the timer + restart workers without the source line
```

The Python paths gracefully fall back; nothing is destructive.

## NEW: Default Behavior (as of 2026-05-31)

The Rust self-improving flywheel is now **enabled by default** for all Antigravity tasks.

- No need to set any `ENABLE_*` variables for normal operation.
- The system will automatically:
  - Run rich Rust flywheel export after tasks (rate-limited)
  - Generate improvement proposals + candidate skills
  - Feed the continuous autonomy loop (when timer is enabled)

### Disable (strong kill switch)
```bash
export DISABLE_RUST_FLYWHEEL=1
# Then restart workers / dispatcher
```

Or per-process: `DISABLE_RUST_FLYWHEEL=1 python ...`

This is the recommended way to temporarily turn off the advanced loop.

## Notes

- The Rust binary is the single source of truth for heavy dataset ops (much faster + type-safe Outcome etc.).
- `enable_rust_flywheel.py` + the updated `bin/enable...sh` are the official tiny activation surface.
- Outcome unification (core → learning reexports + From impls) landed in the same wave for full consistency.

**One command. Whole farm. Self-improving.**

See also: `FARM_ROLLOUT_CHECKLIST.md` (full ops rollout, timer, monitoring, rollback) and `PENDING_CANDIDATES.md` (candidate/A/B flow).

(Updated 2026-05-31: Rust flywheel self-improving closed loop victory + full production ops.)
