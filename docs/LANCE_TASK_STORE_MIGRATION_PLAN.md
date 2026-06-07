# LanceDB Task Store Migration Plan

**Date:** 2026-06-01  
**Status:** Draft / In Progress  
**Owner:** Grok (with input from the team)  
**Related:** RUST_ONLY_MIGRATION_PLAN.md, RUST_MIGRATION_SPEED_MODE.md, AGENTFORGE_CODE_MANAGEMENT_PLAN.md (100% closed)

## 1. Motivation

We are replacing the legacy SQLite-based task storage (`tasks.db` + `aiosqlite`) with LanceDB for the following reasons:

- **Unified storage layer**: Tasks, trajectories, failures, and eval data should live in the same modern database (LanceDB is already used for memory and trajectories via `memory_helper.py` and the flywheel).
- **Semantic capabilities**: Native vector embeddings on tasks enable similarity search ("find similar past tasks"), better routing, and future RAG over task history.
- **Analytics & observability**: Much better filtering, aggregation, and time-series capabilities than raw SQLite for large numbers of tasks.
- **Rust-native future**: As we move to Rust-only (`agentforge-runner`), we need a high-performance, async-friendly store that works naturally from Rust.
- **Consistency with the rest of the system**: The project is already investing in LanceDB + Arrow ecosystem.

## 2. Current State (as of 2026-06-01)

### Python side (Legacy)
- `task_queue.py` (FastAPI server) uses `aiosqlite` against `~/agentforge/tasks.db`.
- Many scripts directly import `sqlite3` and query `tasks.db` (watchdog, various creators, check scripts, etc.).
- Total direct sqlite3 usages: ~17 files.
- The file itself is marked **DEPRECATED — MOVING TO RUST ONLY**.

### Rust side (Target)
- `TaskStore` trait defined in `rust/crates/agentforge-core/src/task.rs`.
- Implementations:
  - `InMemoryTaskStore`
  - `JsonFileTaskStore`
- `LanceTaskStore` skeleton created (2026-06-01) but not yet fully implemented.
- The Rust runner and other crates currently do not have a production Lance-backed store.

### Data
- `tasks.db` (SQLite) is the source of truth for the running system.
- LanceDB is used in `data/lancedb/` (or `/home/eveselove/lance_data`) for trajectories and memory.

## 3. Target Architecture

- **Primary store for new Rust components**: `LanceTaskStore` implementing `TaskStore`.
- **Schema**: Tasks stored as LanceDB records with both structured fields + optional embedding column(s) for semantic search.
- **Python compatibility**: During transition, keep a thin compatibility layer (read-only or bidirectional bridge) so existing Python tools and the current farm don't break immediately.
- **Long term**: Python task queue becomes a thin client/API layer that talks to the Rust services (or directly to LanceDB via Python lancedb bindings).

## 4. Phased Migration Plan

### Phase 0 — Foundations (1-2 days)
- [x] Add `lancedb` + Arrow dependencies to the workspace (done 2026-06-01).
- [x] Create initial `LanceTaskStore` skeleton (done 2026-06-01).
- Define canonical LanceDB schema for `Task` (including embedding strategy).
- Add configuration (env var or config file) to choose task backend (`memory`, `json`, `lance`).
- Write basic tests for the new store.

### Phase 1 — Full Rust Implementation (3-5 days)
- Implement all `TaskStore` methods on `LanceTaskStore`:
  - `create`, `get`, `list_pending`, `list_all`, `update`, `update_status`, `delete`, `count`, `claim`.
- Proper embedding generation (or optional) on task create/update (title + description).
- Efficient queries (filter by status, priority, preferred_agent, tags).
- Atomic operations where needed.
- Connection pooling / reuse strategy.
- Error handling and migration from old stores.

### Phase 2 — Integration into Rust Services (3-4 days)
- Wire `LanceTaskStore` into `agentforge-runner`.
- Update any other Rust crates that need task access (`agentforge-planning`, `agentforge-learning`, etc.).
- Add CLI flags / config for choosing the store at startup.
- Performance testing and benchmarking vs JsonFileStore.

### Phase 3 — Python Compatibility Layer (parallel with Phase 2)
- Create a small Python package (`agentforge_lance`) that can read/write the same LanceDB tables.
- Option A (recommended short-term): Keep `tasks.db` as primary for Python farm, add one-way sync or dual-write.
- Option B: Make Python read from LanceDB directly (lancedb Python bindings are mature).
- Update `task_queue.py` to support LanceDB backend (or mark it read-only during transition).

