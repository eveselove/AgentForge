# Remaining Python Functions → Rust Migration Audit

> Date: 2026-06-13 (WAVE4 polish update)
> Context: Core task API (task_queue.py ~94k LOC functions) **already ported** to gateway/src/main.rs (Rust Axum). Python task_queue.py deleted (only .bak remains). Gateway (9090) primary + running.
> WAVE4: knowledge + blackboard shims complete (gw primary /api/* first + fallback; migrate fn + deprecate); services install gw-focused (api legacy fully dropped from launch); flywheel direct runner (shadow supported); entrypoints mostly excised.
> Goal: Eliminate all remaining Python business logic by porting or deleting (per PYTHON_ENTRYPOINTS_MIGRATION + PHASE4_FLYWHEEL_REMOVAL_CHECKLIST). Tier3/4 after 14d soak/audit.

## Summary Stats (from `grep ^\s*def` on *.py; 2026-06-13 wave)
- 46 active-ish .py files with def/class (excl tests/archive/bak; down from ~70+ pre-waves).
- 419 defs (down from ~580+).
- Major ported/deleted: task entrypoints (runner task live CLI), flywheel orchestration (Tier1/2/3 stubs + direct runner), checkpoints/knowledge/blackboard (gw primary + shims).
- Workers thinned to delegates + execution; eval mostly data harness (keep value); duals (planning/safety/long/obs) thin wrappers.
- Gateway + runner dogfood primary. 

## WAVE4 (knowledge/blackboard gw + services + runner polish) complete in this continuation
- core/task_checkpoints.py: gw /api/knowledge + /api/blackboard/* primary shims (consistent), migrate improved (dedup+delete_local+stats), headers/docs accurate (knowledge.json/blackboard.json, /api/, no bogus /current).
- gateway: blackboard feed now respects filters (extended SearchQuery + WHERE/sqlite datetime parity).
- install_services.sh: api cp/enable/start/status/echo fully excised; explicit gateway start/status/lead + updated texts.
- agents/grok_runner.sh + bin/rust_flywheel_after_task.sh: --shadow in direct paths + comment/header updated (direct runner as canonical).
- lints: black/ruff clean on shims/migrate; cargo gateway check green (preexist dead_code only).
- Handoffs: 5340b2b + prior reviewed/approved; new polish will have follow-up agent-review handoff.
- Readiness: core task/flywheel/gw ~90-95%; overall ~82%+ (workers/eval/infra/duals remaining ~18%; eval/data value kept; Tier3/4 py pending soak per PHASE4).

## Categorized Remaining Python Logic (non-trivial functions)

## Categorized Remaining Python Logic (non-trivial functions)

### 1. Task Entrypoint Scripts (P0 - DONE via `agentforge-runner task` live CLI + gw /api/tasks)
( Most listed files deleted in prior waves; runner live_create/list/update/dispatch + --from-file etc cover create/reassign/approve/stats.)
Status: **complete** (direct to 9090 gw; provenance rust-agentforge-runner). Legacy scripts gone or stubs. See runner main.rs + bin/phase4_audit.

### 2. Management / Fix Scripts (P1)
Files: fix_antigravity_tasks.py, reassign.py, fix_stuck_tasks.py, reset_fakes.py, approve_tasks.py, check_status.py, show_agent_stats.py, fix_badges.py

Key fns:
- main() (GET list + PATCH loops, filters, --dry-run)

### 3. Workers / Lifecycle Execution (core orchestration glue, stay Python or deep-integrate?)
- core/grok_worker.py : do_dispatch, do_git_clone, do_grok_start, do_grok_done, do_ci_start, do_ci_done, do_review, run_pipeline, fetch_task_from_gateway, submit_completion_to_gateway, compute_diff_for_submit, ...
- antigravity_worker.py : load_config, api_request, get_tasks_for_antigravity, select_model, execute_task, main
- builder_worker.py : similar load/execute/main

These drive the steps announced to gateway and run agent-specific execution (git, CI via shell, agent run).

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
eval/ has many:
- eval/runner.py, eval/post_process.py (post_process_task), eval/prm.py (PRMScorer class + score_*, _llm_judge)
- eval/trajectory.py (TrajectoryLogger + load/save/normalize), eval/trajectory_viewer.py
- eval/analyze_trajectories.py, eval/regression.py (detect_regressions), eval/insights.py, eval/suggest.py, eval/report.py, eval/history.py
- eval/export_learning_dataset.py (build_learning_record, export, generate_preference_pairs)
- eval/cli.py (cmd_*), eval/generate_evaluation_report.py etc.
- eval/mappings.py , eval/schemas.py , eval/utils.py

Rust has agentforge-observability (spans, replay) which covers part of trajectory/PRM capture.

### 6. Planning (dual Python + Rust)
- planning/planner.py (Plan, Subtask, HierarchicalPlanner, DependencyGraph, execute, topological_sort, ...)
Rust: agentforge-planning/src/planner.rs (similar structs + impls)

Python version used in phase2_3_integration.py examples and some workers.

### 7. Long Horizon
- long_horizon/task_manager.py (LongTask, LongTaskManager: start, heartbeat, checkpoint, resume, execute_with_safety, ...)
Rust: agentforge-long-horizon/src/task_manager.rs

### 8. Safety (dual)
- safety/policy_engine.py, safety/approval.py, safety/sandbox.py (PolicyEngine, ApprovalLayer, SandboxPolicy, scorers...)
Rust: agentforge-safety (PolicyEngine + defaults)

### 9. Observability (dual)
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

## Current Blockers / Notes
- Runner task subcmds currently only hit local /tmp JSON store (prototype). Gateway is source of truth for live farm.
- No full parity for all gateway endpoints yet in Rust TaskStore (JsonFile is separate).
- Many Python now are "bridges" or "only for tests/parity" - delete when safe.
- Pre-commit + agent-review mandatory on any deletion/rewrite.
- Traceability: every commit must ref a task id.

See also: PYTHON_ENTRYPOINTS_MIGRATION.md, PHASE4_FLYWHEEL_REMOVAL_CHECKLIST.md, AGENT_RUST_TRANSITION_GUIDE.md, rust/README.md.

**Next action**: Implement live API support in runner task CLI (use reqwest) + add reassign/approve/stats subcmds modeled on the Python mains. Then mass-delete scripts + update callers.


## Tier 2 Surgical Completed (Jules continuation 2026-06-13)
- post_process flywheel blocks excised
- phase2_3_integration flywheel glue removed
- bin/rust_post_process_hook.py deleted
- learning/flywheel_parity/ deleted
- runner/analyze flywheel refs stubbed
See JULES_PY_REMOVAL_HANDOFF_f29c675b.md (update)
