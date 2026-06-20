#!/bin/bash
# audit-branch-protection.sh — Self-audit script for GitHub Branch Protection Rulesets
# This fulfills D3: A small script to self-audit branch protection config.

set -e

REPO="eveselove/AgentForge"

echo "🔍 Auditing branch protection rulesets for $REPO..."

if ! command -v gh >/dev/null 2>&1; then
    echo "❌ GitHub CLI (gh) is not installed. Cannot perform audit."
    exit 1
fi

if ! gh auth status >/dev/null 2>&1; then
    echo "❌ Not logged in to GitHub CLI. Cannot perform audit."
    exit 1
fi

echo "Fetching rulesets..."
# We query the rulesets API
RULESETS=$(gh api /repos/$REPO/rulesets 2>/dev/null)

if [ -z "$RULESETS" ] || [ "$RULESETS" == "[]" ]; then
    echo "⚠️  No repository rulesets found for $REPO."
    echo "   Ensure you have run bin/setup-branch-protection."
    exit 1
fi

# Check if our expected A2/A7 ruleset is active
EXPECTED_NAME="main-branch-protection (A2/A7 Level M2)"

if ! command -v jq >/dev/null 2>&1; then
    echo "⚠️  jq is required to parse rulesets. Please install jq."
    # Fallback to grep
    if echo "$RULESETS" | grep -q "$EXPECTED_NAME"; then
        echo "✅ Branch protection ruleset '$EXPECTED_NAME' found (parsed via grep)."
        exit 0
    else
        echo "⚠️  Could not find ruleset '$EXPECTED_NAME'."
        exit 1
    fi
fi

HAS_EXPECTED=$(echo "$RULESETS" | jq -r ".[] | select(.name == \"$EXPECTED_NAME\")")

if [ -n "$HAS_EXPECTED" ]; then
    ENFORCEMENT=$(echo "$HAS_EXPECTED" | jq -r '.enforcement')
    if [ "$ENFORCEMENT" == "active" ]; then
        echo "✅ Branch protection ruleset '$EXPECTED_NAME' is ACTIVE."
        exit 0
    else
        echo "⚠️  Branch protection ruleset '$EXPECTED_NAME' is present but enforcement is '$ENFORCEMENT' (expected 'active')."
        exit 1
    fi
else
    echo "⚠️  Could not find ruleset '$EXPECTED_NAME'."
    echo "   Existing rulesets:"
    echo "$RULESETS" | jq -r '.[].name'
    exit 1
fi
