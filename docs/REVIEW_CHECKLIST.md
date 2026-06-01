# AgentForge Mandatory Review Checklist

**Version**: 1.0  
**Created**: 2026-06 (from real usage in 2026-05-31 closure wave)  
**Status**: **Mandatory** for all agent-generated changes (P2 B5 + AGENTS.md "hard requirement")  
**Owner**: All Grok/Jules/Antigravity agents + humans following the process

This is the lightweight, enforceable self-check that agents **must** complete before invoking the `agent-review` skill and before marking any work "ready" or opening a PR.

It was synthesized directly from defects repeatedly surfaced by independent Jules reviews during the final Phase 2 closure wave (tasks including 85b2d0e6 pre-commit hardening, 14c220fc mandatory-docs, p1-bp-direct branch protection script, mirror strategy handoff 9471de35, and related docs + runner updates).

## 1. Environment & Isolation (do this first, every time)
- [ ] Created isolated worktree via `bin/agent-worktree create <slug>` (or equivalent `git worktree add`) — **mandatory** for parallel waves
- [ ] Ran `./bin/install-pre-commit` in the fresh worktree/branch and verified the hook is active (`.git/hooks/pre-commit` points to repo copy)
- [ ] Branch name follows documented convention (`agent/<kebab>-<taskid>`, `task/<id>`, `jules/<session>`, etc.)
- [ ] First commit (or branch description) captures the originating Task ID or Jules session ID

## 2. Development & Commit Discipline
- [ ] **Every** commit message contains a Task ID (`task 14c220fc`) **or** Jules session ID (enforced by pre-commit + validate-commit-msg)
- [ ] `bin/pre-commit` passed cleanly on every commit (or explicit documented emergency bypass + immediate follow-up "post-bypass cleanup" task created in queue)
- [ ] No `PRECOMMIT_BYPASS*` used routinely; any bypass noted in commit body
- [ ] Changes kept small and focused (one logical concern per PR preferred)

## 3. Rigorous Self-Verification (before any handoff)
Run the equivalent of the pre-commit gates + targeted manual review of the actual diff:

- [ ] Rust files: `cargo fmt -- --check && cargo clippy --workspace -D warnings`
- [ ] Python files: `ruff check --fix && black --check`
- [ ] Shell scripts touched: `shellcheck` (run under `PRECOMMIT_STRICT=1` when possible)
- [ ] Relevant tests / harnesses executed for changed code paths
- [ ] **Diff audit against last-wave defect classes** (the most common findings):
  - [ ] No stdout pollution in functions or code paths intended for capture (`$(func)`, `RULESET_PAYLOAD=$(...)`, JSON fast-paths). All diagnostics use `>&2`. Auth banners and progress messages conditioned or suppressed for machine paths.
  - [ ] No fragile text transforms on structured data (JSON, YAML, etc.). `sed -i 's/"key": ".*"/.../'` and similar are **banned** in new code; use `python3 -c 'import sys,json; ...'` round-trip + explicit field override instead.
  - [ ] Correct data sources in hooks and capture logic. Pre-commit traceability does **not** use `git log -1 --pretty=%B` (that always sees the *previous* commit). Use `prepare-commit-msg` hook data, `.git/COMMIT_EDITMSG`, or the index.
  - [ ] No GNU-only flags without fallback/portability guard (`xargs -r` fails on BSD/macOS; prefer `xargs -r || xargs` or `grep ... | xargs` patterns).
  - [ ] Exit codes propagate. No `while read ...; do ... exit 1; done | pipeline` (subshell swallows `set -e`). Use `set -o pipefail` + explicit checks or temp files.
  - [ ] Validation **before** mutation. Any JSON/YAML payload built for `gh api`, external calls, or config application is validated (`python3 -c 'import sys,json; json.load(sys.stdin)'`) *before* the side-effecting step. Fail fast with clear `>&2` message.
  - [ ] `set -euo pipefail` (or equivalent strict mode) active in scripts that perform privileged or remote actions, with targeted `set +e` only around known-fallible external commands + `|| true` guards.
  - [ ] No doc/code drift: if behavior, bypass semantics, or delivered scope changed, **both** the code *and* AGENTS.md / CONTRIBUTING.md / PHASE* docs were updated in the same change.
  - [ ] Handoff package completeness: `git diff --name-only` (plus untracked) matches exactly what will be declared in context.md / metadata. Incidental files (handoff records themselves, stray edits) are either reverted or explicitly included.

## 4. Mandatory Independent Agent-Review (the hard gate — non-negotiable)
**Only after** self-verification above passes:

1. Invoke the skill exactly as specified in AGENTS.md:
   - `agent-review` (preferred when available)
   - or `/agent-review --to-jules`
   - or `/agent-review --agent jules`
   - Equivalent: manual handoff packaging + `grok --agent jules -p "$(cat .../REVIEW_INSTRUCTIONS.md)" ...`
