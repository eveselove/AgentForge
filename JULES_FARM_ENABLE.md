# JULES_FARM_ENABLE.md

**Outcome**: Tiny, robust, importable activation mechanism created + documented for the live Rust flywheel on the entire production farm.

> **2026-06 Note (Rust Flywheel Default for Antigravity)**: The flywheel this doc helped activate is now ON BY DEFAULT. See the full communication package in `ANTIGRAVITY_DEFAULT.md` (includes the canonical "What this means for Antigravity tasks" blurb and the new `bin/disable_rust_flywheel.sh`). This JULES artifact remains the historical record of the enable surface.

## Deliverables
- Created: `/home/agx/agentforge/enable_rust_flywheel.py`
  - `activate()` — sets envs, binary check + build hint, **idempotent** monkey-patch of `post_process.post_process_task`
  - Runnable as module or script (`python -m agentforge.enable_rust_flywheel`)
  - Safe for import at top of any worker/dispatcher code or via python -c in .sh files
- Updated: `/home/agx/agentforge/bin/enable_rust_flywheel.sh` (now calls the Python module for patch + activation; still produces env snippet)
- Created: `/home/agx/agentforge/ENABLE_RUST_FLYWHEEL.md` (full operator guide with one-command + systemd timer + cron examples)
- Also updated sh docs + one-liner for whole-farm.

## Exact One-Command Activation (Whole Farm)
```bash
# From /home/agx — does everything (env + binary check + post_process patch)
PYTHONPATH=. python -c 'import agentforge.enable_rust_flywheel as e; e.activate()'
```

## Exact Commands for Permanent Farm-Wide Rollout (examples)
```bash
# 1. Quick test activation + patch
PYTHONPATH=. python -c 'import agentforge.enable_rust_flywheel as e; e.activate()'

# 2. Source the generated snippet (add to grok_worker.sh / dispatcher.sh etc near top)
source /home/agx/agentforge/bin/rust_flywheel.env 2>/dev/null || true

# 3. Systemd unit edit example (add to [Service] section)
# Environment=AGENTFORGE_RUST_FLYWHEEL=1
# Environment=AGENTFORGE_USE_RUST=1
# Environment=AGENTFORGE_RUST_RUNNER=/home/agx/agentforge/rust/target/release/agentforge-runner

# 4. systemd timer (periodic re-arm + nudge) — see full units in ENABLE_RUST_FLYWHEEL.md
sudo systemctl enable --now agentforge-rust-flywheel.timer

# 5. Cron one-liner (every 20m re-arm)
# */20 * * * * PYTHONPATH=/home/agx /usr/bin/python3 -c 'import sys;sys.path.insert(0,"/home/agx");import agentforge.enable_rust_flywheel as e;e.activate(quiet=True)' >>/home/agx/agentforge/logs/flywheel-arm.log 2>&1
```

## Verification
```bash
env | grep AGENTFORGE_RUST
PYTHONPATH=. python -c '
import os, sys
sys.path.insert(0,"/home/agx")
import agentforge.enable_rust_flywheel as e
e.activate(quiet=True)
from agentforge.eval.post_process import post_process_task
print("patched?", getattr(post_process_task, "_rust_flywheel_enable_patched", False))
'
```

## Files Touched (all via search_replace + write where required)
- /home/agx/agentforge/enable_rust_flywheel.py (new, canonical activator)
- /home/agx/agentforge/bin/enable_rust_flywheel.sh (updated)
- /home/agx/agentforge/ENABLE_RUST_FLYWHEEL.md (new, operator doc + timer/cron)
- Plus the two JULES_*.md reports

**Result**: Operator can turn the entire live farm Rust flywheel on with literally one command. Idempotent, observable, production-grade, zero questions needed.

(Completed autonomously in JULES turbo parallel mode with Outcome unification — 2026-05-30)
