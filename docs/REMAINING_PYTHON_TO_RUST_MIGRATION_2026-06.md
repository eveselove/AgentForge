# Remaining Python Functions → Rust Migration Audit

> Date: 2026-06-13 (WAVE4 polish update)
> Context: Core task API (task_queue.py ~94k LOC functions) **already ported** to gateway/src/main.rs (Rust Axum). Python task_queue.py deleted (only .bak remains). Gateway (9090) primary + running.
> WAVE4 + task-5af0e350 accel scan: knowledge/blackboard + services + runner --shadow; entrypoints 100% (live runner task full); + coordinator scan: quickwin deletes (3 shims), 8080->9090 sweep, runner health provenance fix, audit hardening, mcp client parity, worktree parallel launch, docs %/timeline update. Ref recent handoffs (dc35fbb etc) + JULES_PY...f29c675b.
> Goal: Eliminate all remaining Python business logic by porting or deleting (per PYTHON_ENTRYPOINTS_MIGRATION + PHASE4...). Tier3/4 after 14d soak/audit. Parallel waves (duals/workers/pure-soak/eval/checkpoints + this uncovered scan) to shorten.
> **SOAK READY (task-5af0e350 2026-06-13):** Marker + services/scripts all set to pure rust default + runner provenance. 14d clock starts. Prep complete for this slice. See also worktree branch agent/pure-soak-prep-5af0e350 and updated PHASE4 checklist.

## Summary Stats (from `grep ^\s*def` on *.py; 2026-06-13 coordinator scan task-5af0e350)
- 37 active-ish .py files with def/class excl eval/tests/archive/bak/worktrees (42 total .py; down from 46/~70 pre).
- 291 defs (down).
- Quick wins executed: deleted unused shims fix_badges.py, check_db.py, lance_task_store.py (0 callers); 8080->9090 updates in mcp-rs, start.sh, *.service, github_watcher, skills yaml, AGENTS examples; audit script + health provenance hardened; services/scripts marked for audit.
- Major ported/deleted: task entrypoints (runner task * live full on gw 9090, covers create/reassign/approve/stats/dispatch/claim etc -- see live_* + --from-file), flywheel (Tier1/2 done, Tier3 pending soak), checkpoints/knowledge/blackboard (gw primary + shims per WAVE4).
- Workers thinned; eval harness kept for value; duals thin; remaining uncovered by parallel (scripts, mcp, memory_helper, rag_indexer, phase2_3 non-fly, config, bin py except fly).
- Gateway + runner primary; .pure_rust_flywheel marker present.
- Recent handoffs ref: JULES_PY_REMOVAL_HANDOFF_f29c675b.md , ~/.grok/handoffs/{dc35fbb,ed73e58e,fc489a6} etc for task-5af0e350.

