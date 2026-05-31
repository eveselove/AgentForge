# Branch Protection (main branch)

**Task**: D1 + D2 (task 3cdd6813) — Write exact UI steps + apply the A2/A7 0-approval ruleset.  
**Status**: ✅ **APPLIED on 2026-05-31** via `bin/setup-branch-protection` (Ruleset API) + documented UI steps below. Ruleset ID: 17085567, enforcement=active, bypass_actors=[] (no bypass even for owner).  
**Reference**: `docs/REMAINING_CLOSURE_TASKS_2026-06.md` (Cluster D), `docs/BRANCH_PROTECTION_A2_PROPOSAL.md` (bc6fa462), `docs/BRANCH_PROTECTION_A7_DECISION.md` (Level M2 architectural decision).

**See also**:
- Authoritative machine-readable config: `.github/rulesets/main-protection.json` (committed, used by the setup script)
- Full rationale + why 0 approvals: the A7 + A2 docs above
- AGENTS.md (mandatory agent-review + pre-commit + traceability before any merge to this protected main)
- Branching strategy: `docs/BRANCHING_STRATEGY.md`

---

## Current Status

- **Ruleset active** on `main` (and default branch via `~DEFAULT_BRANCH`): "main-branch-protection (A2/A7 Level M2)"
- 0 required GitHub approvals (judgment via mandatory `agent-review` skill + CI + process)
- Strict required status checks: exactly `Rust` + `Python` (with "require branches up to date")
- Conversation resolution required
- Force pushes blocked, deletions blocked
- No actors in bypass list (enforced on admins/owner too; emergency bypass requires high-priority post-mortem task per A7)
- Classic branch protection rule: none (ruleset is the enforcement mechanism)

All changes to `main` now require a PR that passes the mechanical gates. The real design/security/correctness review for agent-authored work happens via the `agent-review` skill (separate context, handoff artifact, recorded in `~/.grok/handoffs/`).

---

## D1: Exact Step-by-Step Instructions for GitHub UI (Ruleset)

**Use this when re-applying, editing, or for audit.** Prefer Ruleset over classic (supports the exact A2 parameters + future evolution like commit-message rules).

**Repo**: https://github.com/eveselove/AgentForge (public, Free tier — all needed features available)

### Ruleset Creation (Primary Path)

1. Navigate to the repository → click the **Settings** tab (top navigation bar).
   - [Screenshot placeholder 1: Top nav with "Settings" tab highlighted]

2. In the left sidebar, scroll to **"Code and automation"** section → click **Rules** → **Rulesets**.
   - [Screenshot placeholder 2: Sidebar → Rules → Rulesets]

3. Click the prominent **"New ruleset"** button (green).
   - [Screenshot placeholder 3: Rulesets list page with "New ruleset" button]

4. Configure the ruleset header:
   - **Ruleset name**: `main-branch-protection (A2/A7 Level M2)`
   - **Enforcement status**: `Active` (on Free personal accounts, "Evaluate" mode is Enterprise-only; see A1 research. The ruleset is safe/minimal so Active is appropriate on first apply.)
   - **Target**: select **Branch**
   - [Screenshot placeholder 4: Ruleset creation form header]

5. **Target branches**:
   - Select "Include default branch (`~DEFAULT_BRANCH`)" (or manually add `~DEFAULT_BRANCH` and `refs/heads/main`).
   - Leave Exclude empty.
   - [Screenshot placeholder 5: Target branches section with ~DEFAULT_BRANCH selected]

6. **Bypass list** (critical for A7 "no admin bypass"):
   - **Leave the entire bypass list EMPTY**.
   - Do **not** add "Repository admins", "Organization admins", your own user, or any apps/teams.
   - This ensures the owner cannot accidentally bypass the Rust/Python gates or force-push to main.
   - (Any future ruleset edit outside documented emergency process must create a high-priority task + post-mortem.)
   - [Screenshot placeholder 6: Bypass list section — completely blank]

