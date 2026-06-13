# AUDIT-5: Systemd user services agentforge-* (2026-06-13)

**Scope**: All `~/.config/systemd/user/agentforge-*.service` and `*.timer`.
Templates compared: `/home/eveselove/agentforge/agentforge-*.service` (and worker/flywheel etc).
Runtime: `systemctl --user`, journals, ps, ports, DBs, source inspection of workers.

**Date**: 2026-06-13 (erbox, user eveselove)
**Performed by**: Grok (local operator/debugger per AGENTS.md)

## Summary of services

| Service                    | Status (before/after fix)      | ExecStart (summary)                          | Needed? | Issues |
|----------------------------|--------------------------------|----------------------------------------------|---------|--------|
| agentforge-api.service    | active running (7h+)          | uvicorn task_queue:app @127.0.0.1:8080      | Legacy / partial | Dual queue (own tasks.db ~335 entries, mostly historical) |
| agentforge-antigravity.service | active running (7h)        | python antigravity_worker.py                | Yes (complex/antigravity tasks) | High load during audits (140 tasks, spawns groks + stray gateway in cgroup) |
| agentforge-builder.service | active running (8h, idle)     | python builder_worker.py                    | Niche (build tags) | Very low utilization |
| agentforge-gateway.service | **BROKEN** (restart loop, core-dump ABRT) → **FIXED** active running | rust gateway @0.0.0.0:9090 (primary API+dashboard) | **Critical (now main API)** | Port conflict + bad config (see below) |
| agentforge-grok.service   | active running (7h, heavy)    | bash grok_worker.sh (parallel + router)     | Yes (main executor for auto/grok) | High mem/CPU during audits; some transient tool errors from agents |
| agentforge-watchdog.service | active running (7h)         | python watchdog.py                          | Yes (kill loops, guardian, review sweeps) | utcnow deprecation spam every poll |
| agentforge-flywheel.service + .timer | inactive (disabled)      | agentforge-runner continuous (oneshot)      | Debatable (phase4 target) | No binary; timer had parse error; per-task hooks fallback to py |

**Active units (user)**: api, antigravity, builder, gateway (now), grok, watchdog. (flywheel disabled)

**No system services** for agentforge (old install script targeted /etc + agx user; current is --user only). Only unrelated `actions.runner...`.

## Detailed per-service

### 1. agentforge-api.service (legacy Python queue)
- **What**: Serves old FastAPI task queue on 127.0.0.1:8080 using `tasks.db`. Deprecated header in source: "MOVING TO RUST ONLY".
- **Status**: active (running) since ~05:27, low CPU/mem (~35M).
- **Needed?**: Partial/legacy. Most current code (grok_worker.sh, antigravity_worker.py, create_*.py, watchdog, dispatcher, healthcheck, github_watcher) uses **9090**. Python source no longer contains :8080. However, uvicorn logs show ongoing GET /tasks?status=failed + POST /review/all from 127.0.0.1 (likely from LLM-generated code inside audit worktrees or old .bak executions).
- **Config**:
  - Restart=always, RestartSec=5
  - Limits: TasksMax=100, MemoryMax=4G, CPUQuota=400%, OOM kill, good.
  - After=network.target (no gateway dep)
  - No WatchdogSec, no stdout/stderr redirect (journal only)
  - No StartLimit*
- **Conflicts**: None on port (distinct from 9090). **Data split risk**: separate DB from gateway's `data/task_checkpoints.db`.
- **Notes**: In templates: different (User=agx, 0.0.0.0:8080, envs for rust flywheel, logging to files). Installed version is cleaned for user mode + localhost bind.

