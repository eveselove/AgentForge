# Branch Protection

We want to protect the `main` branch.

## Current Status

As of 2026-05-31, full branch protection / rulesets via API are having validation issues.

## Recommended Manual Setup (in GitHub UI)

Go to:
Settings → Branches → Branch protection rules → Add rule for `main`

Recommended settings:
- Require a pull request before merging
- Require at least 1 approving review
- Dismiss stale pull request approvals when new commits are pushed
- Require status checks to pass before merging (Rust (stable), Python)
- Require branches to be up to date before merging
- Include administrators

Once the CI is more mature, we can enforce more checks.
