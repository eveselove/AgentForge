# AgentForge

**Multi-Agent Orchestration System for Autonomous Software Engineering**

AgentForge is a production-grade task queue and orchestration layer that turns multiple specialized AI agents (Grok, Jules, Antigravity) into a reliable, self-improving, token-efficient engineering workforce. It coordinates complex software development tasks across repositories using isolated Git worktrees, YAML-driven skills/playbooks, semantic memory (RAG + failure clustering), built-in self-verification, and automatic self-expansion.

The system is designed for long-running, high-stakes engineering work on real codebases (Rust, Python, web, mobile, infra) with strong safety guardrails.

> **2026-06 Update (Turbo Phase 2/3)**: We have completed scoped Phase 1 (Evaluation + Observability + PRM + deep tracing + LLM judge) at 100% in aggressive multi-agent turbo mode. We are now simultaneously building **Phase 2 Learning Flywheel** and **Phase 3 Long Horizon + Safety** foundations in parallel (learning/, planning/, safety/, long_horizon/, observability/ modules). See `AGENTFORGE_FRONTIER_ROADMAP.md` for the full aggressive plan.

**Current Status: Phase 2/3 foundations + PURE RUST ORCHESTRATION DEFAULT CUTOVER + SERVICE FIX ACHIEVED (2026-05-31 10:42). 97% overall (Phase3 95% green). 1.41 MB binary sole default engine on 243 cands, continuous success, services patched. HOW_TO... one-pager + crisp 100_PERCENT_READINESS_CHECKLIST.md + 100_PERCENT_VICTORY_ANNOUNCEMENT.md + all roadmaps/TURBO/JULES/PENDING one-last-time refreshed + cross-linked. 14d soak active. DOCS AND 100% READINESS MAXIMIZED.**

**🚀 Major 2026-06+ Direction — Full Rust-Only Migration Active**: Pure Rust flywheel is the default. We are now executing a complete transition to **Rust-only operation** (removal of Python as runtime dependency for core orchestration, task management, and agent conveyor). 

See the living plan: `RUST_ONLY_MIGRATION_PLAN.md`

All new core development targets `agentforge-runner` and Rust crates. Legacy Python paths are being deprecated aggressively.
- 100_PERCENT_READINESS_CHECKLIST.md (97% gates + verdict + 14d soak)
- 100_PERCENT_VICTORY_ANNOUNCEMENT.md (meaning + exact rollback via bin/disable_pure_rust_flywheel.sh + soak measurement + evidence)
- AGENTFORGE_FRONTIER_ROADMAP.md (cutover milestone banner)
- HOW_TO_RUN_PURE_RUST_FLYWHEEL_TODAY.md + bin/make_pure_rust_flywheel_default.sh
Every Antigravity architecture session, deep review, or complex refactor automatically feeds rich trajectories into the continuous learning engine (Rust-accelerated export → proposals → `pending_candidates/` → timer-driven A/B & promotion loops).

- Full story, benefits, exact disable instructions (`DISABLE_RUST_FLYWHEEL=1`), and the canonical "What this means for Antigravity tasks" blurb: see **`ANTIGRAVITY_DEFAULT.md`**.
- Operational commands + systemd: `ENABLE_RUST_FLYWHEEL.md`.
- Live evidence: 236+ real candidates, 3 promoted, closed-loop timer active, `python -m agentforge.list_pending_candidates`.

New top-level integration artifact: `agentforge/phase2_3_integration.py` + `examples/phase2_3_unified_power_demo.py`.
Full composition now works: `run_long_task_with_planning_safety_and_prm_logging` (planning + LongTaskManager + PolicyEngine + automatic PRM + spans + eval runner + immediate TrajectoryDataset capture). The learning flywheel, hierarchical planning, safety guardrails and rich observability are no longer isolated modules — they are a single coherent, instrumented, self-improving system.

---



## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           HUMAN / IDE / API                                  │
│                    (POST /tasks, MCP from Antigravity, Dashboard)            │
└─────────────────────────────────────┬───────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        AgentForge Task Queue (FastAPI :8080)                │
│  • SQLite persistence (tasks + checkpoints + webhooks)                       │
│  • WebSocket real-time updates                                               │
│  • Automatic agent routing (resolve_agent)                                   │
│  • Skill/playbook selection (select_skill by tag overlap)                    │
│  • MoA / best-of-n orchestration endpoints                                   │
│  • Self-expansion API (/skills/capture)                                      │
└─────────────────────────────────────┬───────────────────────────────────────┘
                                      │ dispatch → dispatcher.sh
                                      ▼