### 2. agentforge-antigravity.service
- **What**: Polls 9090 for preferred_agent in (auto, antigravity), claims via PATCH, spawns grok CLI in git worktrees (up to ~10 parallel), uses antigravity_worker.py + config from agentforge_config.json.
- **Status**: active running. ~140 tasks in cgroup (many grok children + tees + bash). Actively processing the current audit wave (tasks like АУДИТ-1..9). Memory ~4G (of 20G). Logs clean (no recent err/warn).
- **Needed?**: Yes — handles architect/complex/"antigravity" tagged tasks separately from grok worker.
- **Config**: Restart=always/10s, strong limits (Tasks=300, Mem=20G, CPU=800%), After=network + api.service, KillMode=control-group, OOM=kill. No WatchdogSec. No log redirects.
- **Conflicts?**: None intentional. **Observed**: the long-lived stray `agentforge-gateway` (969900) lived in *this service's cgroup* (reparented to systemd[1674] but slice inherited from spawn inside a task context). Resource stats for antigravity were polluted by it.
- **Special: "does it work?"**: **Yes**. Fully operational, creating worktrees, dispatching grok for audits, etc.

### 3. agentforge-builder.service
- **What**: Similar poller for build/compile tagged tasks (max_parallel=2). builder_worker.py.
- **Status**: active but idle (Tasks:1, Mem 11M). Started 04:46, only "started" log.
- **Needed?**: Yes for CI/build pipeline tasks, but currently underused (perhaps routing changes or no such tasks lately).
- **Config**: Similar to others (Restart always/10, limits 40t/8G/600%).
- **Conflicts**: Explicitly skipped by grok_worker if build/compile tags.

### 4. agentforge-gateway.service (Rust primary API + dashboard)
- **What**: Axum/Rust server (main.rs): full /tasks CRUD, /review/all, dashboard HTML/WS, proxies to planly (parsers etc), static serve from gateway/static. Uses `data/task_checkpoints.db` (13M+ active). Binds 0.0.0.0:9090 (or $PORT).
- **Status (pre-fix)**: activating (auto-restart), Result=core-dump, restart counter >6140. Panics on `TcpListener::bind` (line 1566) with "Address already in use".
- **Status (post-fix)**: active (running), stable PID ~12960xx, serving 200 + 33 tasks.
- **Needed?**: **Yes — canonical now**. All live workers, creates, watchdog, healthcheck hit 9090. Old 8080 is legacy. Gateway also serves the monitoring/static pages referenced in audits.
- **Config (pre-fix, broken)**: Restart=always/3s (over-eager), **no resource limits**, After=...+api.service (strange), no StartLimit*, no Watchdog, bare Env only RUST_LOG.
- **Config (fixed in place)**: RestartSec=10, StartLimit* (300s/20), TasksMax=50/Mem=512M/CPU=100%, After=network.target only (dropped legacy api dep in comment), docs updated inline.
- **Conflicts**: Direct runtime port conflict with **stray** gateway (started 05:37, likely `exec` or background from prior audit task e.g. АУДИТ-6 "Rust Gateway audit", left running, reparented into antigravity slice).
- **Fix applied**: `kill 969900`; `systemctl --user restart ...` (then improved unit + daemon-reload + restart). Port now exclusively by managed service.

