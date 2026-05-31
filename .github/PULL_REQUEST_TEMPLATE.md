## Description
<!-- Describe what was done in this PR. Keep it concise but complete. -->

## Related (MANDATORY)
<!-- Link to the originating task in the internal queue and/or Jules session -->
- Task ID: 62a84821   <!-- e.g. 62a84821 [CM-03] -->
- Jules Session: 
- Branch: agent/cm-... (or task/... / jules/...)

## Branching & Process
- Followed [docs/BRANCHING_STRATEGY.md](docs/BRANCHING_STRATEGY.md) (v1.0)
- Short-lived branch from `main`, proper naming (`agent/cm-...` recommended)
- Pre-commit hook installed and passed (`./bin/install-pre-commit`)
- **Agent review performed** (agent-review skill / Jules / recorded Grok analysis) before requesting merge

## Type of change
- [ ] Bug fix
- [ ] New feature
- [ ] Refactoring / cleanup
- [ ] Documentation
- [ ] CI / Infrastructure
- [ ] Agent workflow / Code Management (CM)

## Checklist
- [ ] Self-review of the code
- [ ] Agent-review completed and referenced (for agent changes)
- [ ] Tests added or updated (if applicable)
- [ ] Documentation updated (if needed)
- [ ] `cargo fmt` + `cargo clippy -D warnings` passed (Rust)
- [ ] `ruff check` + `black --check` passed (Python)
- [ ] Linked to task / Jules session in commits + this PR
- [ ] Pre-commit hook active in the branch

## How to test
<!-- Describe how to verify the changes -->