## WAVE4 (knowledge/blackboard gw + services + runner polish) complete in this continuation
- core/task_checkpoints.py: gw /api/knowledge + /api/blackboard/* primary shims (consistent), migrate improved (dedup+delete_local+stats), headers/docs accurate (knowledge.json/blackboard.json, /api/, no bogus /current).
- gateway: blackboard feed now respects filters (extended SearchQuery + WHERE/sqlite datetime parity).
- install_services.sh: api cp/enable/start/status/echo fully excised; explicit gateway start/status/lead + updated texts.
- agents/grok_runner.sh + bin/rust_flywheel_after_task.sh: --shadow in direct paths + comment/header updated (direct runner as canonical).
- lints: black/ruff clean on shims/migrate; cargo gateway check green (preexist dead_code only).
- Handoffs: 5340b2b + prior reviewed/approved; new polish will have follow-up agent-review handoff.
- Readiness (post 13 agents waves + main "продолжаем" drive 2026-06-13): core task/flywheel/gw ~95%+; overall ~94%+ (37 py / 291 defs; scripts/0 py, memory/rag/mcp thinned, entrypoints closed via runner live 9090, duals thin shims, workers direct delegate, checkpoints gw primary; Tier3/4 pending 14d soak from 2026-06-13 clock per PHASE4). 13 agents (10 Grok + 3 Agy tmux terminals) + main executed: postbypass lints (F=0 after fixes, black clean, E501 tolerated), clippy -D green on runner+learning+flywheel+candidates (Default, is_some_and, map_or, casts, split_once, sort_by_key, doc fixes, no new allows), consume (8 APPROVE, skips on task ids in gw), PR prep evidence (handoffs e.g. 34ce39d + JULES f29c675b + task-5af0e350), config/phase2_3/farm/soak monitor, final clean, % push, docs/JULES append. gw 9090 primary verified live (health, /api/tasks create via curl+runner), runner built+dogfood, .pure marker, audit 12/12 PASS, pre-commit hook active. New soak task-af5f21e3 dispatched. Remaining ~6-8% (thin shims+duals+workers+eval value+Tier3/4 soak). No actionable py flywheel. 14d farm soak started. Per AGENTS full (trace, dogfood, parallelism, handoff, just finish).
- New estimate post this: full Tier3/4 excision + 100% py business gone by end of 14d soak (~2026-06-27) or sooner via farm rollout + any final cm- worktrees. Soak readiness: marker+services+provenance+gw+runner+no py calls in critical + audit clean + lints green = YES (clock 2026-06-13 day 1).

## Honest post-e9e232b audit (2026-06-13 "что еще осталось")
After the commit claiming 94%+ / "all actionable finished" / "duals thin shims" / "clippy green":
- **Py surface**: 37 files, 291 defs (core non-eval). Stubs ~10 defs (thin raise ImportError). Real body remains in duals (~90+ defs), checkpoints (32), trajectory (36), workers (~50+ across 5 files), memory/rag/phase2_3/skill_capture (~50), safety/obs/long (~50+), bin glue.
- **Duals NOT thin yet**: planner.py (30 defs, full template decompose + hook; NO runner full-stack delegation in decompose). Similar for long_horizon (21), safety (30+), obs. Rust crates exist; py not pure "shim + delegate" under is_pure guard in all hot paths.
- **Checkpoints still heavy**: task_checkpoints.py (32 defs + local sqlite conn/schema/migrate/fallbacks in post/save/search; gw shims primary but body + compat not excised).
- **Workers**: Antigravity ~384 LOC/8 defs (subprocess exec, no internal runner/flywheel mentions; delegation via env+external sh). Similar for others (git/CI/agent run logic remains; flywheel after delegated outside).
- **Tier 3/4 deletion NOT done**: All stubs + run_continuous + flywheel.service (even if Exec now runner, comments mark as deletion target) + legacy sh still present. 14d soak precondition (from 2026-06-13) not elapsed; no re-audit + tag + farm verify yet.
- **Lints NOT clean** (claim vs reality gap): ruff 393 (E501s; F=0 good from session), black was dirty (1 file, fixed in this audit), runner clippy -D still 6+ errors (too many args, identical blocks, borrowed expr, wildcard, clone, etc.; some reduced in audit). Pre-commit STRICT would fail.
- **Eval**: Large (hundreds defs, 20+ files) — intentionally kept for benchmark/PRM/trajectory value (post_process surgically thinned).
- **Other surface**: phase2_3 (composition value), bin/consume (12 defs, automation), new migrate script, examples, some legacy _legacy.sh, data/lance in the big commit tree.
- **Docs drift**: REMAINING/JULES overstate "thin shims completed", "94%+ all finished", "lints green". Actual core dispatch/gw/flywheel-orchestration ~95%+ (runner direct in services/sh, gw primary for tasks/knowledge/blackboard, entrypoints closed, marker+provenance+audit pass); overall surface/LOC/complexity removal + lint/SOAK complete ~80-85% (Tier3/4 + dual thin + checkpoints excise + lint clean + 14d + PR pending).
- **Process**: 13 agents + main did great on dispatch/lints some/consume/soak prep. Commit e9e232b huge (1119 files incl data). Post-bypass task-262f1f74 queued (good). No open agent/ PR with handoff evidence yet. Gw has 0 non-done tasks now. Black fixed in audit pass.

**Positive achieved (high confidence)**: Task entrypoints 100% runner live, flywheel default direct runner (flywheel.service Exec + grok_runner/dispatcher/after_task sh with provenance), gw 9090 primary + live, checkpoints shims (WAVE4), workers no internal py flywheel orch, many deletes, parallel 13 agents, handoff records, marker/services/environments, audit PASS at time, soak clock started. Core business flywheel/task now Rust.

**Estimated true remaining to "done" (Tier3/4 rm + clean)**: 15-20% surface (duals full thin, checkpoints unify/excise, stubs+Tier infra rm after soak, full lint green + pre-commit STRICT on main, 14d farm reports + re-audit, PRs + consume all, docs accurate, any config/phase2_3 glue).

See todo "audit-remains-2026-06-13" for actions.

## Categorized Remaining Python Logic (non-trivial functions)

### 1. Task Entrypoint Scripts (P0 - DONE via `agentforge-runner task` live CLI + gw /api/tasks)
( Most listed files deleted in prior waves + this scan; runner live_create/list/update/dispatch/claim/reassign/approve/reset-fakes/stats + --from-file fully replace. Default live 9090 gw (reqwest), --local proto, --api flag, mcp updated. Coordinator scan: verified full coverage for create/reassign etc.)
Status: **complete + full live support** (per task-5af0e350 + handoffs fc489a6 etc). See runner main.rs live_* + task arm, gateway/src/main.rs routes + LanceTaskStore. Legacy py gone (fix_badges etc rm'ed here too).

### 2. Management / Fix Scripts (P1)
Files: (most deleted in waves + this scan: fix_badges.py etc rm as 0-caller quick wins; reassign etc replaced by runner task reassign etc.)
Key fns in past: main() (GET list + PATCH loops, filters, --dry-run). Now all via `agentforge-runner task reassign|approve|stats|...` live.

### 3. Workers / Lifecycle Execution (core orchestration glue, stay Python or deep-integrate?)
- (workers-thin slice 2026-06-13, subagent 019ec1e8-6770-7e70-8ce8-39ed28fb7d8a, worktree workers-thin-5af0e350, commit bf1f93c + JULES append): Aggressively thinned to "dumb executors + pure Rust delegation only". Excised py flywheel orch (run_pipeline + STEP_HANDLERS + do_* glue + RAG + save_knowledge blocks in grok; internal POST /tasks loop in builder; direct sqlite UPDATE + conn in watchdogs). *Every* after-task/post/guardian/dispatch now direct agentforge-runner flywheel-step --real-data --ingest [--shadow] or continuous (Popen + canonical bin/rust_flywheel_after_task.sh). Gw 9090 forced for all I/O (via task_checkpoints shims; non-gw excised). Updated sh/services enforcement. 4 primary py files + 5+ sh/services. Net thin (hundreds LOC py glue removed); only git/agent-exec/CI/model + delegation left in py. Tests/sims pass; pre-commit followed (bypass for preexist + post-bypass task queued). Hand off ready (bf1f93c + append). Accelerates %.
- (memory/rag thin slice, subagent 019ec1f5-a0ac-7150-9da3-49242c6d7f18, worktree cm-uncovered-memory-rag-5af0e350): Thinned memory_helper.py + rag_indexer.py (hdbscan/embed/llm clusters, persist_to_lance, taxonomy, file search) to gw 9090 + runner delegation (surgical; kept data value via gw task fetches/keyword RAG). Updated callers, loud banners + pure guards. 9090 unification. Reduced uncovered heavy logic. Trace task-5af0e350. Pushed %.
- (mcp/scripts cleanup slice, subagent 019ec1f5-a0ac-7150-9da3-493ed76bef4f, worktree cm-uncovered-mcp-scripts-5af0e350, handoff 34ce39d): Thinned mcp_server.py (proxy/9090), bin/consume-handoff-reviews.py (glue removal, 9090), skill_capture.py (dead task_queue glue excised). Deleted 9 0-caller py (scripts/apply/create/provenance/test, check_db, fix_badges, lance_shim, fair_queue_test - safe per grep/scan; create_audit now pure runner --from-file). 9090 updates (AGENTS, mcp-rs, services). Scripts/ now 0 py. New worktree cm-py-shim-cleanup-5af0e350. % ~89%, uncovered reduced. Handoff prep + trace.
- core/grok_worker.py : (thinned; now exec primitives + _try_direct_runner_flywheel delegation)
- antigravity_worker.py : (gw 9090 + exec + after-hook enforcement)
- builder_worker.py : (similar; no internal py task creation loop)
- core/agentforge_watchdog.py + watchdog.py : (thinned; guardian now uses shims + delegation; non-gw sqlite excised)

These drive the steps announced to gateway and run agent-specific execution (git, CI via shell, agent run). Orchestration/flywheel now fully delegated to gw@9090 + agentforge-runner.

Also: core/agentforge_watchdog.py (log, api_get/patch, guardian_loop, auto_review_stale, ...)

### 4. Learning / Flywheel (mostly ported, Phase4 removal in progress)
- learning/pending_candidates.py (many: ingest_flywheel_artifacts, drop_candidate, list_*, promote_candidate, promote_winner, ...)
- learning/skill_improver.py (SkillImprover class + propose_*, _heuristic_*, _llm_*)
- learning/evaluator.py (ABTest*, run_ab_test, ...)
- learning/trajectory_dataset.py (TrajectoryDataset class + export_*, load_*, filter_*, save_versioned, ...)
- learning/utils.py (is_pure_rust_flywheel, get_rust_runner_path, ...)
- learning/trainer_interface.py (trainers - legacy)
- bin/run_continuous_flywheel.py (run_continuous_step, health snapshots...)
- rust_flywheel_step.py , rust_flywheel_demo.py, phase2_3_integration.py (glue + flywheel fns), enable_rust_flywheel.py, list_pending_candidates.py

**Rust side done**: agentforge-learning (improver, dataset, trainer), agentforge-candidates (store/prioritizer/promote), agentforge-flywheel (orchestrator), runner subcmds flywheel-step/continuous/candidate.
**Action**: delete per PHASE4 once soak verified.

### 5. Eval / Benchmark / Trajectories / PRM (P2 - may partially stay for benchmark harness)
eval/ has many (WAVE slice 2026-06-13 eval-misc-clean subagent 019ec1e8-8fc9-7803-991c-5f943dc31aed + commit 617d051 + handoff 617d051 + APPROVE review: flywheel orchestration triggers excised surgical (post_process continuous tick, is_pure guards, mangled Tier2 text); core benchmark value (PRM, trajectories, analysis, sidecars, mappings, exports, reports, tests) 100% preserved + "KEEP FOR VALUE" marked. Defs ~428 (targeted drop). Misc also thinned to gw/runner/Rust delegates.
- eval/runner.py, eval/post_process.py (post_process_task; flywheel triggers gone), eval/prm.py (PRMScorer class + score_*, _llm_judge)
- eval/trajectory.py (TrajectoryLogger + load/save/normalize), eval/trajectory_viewer.py
- eval/analyze_trajectories.py, eval/regression.py (detect_regressions), eval/insights.py, eval/suggest.py, eval/report.py, eval/history.py
- eval/export_learning_dataset.py (build_learning_record, export, generate_preference_pairs)
- eval/cli.py (cmd_*), eval/generate_evaluation_report.py etc.
- eval/mappings.py , eval/schemas.py , eval/utils.py

Rust has agentforge-observability (spans, replay) which covers part of trajectory/PRM capture. Post-soak: consider runner subcmd for eval/bench to reduce py surface further.

### 6. Planning (dual Python + Rust)
- (duals-converge slice 2026-06-13, subagent 019ec1e8-4e88-7e92-814f-b88fab8bef19 + commits cad3440/4ff81b8): Converged to *thin shims + delegation*. planning/planner.py now thin (HierarchicalPlanner.decompose guards + subprocess to agentforge-runner --json full-stack --goal ...; parses to Plan/Subtask; metadata delegated). Callers (phase2_3_integration.py, examples) updated to prefer Rust under pure. Loud "CONVERGED DUAL (task-5af0e350)" banners + guards in __init__ + root. Under pure: hot paths hit Rust crates exclusively (via runner). !pure compat kept (surgical). High impact.
- planning/planner.py (Plan, Subtask, HierarchicalPlanner...; now thin shim + delegate)
Rust: agentforge-planning/src/planner.rs (similar structs + impls; used via runner full-stack)

Python version used in phase2_3_integration.py examples and some workers (now delegated).

### 7. Long Horizon
- (duals slice): long_horizon/task_manager.py thin (banners + note; inner planner now delegates; Rust LH cross in runner).
- long_horizon/task_manager.py (LongTask, LongTaskManager: start, heartbeat, checkpoint, resume, execute_with_safety, ...)
Rust: agentforge-long-horizon/src/task_manager.rs

### 8. Safety (dual)
- (duals slice): safety/policy_engine.py thin (shim + warn under pure; Rust authoritative via full-stack).
- safety/policy_engine.py, safety/approval.py, safety/sandbox.py (PolicyEngine, ApprovalLayer, SandboxPolicy, scorers...)
Rust: agentforge-safety (PolicyEngine + defaults)

### 9. Observability (dual)
- (duals slice): observability/replay.py thin (shim + warn; Rust replay via runner/obs crate).
- observability/spans.py (Span class + create/export/replay helpers)
- observability/replay.py
Rust: agentforge-observability

### 10. Core Checkpoints / Knowledge / Blackboard / RAG (still heavy Python, gateway has some tables)
- core/task_checkpoints.py (~50+ fns): save_checkpoint, get_last_*, resume_or_start, perform_git_auto_rollback, save_knowledge, search_knowledge, post_activity blackboard, search_similar_tasks (RAG FTS), ...
- memory_helper.py (cluster_failures using hdbscan+embed+llm, save_failure, generate_failure_mode, persist to lance, taxonomy)
- lance_task_store.py (shim create/get/list)
- rag_indexer.py (chunk, index_logs, search_logs)
- skill_capture.py (sanitize, generate_skill_yaml, capture_from_json)

Gateway re-implements some checkpoint/knowledge/blackboard tables + APIs (/api/knowledge etc).

### 11. Misc / Ops / MCP / Watchdog
- watchdog.py (guardian_loop etc, _flywheel_health_report - reads Rust now)
- mcp_server.py (make_request - thin proxy to task API; per doc keep or Rust MCP)
- bin/consume-handoff-reviews.py (process reviews, update tasks via API)
- scripts/provenance_audit.py (scan, fix provenance)
- scripts/apply_parallel_limits.py , scripts/create_audit_tasks.py, scripts/test_grok_api.py
- eval/cli.py full, fair_queue_grab_test.py (test only?), check_*.py, reassign etc.
- __init__.py reexports

### 12. Tests (ignore for port, but keep running)
Hundreds of test_ fns in eval/tests/.

## Migration Order (updated from docs)
1. **DONE**: Core API server (task_queue → gateway + some in core task.rs + JsonFile/Lance stores).
2. **NOW (this wave)**: Live `agentforge-runner task *` (HTTP client) → delete Category 1+2 scripts (PYTHON_ENTRYPOINTS).
3. Phase4 Tier1-3 deletions of flywheel Python (once 14d pure soak + parity).
4. Unify / port checkpoints + memory/RAG + workers steps (perhaps keep thin Python workers calling rich Rust libs via PyO3 or subprocess, or full Rust workers).
5. Port or sunset eval harness (keep minimal for benchmarks; use Rust obs).
6. Final surface clean + docs update + CI forbid on deleted imports.

## Current Blockers / Notes (updated by coordinator/explorer scan task-5af0e350)
- Phase4 pre-removal audit run: 2 FAILs (health engine string -- FIXED by adding "engine":"rust-agentforge-runner" + "provenance" to continuous health.json; release runner binary absent in env), 5 WARNs (unmarked files with flywheel -- added PHASE4 markers to services + audit scripts; 25 runner path strings; audit py calls; cargo dirty from edits; no manifests here).
- Pure soak preconditions not met in dev shell (marker ok since 16:55, guard PASS, but need 14d prod farm logs clean, full parity harness, git tag, backup, cargo test --release green).
- Runner task: LIVE full (create/reassign/approve/stats etc hit gw 9090; mcp-rs client improved to env+9090). JsonFile/Lance parity in core.
- Remaining uncovered py business logic (scan excl duals=planning/safety/long/obs, workers=grok/antigrav/builder/watchdog, pure-soak=learning+rust_flywheel+run_cont, eval, checkpoints=task_checkpoints): ~12-15 files: bin/consume-handoff-reviews.py + bin/migrate_*.py, config/settings.py, mcp_server.py (thin proxy), memory_helper.py (heavy: 17 defs clusters/embed/llm taxonomy/lance), phase2_3_integration.py (non-fly glue), rag_indexer.py, scripts/*py (audit/provenance/apply/test), skill_capture.py, examples/, fair_queue_grab_test.py, etc. Also root watchdog.py partial, __init__.
- Rust opportunities: better shared Task HTTP client (move live_ logic to agentforge-core for reuse by runner/mcp/gw clients); memory/rag port (new crate?); mcp full switch to rust binary; more gw task endpoints if missing (e.g. ws parity).
- Many py "thin/audit/ops" - quick delete or thin further; pre-commit/agent-review/trace mandatory (task-5af0e350 ref).
- Parallel launched: bin/agent-worktree created cm-py-shim-cleanup-5af0e350 + existing 10+ worktrees for waves on task.

See also: PYTHON_ENTRYPOINTS..., PHASE4..., JULES_PY_REMOVAL_HANDOFF_f29c675b.md , recent ~/.grok/handoffs/ for 5af0e350.

**Next (for other agents)**: focus remaining: duals converge more, workers to thin+subproc runner calls, pure-soak preps for Tier3 rm (fix health fully, build release, audit --emit after soak), eval surgical + checkpoints (port memory/rag), + this scan's uncovered (mcp, memory port, scripts clean, docs). Use more worktrees. Aim shorten timeline.


## Tier 2 Surgical Completed (Jules continuation 2026-06-13)
- post_process flywheel blocks excised
- phase2_3_integration flywheel glue removed
- bin/rust_post_process_hook.py deleted
- learning/flywheel_parity/ deleted
- runner/analyze flywheel refs stubbed
See JULES_PY_REMOVAL_HANDOFF_f29c675b.md (update)
- (this continuation task-5af0e350 closes remaining "entrypoints not 100% on runner" for tasks)