┌──────────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐
│   Antigravity│   │     Grok     │   │    Jules     │   │   Gemini     │
│   (AGY)      │   │   (Primary)  │   │  (Background)│   │              │
└──────┬───────┘   └──────┬───────┘   └──────┬───────┘   └──────┬───────┘
       │                  │                  │                  │
       │ (explicit only   │ (default for     │ (PRs, docs,      │
       │  + deep tags)    │  most tasks)     │  tests-heavy)   │
       ▼                  ▼                  ▼                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Execution Runners (per-agent .sh)                     │
│  • Git Worktree Isolation (/tmp/agentforge/{task_id})                        │
│  • Skill system_prompt injection                                             │
│  • RAG context from LanceDB memory                                           │
│  • HITL feedback history replay                                              │
│  • Priority-based flags (--check, --best-of-n)                               │
│  • Post-execution CI (cargo test / skill ci_checks)                          │
│  • Memory save on success / failure clustering                               │
│  • Self-expansion hook (tool-creation tasks)                                 │
└─────────────────────────────────────┬───────────────────────────────────────┘
                                      │
                    ┌─────────────────┼─────────────────┐
                    ▼                 ▼                 ▼
            ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
            │  Watchdog    │  │   Memory     │  │  MCP Server  │
            │  (Guardian)  │  │  (RAG+Fail)  │  │  (Tool API)  │
            └──────────────┘  └──────────────┘  └──────────────┘