### 5. agentforge-grok.service (main parallel executor)
- **What**: bash grok_worker.sh — polls 9090, claims auto/grok tasks (skips antigravity/build), dynamic model router (simple/medium/complex + history), worktree isolation, timeout 300, background, supports rust flywheel envs, --check/--best-of-n for high/crit.
- **Status**: active, heavy (198 tasks in slice, 13.4G of 24G, 1h+ CPU recently). Running the parallel audit batch (multiple grok + timeout + tee wrappers).
- **Needed?**: Yes — primary "horse" for most tasks.
- **Config**: Excellent limits (500 tasks / 24G / 1400% CPU — leaves headroom), Restart always/10s, UnsetEnvironment=XAI..., After=network only (no api dep — good), KillMode=cgroup.
- **Conflicts?**: Minor race on "auto" tasks vs antigravity (both poll+PATCH claim; mitigated by post-claim status check in both). See also АУДИТ-4 (which was running concurrently).
- **Notes**: Has embedded rust flywheel source + rate limiting. Some ERROR tool_error in current run (from this audit's subagent calls: spawn_subagent cwd+isolation conflict, read_file errors) — agent-level, not service.

### 6. agentforge-watchdog.service
- **What**: watchdog.py — polls, detects loops (repeated lines), kills token-wasting procs, guardian resurrects with RAG (task_checkpoints), periodic /review/all. Uses 9090.
- **Status**: active light (14M), deprecation warnings on every poll (datetime.utcnow).
- **Needed?**: Yes for reliability.
- **Config**: Limits tight but appropriate (15t/2G/200%), Restart/10s, After=api.
- **Issues**: Deprecation spam; flywheel parts in it marked deprecated.

### 7. agentforge-flywheel.service + agentforge-flywheel.timer (disabled)
- **What**: oneshot timer (every ~20min + OnBoot + Persistent + RandomizedDelaySec=90) that runs `agentforge-runner --json continuous --top-n 2 --shadow`. Drives meta autonomy (promote-and-ab, winner detection) on top of per-task hooks.
- **Status**: inactive (dead), disabled. Timer parse-warn spam in journal until fixed (see below).
- **Needed?**: **Debatable / legacy in transition**. Header banners everywhere (PHASE 4 DELETION TARGET INFRA, RUST_FULL_MIGRATION_PLAN.md + PHASE4_REMOVAL_PLAN.md). Per-task flywheel now "DEFAULT" via AGENTFORGE_RUST_FLYWHEEL=1 in workers/runners (post_process_hook + grok_runner etc try direct binary or fallback to py phase2_3).
- **Config issues**:
  - Service: oneshot correct (Restart=no), Timeout=300, logs append to continuous_flywheel.log, After=api, EnvFile for rust_flywheel.env + AGENTFORGE_PURE_...
  - **Binary missing**: /home/eveselove/agentforge/rust/target/release/agentforge-runner does not exist (no target/ dir even; only gateway was built). Would fail if enabled.
  - Timer: malformed `Documentation=... (see CONTINUOUS_FLYWHEEL.md) man:...` → repeated "Invalid URL, ignoring".
- **flywheel vs worker?**: **NOT the same**. Old `agentforge-worker.service` template was literally `ExecStart=.../grok_worker.sh` + "Grok Worker (параллельный)" desc. "Worker" = task executor family (now split: grok + antigravity + builder). Flywheel = scheduled continuous closer / meta-loop.
- **Fix applied (timer)**: cleaned Documentation line (now valid; service still disabled).

## Other findings

- **Templates vs installed**: Templates in `/home/eveselove/agentforge/` contain heavy deprecation banners, old User=agx/Group, broader binds (0.0.0.0), file logging, PATH/PROTO C envs, StartLimitBurst etc. Installed user units are "clean" versions (no User=, localhost for api, limits added to most, no file logs for daemons, some After tweaks). No gateway template ever existed in source (added directly). install_services.sh is outdated (targets system units).
- **No WatchdogSec** on any unit (query specifically called out). None use Type=notify.
- **Dual API / split brain risk**: 8080 (python, tasks.db ~335) + 9090 (rust, checkpoints.db ~13M active). New tasks/creations use 9090. Old 8080 still polled by something (spurious?). Inconsistency possible for status/review.
- **Stray processes in cgroups**: long-running sidecars (the old gateway) started from *inside* antigravity/grok task trees get their cgroup "stuck" under the worker service even after reparent. Affects accounting + `systemctl status` tree view.
- **Rust flywheel state**: envs set to ON by default (in all workers, runners, post hooks, dispatcher). But since no `agentforge-runner` binary, pure path always falls back (with log "FAILED rc" or exception caught + py fallback). Continuous timer non-functional. Per-task hooks still provide some via python.
- **Builder idle + gateway was the only "broken"**.
- **No other timers loaded**. Only flywheel (disabled).
- **.bak files**: grok.service.bak (older, fewer limits). Ignored by systemd.
- **IDE sidecars**: antigravity (and agents) appear to launch `.antigravity-ide-server` (VSCode-like remote with language servers) for some workspaces — explains node processes + extra mem. Not a systemd service.

## Conflicts matrix
- gateway.service <-> stray manual gateway (port 9090) — **critical, fixed**
- grok <-> antigravity (race on "auto" tasks) — known, claim+verify mitigates (see АУДИТ-4 running in parallel)
- api (8080) <-> gateway (9090) — data split, not direct port conflict
- builder is "avoided" by grok (intentional)
- flywheel (if enabled) <-> non-existing binary (would fail)
- No explicit `Conflicts=` directives in units.

## Recommendations / actions taken
1. **Fixed immediately (as operator per AGENTS)**:
   - Killed stray gateway (969900) holding port.
   - Restarted agentforge-gateway.service → now stable.
   - Hardened [gateway.service](/home/eveselove/.config/systemd/user/agentforge-gateway.service): limits + StartLimit + RestartSec=10 + cleaned After/dep comment.
   - Fixed timer Documentation parse error (even though disabled).
   - Verified: port free, gateway serves /tasks (33), 200 OK.

2. **High priority**:
   - Rebuild rust runner if flywheel/continuous desired: `(cd /home/eveselove/agentforge/rust && cargo build --release)` (or use debug). Then consider enabling timer.
   - Decide on agentforge-api.service: migrate remaining users or explicitly mark deprecated + perhaps disable (after confirming no critical callers). Consider one-time data sync or deprecate the python queue.
   - Update AGENTS.md / docs (still reference 8080 in places) + any remaining hardcodes.
   - Add WatchdogSec=30..120 + sd_notify support? to critical units (grok, antigravity, gateway, watchdog, api).
   - Make After= consistent: change antigravity/builder/watchdog to `After=agentforge-gateway.service` (or network + gateway) since 9090 is truth.
   - Add logging redirects (or Accept=) for consistency with templates/flywheel.
   - For gateway: consider socket activation or `RestartPreventExitStatus=...` if bind errors persist.

3. **Medium**:
   - Investigate why 8080 still gets /review/all + /tasks (grep worktrees or agent-generated scripts?).
   - Review builder utilization + tags routing.
   - Clean .bak + old templates or sync them.
   - Monitor restart counters in future (add to watchdog?).
   - Cgroup hygiene: avoid long sidecars in worker slices, or use `systemd-run --user --scope` / slice for side services.

4. **Low / deprecation**:
   - Per PHASE4 notes: evaluate removing flywheel.timer/.service + python orchestration bits (continuous, some hooks) once runner binary is standard and per-task is proven.
   - Remove or comment heavy banners once migration complete.

## Verification commands used
- ls ~/.config/systemd/user/agentforge-* ; ls /home/eveselove/agentforge/*.service
- systemctl --user list-units --type=service,timer | grep agentforge
- systemctl --user status ... -l --no-pager for each
- journalctl --user -u ... -n 100
- ss -tlnp | grep 9090/8080 ; curl checks
- ps aux | grep ... ; cat /proc/<pid>/cgroup
- grep / read of all workers + gateway/src/main.rs + bin/*.sh + rust_post_process_hook.py
- Comparison of installed vs templates + .bak

**Post-fix state (as of end of audit)**: gateway healthy + managed. All other services healthy and purposeful (except legacy api + disabled/broken-without-bin flywheel). No failed units. Heavy but intended load from concurrent audits.

**Tags**: audit,systemd,infrastructure (as requested)

---
*Report written during/after direct inspection + fix. Follow-up PR/docs updates via Jules if needed per AGENTS.md (Variant B).*
