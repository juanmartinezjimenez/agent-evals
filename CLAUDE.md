# Working conventions for AI coding agents

These rules apply to Claude Code and any other agent working in this repo.

- Code, identifiers, commits, issues and PRs in English.
- Commits follow Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:`, `test:`, `refactor:`).
- Small commits, one logical change each. Never commit directly to `main`: branch and open a PR.
- Never commit secrets, `.env` files or real personal data. Test data is always synthetic.
- Every behaviour change ships with a test. CI must be green before merging.
- Decisions that are expensive to reverse get an ADR in `docs/adr/`.
- Update `CHANGELOG.md` under `[Unreleased]` for user-visible changes.
