# repo-template

Base template for every new project: CI from the first commit, secret scanning,
decision records and shared conventions.

[![CI](https://github.com/juanmartinezjimenez/repo-template/actions/workflows/ci.yml/badge.svg)](https://github.com/juanmartinezjimenez/repo-template/actions/workflows/ci.yml)

## What's included

| File | Purpose |
| --- | --- |
| `.github/workflows/ci.yml` | Lint and secret scan on every push and PR; projects add their own test job |
| `.pre-commit-config.yaml` | Formatting checks, private-key detection and [gitleaks](https://github.com/gitleaks/gitleaks) over the full history |
| `.github/dependabot.yml` | Monthly updates for GitHub Actions |
| `docs/adr/` | Architecture Decision Records, with a template |
| `docs/README_SKELETON.md` | README structure for new projects: problem, architecture, quickstart, results, decisions |
| `CLAUDE.md` | Conventions for AI coding agents working in the repo |
| `CHANGELOG.md` | [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format, semver |
| `.editorconfig`, `.gitignore`, `LICENSE` | Editor settings, ignored files (secrets first), MIT license |

## Using it

1. **Use this template → Create a new repository.**
2. Replace this `README.md` with `docs/README_SKELETON.md` and fill it in.
3. Install the hooks locally:

   ```bash
   pip install pre-commit
   pre-commit install
   ```

4. Add the project's test job to `.github/workflows/ci.yml` and its ecosystem to `dependabot.yml`.

## Conventions

- Conventional Commits, small commits, PRs into `main`.
- Synthetic data only; no secrets or real personal data, ever.
- Every decision that is expensive to reverse gets an ADR.

## License

[MIT](LICENSE)
