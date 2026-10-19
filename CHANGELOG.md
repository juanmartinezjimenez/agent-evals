# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.0] - 2026-10-19

### Added

- YAML suites validated with Pydantic: system prompt, threshold, cases and tags.
- Replay provider that returns recorded outputs, for deterministic runs.
- Scorers: `exact`, `contains`, `regex` and `json_schema` (with expected field values).
- `agent-evals run` CLI with exit codes, terminal summary, Markdown and JSON reports.
- Per-tag pass rates.
- Two synthetic example suites: ticket classification and contact extraction.
- CI: lint, format, strict type checking, tests and the example evals.
