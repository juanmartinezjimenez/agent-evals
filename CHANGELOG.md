# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.2.0] - 2026-10-19

### Added

- OpenAI provider (Responses API) and Anthropic provider (Messages API), as optional extras.
- `--provider`, `--model` and `--record`: run against a real model and save its outputs for replay.
- Token usage per case and per run; cost when `--price-input` and `--price-output` are given.
- p95 latency in every report.
- Provider errors: transient failures fail only their case; auth, permission and unknown-model errors abort with exit code 2.

### Changed

- `--replay` is no longer required; it selects the replay provider when `--provider` is omitted.
- Terminal summary shows `provider:model` and both mean and p95 latency.

## [0.1.0] - 2026-10-19

### Added

- YAML suites validated with Pydantic: system prompt, threshold, cases and tags.
- Replay provider that returns recorded outputs, for deterministic runs.
- Scorers: `exact`, `contains`, `regex` and `json_schema` (with expected field values).
- `agent-evals run` CLI with exit codes, terminal summary, Markdown and JSON reports.
- Per-tag pass rates.
- Two synthetic example suites: ticket classification and contact extraction.
- CI: lint, format, strict type checking, tests and the example evals.