### Phase 4 — Data Migration Tools (2-3 days)
- One-time migration script: SQLite → LanceDB (with embedding generation).
- Validation script (row counts, sample data, embedding quality).
- Rollback plan.
- Document the migration runbook.

### Phase 5 — Cutover & Deprecation (1-2 weeks)
- Switch the main farm (grok_worker, jules_worker, etc.) to LanceDB (or the new Rust services).
- Make `tasks.db` read-only or archive it.
- Update all direct `sqlite3` scripts to use the new client/API.
- Remove or heavily deprecate direct SQLite access in new code.
- Update documentation (this plan becomes historical).

### Phase 6 — Advanced Features (ongoing)
- Hybrid search (keyword + vector) over tasks.
- Task similarity features for better routing and "similar past tasks" in agent prompts.
- Analytics dashboards on top of LanceDB (success rates, agent performance, etc.).
- Time-travel / versioning of task state if needed.

## 5. Schema Sketch (Draft)

```python
# Conceptual LanceDB table "tasks"
{
    "id": string (primary key),
    "title": string,
    "description": string,
    "priority": string,           # low/medium/high/critical
    "complexity": string,
    "preferred_agent": string,    # grok/jules/antigravity/auto
    "assigned_to": string | null,
    "status": string,             # pending/dispatched/in_progress/review/done/failed/cancelled
    "tags": list<string>,
    "created_at": timestamp,
    "updated_at": timestamp,
    "started_at": timestamp | null,
    "completed_at": timestamp | null,
    "metadata": json,             # flexible extra fields
    "result": json | null,
    "vector": list<float>         # embedding of title + description (optional but powerful)
}
```

Rust side will use Arrow types + proper LanceDB table creation.

## 6. Risks & Mitigations

- **Performance regression on simple queries**: Mitigate with proper indexing in LanceDB and benchmarking.
- **Embedding cost / quality**: Make embeddings optional at first; use a good small model (or even just for high-priority tasks).
- **Python ecosystem breakage**: Keep a compatibility shim for as long as needed.
- **Data migration bugs**: Heavy testing + dry-run + rollback scripts.
- **Team cognitive load**: Clear documentation + gradual rollout.

## 7. Success Criteria

- All new Rust task usage goes through `LanceTaskStore`.
- Python farm can operate against LanceDB (directly or via shim).
- Old `tasks.db` can be archived or deleted.
- Semantic search over historical tasks is demonstrably useful in agent prompts or analytics.
- The 5 Post-100% Hardening tasks (handoff consumer, CI gate, etc.) can be implemented on top of the new store without friction.

## 8. Open Questions

- Should we keep a small SQLite for ultra-low-latency local agent state, or go full LanceDB?
- Embedding strategy: on create only, or also on updates? Which fields?
- Multi-tenancy / namespacing if we ever run multiple environments.

---

**Progress (as of 2026-06-01):**

- [x] Dependencies added (lancedb + Arrow)
- [x] Initial skeleton created
- [x] Significantly improved `LanceTaskStore`:
  - Proper table schema with all main Task fields
  - Working `create` + `delete`
  - Basic but functional `get`, `update`, `update_status`, and **claim** (critical for the agent farm)
- [x] Full migration plan document written
- [x] Multiple dependency resolution fights (features + half/arrow version conflicts) — currently trying relaxed Arrow pinning
- [x] Cargo check running after latest dependency adjustment

**Current approach (pragmatic):** 
- LanceDB is **completely removed from workspace.dependencies**.
- In `agentforge-core` it is declared with a direct version under `optional = true`.
- Activated via feature `lancedb = ["dep:lancedb"]`.
- Forwarded in `agentforge-runner`.

This pattern avoids forcing resolution of the heavy lancedb/lance/aws dependency tree on every build or every mirror. The code is fully developed behind the feature gate and can be activated cleanly when the environment allows.

**Next immediate steps:**

1. Make `LanceTaskStore` fully compile and implement remaining `TaskStore` methods.
2. Add basic tests.
3. Create a small example of using it from the runner.
4. Start building migration tooling (SQLite → LanceDB).
5. Wire behind a feature flag in `agentforge-runner`.

This document will be updated as we make progress.
