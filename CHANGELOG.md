# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.4.0] - 2026-10-20

### Added

- GitHub Action (`action.yml`, composite): replays a suite on the pull request and on its base commit, compares them, writes the job summary and outputs (`regressions`, `fixes`, `stale`, `report`), and creates or updates one comment per suite. Runs only on `pull_request` with `contents: read` and `pull-requests: write`; skips the comment on fork PRs; needs no API key ([ADR 0007](docs/adr/0007-pr-comment-action-regenerates-the-base.md)).
- CI runs the action on the example suites of every pull request.

- Stale recording detection ([ADR 0007](docs/adr/0007-pr-comment-action-regenerates-the-base.md)): `--record` writes recording format 2 with a fingerprint of each case's system prompt and input. A replayed case whose prompt or input changed fails as stale; `run` exits 2 after writing its reports, and the JSON report has `stale` per case and per run.
- `--record` together with `--replay` upgrades a recording to format 2 without calling any API, and refuses when a case is stale.
- `compare` lists stale head cases apart from regressions and fixes, and fails when there is any.
- Reports carry run warnings; recordings without fingerprints add one.

### Changed

- A run with a stale case is never `ok`, even if its pass rate meets the threshold.
- The example recordings use format 2.

### Deprecated

- Recording format 1 (a flat `case id: output` mapping) still replays, with a warning; upgrade it with `--replay OLD --record NEW`.

## [0.3.0] - 2026-10-20

### Added

- `agent-evals compare BASE HEAD`: compares two `run --json` reports case by case and lists regressions, fixes, added and removed cases with the change in pass rate, latency and cost. Exits 1 when any case that passed now fails ([ADR 0005](docs/adr/0005-compare-gates-on-case-regressions.md)).
- `compare --markdown` writes the comparison as a Markdown report.
- Example recording `recording-new-prompt.yaml` for ticket classification: same 9/10 pass rate, one regression.
- Multi-turn cases: `turns` (scripted `user` / `assistant` messages) instead of `input`. Only the answer to the last user turn is scored; recordings stay keyed by case id ([ADR 0006](docs/adr/0006-multi-turn-cases-with-scripted-history.md)).
- `Case.messages`: every case's input as a conversation; a single `input` is one user turn.
- Example suite `workshop-booking`: five conversations and one single message, run in CI.

### Changed

- Providers must read `case.messages` instead of `case.input`, which is `None` for multi-turn cases. Custom providers need the same change; the `Provider` signature is unchanged.
- The OpenAI provider sends `input` as a list of messages, also for single-message cases (equivalent request).

### Fixed

- `run` no longer crashes with `UnicodeEncodeError` on Windows when its output is redirected to a file or a pipe.

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