2. Confirm the portable package exists under `~/.grok/handoffs/<8-hex-id>/` containing:
   - `diff.patch`
   - `context.md` (task goal + instructions)
   - `metadata.json`
   - `REVIEW_INSTRUCTIONS.md`
3. Independent reviewer (Jules in separate context recommended) produces `jules-review-<id>.md` (or equivalent) with structured:
   - `## Summary`
   - `## Issues` (each with `[bug|suggestion|nit] File:line`, Description, Suggestion, `Status: open`)
4. Read the full review output.

## 5. Consume Findings & Produce Auditable Record
- [ ] **All bugs** (any severity) fixed or explicitly accepted only for non-blocking nits with written rationale
- [ ] High-severity or structural bugs trigger a follow-up focused review (parent handoff pattern used in wave)
- [ ] Create or append to a handoff record document modeled on existing examples:
  - `docs/P2_AGENT_REVIEW_HANDOFF_14c220fc.md`
  - `docs/CM_PHASE1_09_MIRROR_AGENT_REVIEW_HANDOFF.md`
  - Include: handoff ID + absolute `~/.grok/handoffs/...` path, reviewer identity, exact issue counts + key excerpts, remediation steps or "accepted" notes, final "safe to merge / ready for PR" statement
- [ ] Reference the handoff record + handoff dir + originating task/Jules ID in:
  - Final commit message(s)
  - PR title / body
  - Task queue update

## 6. Pre-PR / "Ready" Gate (final confirmation)
- [ ] Clean `git status` + final `bin/pre-commit` (or full manual gate run) passes with **zero** bypasses on the ready commit
- [ ] Traceability present in **all** commits on the branch
- [ ] All CI jobs green (fmt, clippy, tests, etc.)
- [ ] No open high-severity review findings
- [ ] PR template checklist items for pre-commit + agent-review + traceability are satisfied
- [ ] (When branch protection active) Status checks expected to pass
- [ ] If this change touches process / runners / docs: a P4 dogfood task was considered per REMAINING_CLOSURE_TASKS_2026-06 E1 pattern

## Last-Wave Recurring Defect Catalog (2026-05-31 wave)
Use as a **targeted diff grep / audit** before handoff. These were the actual bugs/suggestions that blocked or required polish commits in the wave:

1. **stdout pollution on capture paths** (multiple handoffs): diagnostic text mixed into JSON / command-substitution output → `>&2` + conditional banners.
2. **Sed fragility on structured data** (branch-protection script): `sed` replace on pretty-printed or whitespace-variant JSON → python json load/dump + override.
3. **Wrong commit message source in hard gate** (pre-commit): `git log -1` instead of the message being prepared → false positives/negatives once upgraded from soft reminder to `exit 1`.
4. **Non-portable xargs** (pre-commit STRICT): `-r` flag → breakage on macOS/BSD agents.
5. **Bypass policy / code mismatch**: docs claimed `PRECOMMIT_BYPASS=1` is master bypass; code only applied it to shellcheck block, not the new hard traceability gate.
6. **Incomplete handoff package declaration** vs actual touched files (including the handoff record itself).
7. **Pipeline subshell exit swallowing** (large-file check): `while ... exit 1 | ...` never aborts the script.
8. **Missing pre-mutation validation**: building ruleset payload then calling `gh api` without a json.load guard in between.
9. **Section numbering / doc drift** after edits: delivered scope didn't match claimed "shellcheck + markdown lint"; numbering broke when new block inserted.
10. **Redundant expensive calls** in hot path (multiple `git diff --cached` inside hook).

Any new diff that re-introduces one of these patterns fails self-verification.

## After This Checklist
**Still mandatory** (per AGENTS.md, never skipped):
- Perform the full `agent-review` / `/agent-review --to-jules` step.
- Package handoff + obtain + consume independent review.
- Record the result in a `*_AGENT_REVIEW_HANDOFF.md` file.
- **Only then** mark the task complete, commit the ready state, and open the PR.

This checklist + the agent-review handoff record together constitute the auditable evidence that the "judgment layer" (replacing traditional required approvals) was applied.

---

**Traceability note**: Created as the concrete deliverable for PHASE2 B5 ("Create lightweight 'review checklist'...") and REMAINING_CLOSURE_TASKS_2026-06 wave-2 items (handoff 82c8ff44 + this record). Future improvements to this checklist should themselves go through the full process (worktree + pre-commit + this checklist + agent-review) and reference a P4 dogfood task where possible.

**Measurement hook** (for E1 / continuous improvement): When using this checklist on a task, note in the handoff record or task result: "REVIEW_CHECKLIST v1.0 applied — caught X of the last-wave patterns (list)". This feeds the "measure effect on PR quality" loop.