```

---

## Roles (Agent Personas)

### Antigravity (AGY / "Antigravity IDE")

- **Role**: Architect, deep analyst, code reviewer, orchestrator of complex work.
- **Strengths**: Architecture, complex logic, security reviews, large-scale refactoring, algorithm design, cross-system analysis.
- **Capabilities** (from agent_cards): file_edit, terminal, ssh, browser, subagents, MCP.
- **Models**: Gemini, Claude Opus/Sonnet, GPT variants.
- **When selected**: `complexity=complex` or tags containing `architecture`, `analysis`, `review`, `algorithm`, `web`, `browser`, `mcp`, `scrape`.
- **Invocation**: `agy --prompt "..." --yes` (headless) or full Antigravity IDE chat. In AgentForge it is often triggered manually or via MCP from within Antigravity sessions.
- **Location**: Typically Windows PC / powerful workstation (SSH-accessible).
- **2026-06 Default superpower**: All Antigravity work now automatically fuels the Rust self-improving flywheel (see `ANTIGRAVITY_DEFAULT.md` — "What this means for Antigravity tasks").

### Grok (Primary Executor / "Grok Build")

- **Role**: Fast, reliable multi-agent generalist. The workhorse for the majority of tasks.
- **Strengths**: Speed, Rust, debugging, multi-file edits, server-side work, rapid iteration.
- **Capabilities**: file_edit, terminal, git, multi_agent (spawns subagents), full suite of skills (/check, /implement, /design, /arena, /best-of-n, etc.).
- **Key Flags** (passed by runners):
  - `--always-approve` (headless automation)
  - `--check` (self-verification via the `/check` skill – see below)
  - `--best-of-n N` (parallel MoA / Arena proposals)
- **When selected**: Default for `rust`, `cargo`, `server`, `fix`, routine engineering (most tasks).
- **Location**: Jetson AGX (or other Linux boxes) running the Grok CLI.
- **Special behavior in AgentForge**: Heavy use of worktree isolation, skill injection, RAG, CI gates, and automatic self-expansion hooks.

### Jules

- **Role**: Asynchronous background specialist focused on GitHub PR lifecycle.
- **Strengths**: Writing tests, documentation, refactoring, creating clean PRs without blocking the foreground.
- **Models**: Gemini 2.5 Pro (cloud).
- **When selected**: `complexity=simple` + tags `test` or `docs`, or explicit `preferred_agent=jules`.
- **Behavior**: Runs `jules new --repo ... --parallel N` (for high/critical). Creates PR remotely. Does not perform local edits in the traditional sense (uses cloud execution).
- **Isolation**: Still creates a worktree for consistency / clean environment.

### Guardian (Safety & Oversight Layer)

"Guardian" is the collective name for the safety, verification, and anti-waste subsystems:

- **Watchdog Daemon** (`watchdog.py` + systemd `agentforge-watchdog.service`): Continuously polls active tasks, analyzes agent logs for repetition/loop patterns (same error >5 times, >20 repetitive tool calls), kills the corresponding processes (via `pgrep` on worktree dir + task_id), and marks the task `failed` with a token-saving message. This is the primary runtime guardian against infinite loops and token hemorrhage.
- **Self-Verification (`/check` skill + `--check` flag)**: When priority is high/critical, runners automatically add `--check`. This spawns an independent verifier subagent (general-purpose) that follows the full Phase A (trace review) + Phase B (code review, build, test) protocol defined in the skill. The verifier must output `VERDICT: PASS` or `VERDICT: FAIL` with structured evidence. FAIL triggers fixes (up to 3 iterations in the loop).
- **CI Gates**: Every completed task (unless overridden by skill) runs language-appropriate checks (`cargo clippy/test/build`, `pytest`, etc.). Skill-defined `ci_checks` take precedence and are executed inside the worktree.
- **HITL (Human-in-the-Loop) Feedback Loop**: User rejections are captured in task `result`/`description`, replayed on retry with explicit "=== ВАЖНО: ИСТОРИЯ ОТКАЗОВ ПОЛЬЗОВАТЕЛЯ ===" blocks so agents never repeat the same mistakes.
- **Failure Clustering & Taxonomy**: Failed trajectories are saved to a dedicated LanceDB table and can be clustered (HDBSCAN) for systemic pattern analysis.
- **Resource Limits**: Log size caps, per-skill timeouts, priority-based escalation to heavier verification.

Guardian ensures that AgentForge remains economical and trustworthy even when running 24/7 on autonomous engineering workloads.

---

## Core Processes & Mechanisms

### Git Worktrees (Isolation)

Every task receives a dedicated, isolated Git worktree:

```bash
WORKTREE_DIR="/tmp/agentforge/${TASK_ID}"
git -C "$PROJECT_DIR" worktree add "$WORKTREE_DIR" -b "agentforge/$TASK_ID"
# ... agent runs inside WORKTREE_DIR ...
git -C "$PROJECT_DIR" worktree remove --force "$WORKTREE_DIR"
```

- **Why**: Concurrent agents (Grok + Jules + Antigravity) never collide on the same checkout. Each has a clean `HEAD` on its own branch.
- **Cleanup**: Guaranteed via `trap cleanup_worktree EXIT INT TERM` in every runner.
- **Naming**: Branch `agentforge/{short-uuid}`, directory under `/tmp/agentforge/`.
- **Integration**: Also used by the core `~/.grok` system (`worktrees.db`, handoffs) for session-level git isolation.

This is the foundational primitive that makes safe parallel multi-agent work possible.

### Watchdog (Token Guardian)

See the dedicated Guardian section above. Polling loop + log heuristics + surgical `kill -9` + status PATCH. Runs as a hardened systemd service.

### Task Lifecycle

`pending` → `dispatched` (routing + skill selection) → `in_progress` (runner start) → `review` / `done` / `failed`

- After runner finishes + CI passes → `review` (human or secondary agent can promote to `done`).
- Failures (CI or Watchdog) → `failed` with rich result text.
- Re-dispatch of failed tasks is supported and carries full HITL history.

### Skills / Playbooks (Self-Expansion / Tool Creation)

YAML files in `~/agentforge/skills/*.yaml` (and `~/.grok/skills/*/SKILL.md` for the base Grok layer).

**Selection** (`select_skill`):
- Explicit `skill` field on task wins.
- Otherwise, tag intersection: task `tags` ∩ skill `required_tags`.

**Injection**:
- The entire `system_prompt` from the YAML is prepended inside a `=== PLAYBOOK: xxx === ... === END PLAYBOOK ===` block.
- Runners also merge RAG results and HITL history.

**Self-Expansion** (the killer feature):
- Any agent that creates a reusable parser, crawler, deploy script, API client, etc., is *required* (by the `tool-creation` skill and hooks in runners) to synthesize a high-quality standalone `system_prompt` and persist it via:
  - `python /home/agx/agentforge/skill_capture.py --stdin < JSON`
  - `POST /skills/capture`
  - Direct file write
- The new skill immediately becomes available for future tasks with matching tags.
- This turns AgentForge into a **living, compounding intelligence system**.

Example skills shipped: `tool-creation`, `architecture-review`, `frontend-feature`, `rust-fix`, etc.

### Memory System (RAG + Failure Intelligence)

- **Successful trajectories**: Saved via `memory_helper.py save` into LanceDB (`agentforge_memory`) using `all-MiniLM-L6-v2` embeddings. Injected into future prompts via `memory_helper.py search`.
- **Failures**: Saved to `agentforge_failures` table + optional HDBSCAN clustering + taxonomy JSON for root-cause analysis.
- Enables agents to "remember" what worked and what didn't across months of work.

### MCP Server

`mcp_server.py` (stdio transport) exposes the entire Task Queue as tools consumable by any MCP-capable client (especially Antigravity IDE). Allows an architect agent living in Antigravity to create, dispatch, monitor, and steer tasks without leaving its native environment.

### MoA / Arena / Best-of-N

The Task Queue has dedicated endpoints (`/moa/propose`, `/moa/aggregate`) and runners honor `--best-of-n` (critical priority). Proposals run in parallel (often via subagents or multiple Grok instances), then an aggregator (or Jules) synthesizes the best result. Directly maps to the `arena` and `best-of-n` skills in the Grok layer.

### Dashboard & Observability

- Real-time HTML dashboard served at `/dashboard` (WebSocket-powered).
- Full task list, status, logs, badges.
- Systemd services + `logs/*.log` + health endpoints.
- `github_watcher.sh`, `healthcheck.sh`, `check_status.py` helpers.

---

## Deployment & Operations

### Services (systemd)

- `agentforge-api.service` — the FastAPI task queue
- `agentforge-worker.service` — (optional) background workers
- `agentforge-watchdog.service` — the Guardian
- `agentforge.service` — umbrella

Install via `install_services.sh`.

### Starting Manually

```bash
# Terminal 1
uvicorn task_queue:app --host 0.0.0.0 --port 8080 --reload

# Terminal 2 (Guardian)
python3 watchdog.py
```

Or use the provided `start.sh`.

### Environment

- Primary project: `/home/agx/planlytasksko` (configurable)
- DB: `~/agentforge/tasks.db`
- Vector memory: `/home/agx/lance_data`
- Logs: `~/agentforge/logs/`

### GitHub Integration

Jules creates real PRs against the configured repo (`eveselove/planlytasksko` by default). GitHub watcher can feed new issues back into the queue.

---

## Key Slash Commands & Skills (Grok Layer)

When a Grok instance is spawned inside a worktree, it has access to the full skill library:

- `/check [focus]` — Self-verification (the verifier prompt is reproduced verbatim in the skill). Spawns independent general-purpose subagent.
- `/implement` — Full implement-review-fix actor-critic loop.
- `/design` — Design doc + review loop until consensus.
- `/arena`, `/best-of-n` — Mixture-of-Agents / parallel proposers + judge.
- `/agent-review` — Hands diff to Jules (or named reviewer) for independent code review.
- `tool-creation` / `/create-skill` — Self-expansion ritual.
- Many domain skills (docx, pptx, xlsx, ssh-tunnel, merge-conflict-resolver, etc.).

All of these are leveraged automatically by the runners via flags and playbook injection.

---

## Development & Contributing

- The system is self-hosting: many improvements to AgentForge itself are performed *by* AgentForge agents.
- To add a new capability: implement it, then capture it as a skill.
- All changes to the core should go through the `/check` + review process.

---

## Philosophy

AgentForge embodies three principles:

1. **Isolation** — Git worktrees + process sandboxing + strict cleanup make parallel autonomous agents safe.
2. **Compounding Intelligence** — Every solved problem permanently upgrades the entire fleet via skills and memory.
3. **Relentless Verification** — Watchdog + `--check` + CI + HITL + failure analysis = high trust even at scale.

The result is a system that can run for weeks, burn through large engineering backlogs, create real PRs, and get demonstrably better over time — while protecting the operator from runaway token spend.

---

## Status

Active in production on the planlytasksko family of repositories. Continuously improved by its own agents.

For operational status, open the dashboard or query the `/health` and `/tasks` endpoints.

---

*Built with Grok, Jules, Antigravity, and a healthy dose of Guardian discipline.*
