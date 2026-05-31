#!/usr/bin/env bash
# bin/check-agent-review-link.sh
# Lightweight warn-only agent-review linkage check (A4 / P2 final).
# Never fails the CI job (exit 0 always). Emits ::warning:: annotation only
# when an agent/ or jules/ PR lacks obvious handoff evidence.
# Complements the mandatory handoff package requirement in AGENTS.md.
set -euo pipefail

PR_BRANCH="${PR_BRANCH:-${GITHUB_HEAD_REF:-}}"
PR_TITLE="${PR_TITLE:-}"
PR_BODY="${PR_BODY:-}"
COMBINED="$PR_BRANCH $PR_TITLE $PR_BODY"

if [[ "$PR_BRANCH" =~ ^(agent|jules)/ ]]; then
  if echo "$COMBINED" | grep -qiE '(handoff|agent-review|jules-review|[0-9a-f]{7,}|02d2727d|6cbb2bb1)'; then
    echo "✅ Agent-review linkage evidence detected in PR metadata (warn-only job, non-blocking)."
  else
    echo "::warning title=Agent Review Linkage::Branch is agent/ or jules/ but no explicit handoff ID / agent-review reference found in title or body. Per AGENTS.md + FINAL_MERGE_CHECKLIST, ensure ~/.grok/handoffs/<id>/ exists and was produced before requesting merge."
  fi
else
  echo "Agent-review link check: not an agent/ or jules/ PR — skipped (OK)."
fi

exit 0
