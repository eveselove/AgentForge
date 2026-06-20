#!/usr/bin/env bash
# bin/check-agent-review-link.sh
# Lightweight warn-only agent-review linkage check (A4 / P2 final).
# Never fails the CI job (exit 0 always). Emits ::warning:: annotation only
# when an agent/ or jules/ PR lacks obvious handoff evidence.
# Complements the mandatory handoff package requirement in AGENTS.md.
# Pure-bash fast path; supports branch prefixes + metadata keywords/IDs.
#
# AUDIT (bottlenecks / logic / races):
# - No data races: stateless, no files/locks/shared mutable state, pure env+print.
# - No real bottlenecks: zero external procs/pipes/subshells/forks (original strength preserved). Avoids COMBINED string alloc for large PR bodies.
# - Logical fixes: (1) branch prefix ^(agent|jules)/ now also case-insensitive (consistent with content check + robust to Agent/JULES/ casing); (2) shopt calls protected by ||true so set -e never causes non-zero exit on shopt fail (old bash/no nocasematch etc) -- stronger guarantee of "exit 0 always"; (3) temp vars always unset -- truly zero state pollution on sourced runs.
set -euo pipefail

PR_BRANCH="${PR_BRANCH:-${GITHUB_HEAD_REF:-${GITHUB_REF_NAME:-}}}"
PR_TITLE="${PR_TITLE:-}"
PR_BODY="${PR_BODY:-}"

# Save/restore shopt (via -q) so safe even if script is sourced (no state pollution / side effects). No subshell.
# nocasematch now covers the branch prefix check too (was case-sens only before -- logical gap).
__carl_old_nocase=u
if shopt -q nocasematch 2>/dev/null; then __carl_old_nocase=s; fi
shopt -s nocasematch 2>/dev/null || true

if [[ "$PR_BRANCH" =~ ^(agent|jules)/ ]]; then
  # Pure-bash case-insensitive match via nocasematch + [[ =~ ]] (no echo|grep subshell/pipe/fork).
  # Eliminates the process-spawn bottleneck for speed ("lightning fast").
  # Also covers jules/ (matches job if: in ci.yml + AGENTS.md + FINAL_MERGE_CHECKLIST).
  # Pattern aligned with inline CI logic + legacy handoff IDs. (branch prefix checked separately; branch hex e.g. task IDs do not count as handoff evidence)
  HANDOFF_PATTERN='(handoff|agent-review|AGENT_REVIEW_HANDOFF|handoff[[:space:]]*[0-9a-fA-F]{7,}|[0-9a-fA-F]{7,}|02d2727d|6cbb2bb1)'
  if [[ "$PR_TITLE" =~ $HANDOFF_PATTERN ]] || [[ "$PR_BODY" =~ $HANDOFF_PATTERN ]]; then
    echo "✅ Agent-review linkage evidence detected in PR metadata (warn-only job, non-blocking)."
  else
    echo "::warning title=Agent Review Linkage::Branch is agent/ or jules/ but no explicit handoff ID / agent-review reference found in title or body. Per AGENTS.md + FINAL_MERGE_CHECKLIST, ensure ~/.grok/handoffs/<id>/ exists and was produced before requesting merge."
  fi
  unset HANDOFF_PATTERN 2>/dev/null || true
else
  echo "Agent-review link check: not an agent/ or jules/ PR — skipped (OK)."
fi

shopt -"$__carl_old_nocase" nocasematch 2>/dev/null || true
unset __carl_old_nocase 2>/dev/null || true

(return 0 2>/dev/null) || exit 0