7. Enable the following **Rules** (use the "Add rule" button or direct toggles/checkboxes depending on the exact GitHub UI version at the time; configure exactly as below):

   **a. Require a pull request before merging**
   - Required approving reviews: `0`
   - Dismiss stale pull request approvals when new commits are pushed: ✅ (checked)
   - Require review from Code Owners: ⬜ (unchecked)
   - Require approval of the most recent push: ⬜ (unchecked)
   - Require conversation resolution before merging: ✅ (checked)
   - [Screenshot placeholder 7: Pull request rule configured with 0 approvals + conversation resolution]

   **b. Require status checks to pass before merging**
   - Require branches to be up to date before merging: ✅ (checked — strict)
   - Required status checks — add exactly these two (by exact job name from `.github/workflows/ci.yml`):
     - `Rust`
     - `Python`
   - (Do **not** add "Shell & Scripts", "Docs", or the advisory parity harness.)
   - [Screenshot placeholder 8: Status checks section with Rust + Python + strict up-to-date]

   **c. Block force pushes**
   - Add / enable the "Block force pushes" rule (API type: non_fast_forward).
   - Leave any sub-options at defaults (the rule is a simple on/off).
   - [Screenshot placeholder 9: "Block force pushes" rule added/selected]

   **d. Block deletions**
   - Add / enable the "Block deletions" rule.
   - Leave any sub-options at defaults.
   - [Screenshot placeholder 10: "Block deletions" rule added/selected]

   (No other rules needed for the initial A2/A7 minimal set.)

8. Review the summary on the right (should show 0 approvals, 2 status checks, etc.).
9. Click **Create** at the bottom.
   - [Screenshot placeholder 11: Completed form + Create button]

10. **Verification after creation**:
    - The new ruleset appears in the list with "Active" badge.
    - Click it → you can see the full JSON-like view and "Insights" (dry-run effects even on Active for visibility).
    - Confirm via API or Settings that direct pushes to main are rejected and PRs without green Rust+Python cannot merge.
    - Test: open a draft PR that touches Rust/Python and verify the required checks + "0 approvals needed" behavior.

### Editing / Promoting / Auditing an Existing Ruleset

- Go to Settings → Rules → Rulesets → click the ruleset name.
- Edit any field (e.g. to add a future commit-message pattern rule for Phase 2 traceability).
- To temporarily relax (emergency only): add yourself to Bypass list with mode "always" (then immediately create post-mortem task and remove after).

### Classic Branch Protection (Legacy / Fallback Only)

If Rulesets UI is unavailable:
1. Settings → Branches → "Add branch protection rule" for `main`.
2. Check "Require a pull request before merging".
3. Set "Required approving reviews" to 0.
4. Check the other boxes matching the rules above (status checks `Rust` + `Python`, strict, conversation resolution, "Do not allow bypassing...", block force/deletes).
5. Save.
**Note**: Rulesets are strongly preferred (see A2/A7). The setup script and committed JSON target the Ruleset form.

---

## How This Was Applied (D2)

- Ran `./bin/setup-branch-protection` inside an isolated agent worktree (`agent/d1-d2-branch-protection-3cdd6813`) after `./bin/install-pre-commit`.
- Script read `.github/rulesets/main-protection.json`, POSTed it via `gh api /repos/.../rulesets` → live Ruleset ID 17085567 (active, matches JSON).
- Script output + this file + checklist updated with full traceability to task 3cdd6813.
- **Mandatory agent-review gate** (per AGENTS.md + explicit user instruction): Full handoff package created (`~/.grok/handoffs/b50d6187/`), independent Jules review launched in separate context, verdict **PASS WITH NOTES** (0 bugs). 4/6 minor findings addressed in follow-up edits on the same branch (see `docs/AGENT_REVIEW_HANDOFF_3cdd6813_b50d6187.md` for details + full review file). Pre-commit + task ID reference will be enforced on the actual commit.
- All per AGENTS.md (worktree, pre-commit, traceability, agent-review before PR).

**Next (future D3 or A5)**: Add a CI self-audit job that calls the rulesets API and fails if the expected rules drift.

---

*Dogfooding note (per AGENTS.md): All work performed on proper short-lived agent/ branch in worktree, pre-commit active, task ID referenced, mandatory agent-review step to be executed before PR/merge (see handoff record).*

**Traceability**: This document + the ruleset application fulfill D1+D2 of Cluster D (task 3cdd6813) in REMAINING_CLOSURE_TASKS_2026-06.md.
