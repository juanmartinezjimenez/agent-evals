# 0007. A composite action that regenerates the base run and keeps one PR comment

- Status: accepted
- Date: 2026-10-20

## Context

v0.4.0 ships a reusable GitHub Action. On every pull request it runs a suite on
the PR, compares it with the same suite on the base branch and posts the result
of `compare --markdown` (ADR 0005) on the pull request, so a reviewer sees which
cases regressed without opening the CI logs.

Four questions decide the design and are expensive to change once other
repositories depend on the action: where the base report comes from, what kind
of action it is, how the comment is published, and what the action is allowed
to do with tokens and secrets.

## Decision

`agent-evals` ships a **composite action** in `action.yml` at the root of this
repository. In the PR job it **regenerates the base report** by checking out the
base commit of the pull request and running the suite with **replay**. It then
runs the same suite on the PR, compares both reports, publishes **one comment
per suite that is updated on every push**, writes the report to the job
summary and fails the step when there is a regression. It runs only on the
`pull_request` event with a read-only token plus `pull-requests: write`, and it
never needs an API key.

Because replay compares recordings and not the model, recordings carry a
**fingerprint of what was sent to the model** for each case, and a replayed case
whose prompt or input changed after it was recorded **fails as stale** instead
of returning an old answer. Without this, the action would be unsafe to rely on.

### Where the base report comes from

The action checks out `github.event.pull_request.base.sha` into a separate
directory and runs `agent-evals run SUITE --replay RECORDING --json base.json`
there; then it runs the same command on the PR checkout to produce `head.json`.
Both runs use the agent-evals version pinned by the action reference, so
differences come only from the suites and recordings, never from the tool.

| | Regenerate in the same job (chosen) | Download an artifact from the CI of `main` |
| --- | --- | --- |
| Cost | One extra checkout and a replay run: seconds, no API calls | One API lookup and a download: also seconds; no real saving |
| Determinism | Exact: the base is the PR's base commit, replayed from its own recording | The latest run of `main` may be for a different commit than the PR's base (PR opened earlier, `main` moved, run still in progress), so the baseline can be wrong without any error |
| Expiry | None: the base commit is always in the repository | Artifacts expire (90 days by default, less if the repository lowers it) and a PR against an old base has nothing to compare with |
| Permissions | `contents: read`, already needed for the checkout | Also `actions: read` and cross-workflow lookup logic; the artifact is produced by a workflow the PR job does not control |
| Moving parts | One job | Two workflows that must agree on artifact names, paths and retention |

If the suite file does not exist at the base commit (a new suite), the action
skips `compare`, posts the `run` report and says the suite is new. If the suite
exists in both but `compare` cannot read the reports (exit `2`, e.g. the suite
was renamed), the action fails with the error instead of guessing.

### Stale recordings

**Why it is necessary.** Replay returns whatever was recorded for a case id. If
a PR changes the system prompt or the input of a case (`input` or `turns`) and
does not re-record, the head run replays answers the model gave to the *old*
prompt, scores them against the new suite and usually passes. `compare` then
reports "0 regressions" for a change nobody evaluated: a false green on exactly
the kind of PR the action exists to check. A regression gate that can be passed
by forgetting a step is worse than no gate, because it looks authoritative. So
replay must refuse answers that were recorded for something else.

**What is recorded.** `--record` writes format version 2. Next to each output it
stores a fingerprint of what the model received for that case:

```yaml
# Recorded by agent-evals. Replay with: agent-evals run SUITE --replay THIS_FILE
version: 2
provider: anthropic
model: claude-haiku-5-5
cases:
  double-charge:
    fingerprint: sha256:3f9a1c0b7d2e4a65
    output: billing
  confirm-chosen-slot:
    fingerprint: sha256:9b04e7d15a2c8f31
    output: You're booked for Thursday at 17:30, Laura Pérez.
```

The fingerprint is the first 16 hex characters of the SHA-256 of the canonical
JSON (sorted keys, no extra whitespace, UTF-8) of
`{"system": <suite system prompt>, "messages": <case.messages>}`. It covers
exactly what the provider sends (ADR 0006): a case written as `input: "x"` and
the same case written as one user turn have the same fingerprint. It does
**not** cover `expect` or `tags`, because changing what counts as correct must
re-score the same answer, not force a new live run. `provider` and `model` are
stored for traceability and are not checked.

**What replay does.** For every case it recomputes the fingerprint from the
current suite and compares it with the recorded one:

| Situation | Result |
| --- | --- |
| Fingerprints match | Normal replay |
| Fingerprints differ | The case fails with `stale recording: the system prompt or input changed since this case was recorded; re-record with --record`. It is marked `stale` in the JSON report, and `run` exits `2` (the recording does not match the suite) after writing its reports |
| Recording in the old format (version 1, a flat `case id: output` mapping, as written by v0.1–v0.3) | Replays as before, with one warning per run on stderr and in the reports: `recording has no fingerprints; changes to prompts or inputs cannot be detected; re-record with --record` |

`compare` lists stale cases of the head run in their own section and fails
(exit `1`) when there is any, even if no case regressed, because a stale case
says nothing about the model.

**Upgrading old recordings without an API call.** `--record` is also accepted
with `--replay`: it rewrites the outputs that were replayed in format version 2,
fingerprinted against the current suite and keeping the original `provider` and
`model` when the source has them. It refuses to write anything if any case is
stale, so it can never stamp a new fingerprint on an old answer. For a version 1
recording there is nothing to check against: upgrading it asserts that the
outputs belong to the current suite, which is the author's responsibility. The
example recordings of this repository are upgraded this way, with no API calls.

**In the PR comment.** Stale cases go first, above the metrics, because the rest
of the comment cannot be trusted until they are fixed. Notices use GitHub's
alert syntax (`> [!WARNING]`, `> [!NOTE]`), which GitHub renders as coloured
callouts and other Markdown viewers show as plain blockquotes:

```markdown
## workshop-booking: base vs head

**❌ FAIL** · 0 regressions, 0 fixes · ⚠️ 2 stale recordings · `replay` → `replay`

> [!WARNING]
> **2 cases replayed answers recorded for a different prompt or input.**
> Their results say nothing about the current suite. Re-record them with a live run
> (`agent-evals run SUITE --provider ... --model ... --record RECORDING`) and push the recording.
>
> - `confirm-chosen-slot`
> - `correction-wins`
```

A version 1 recording adds a NOTE alert under the header, one per run warning:

```markdown
> [!NOTE]
> recording has no fingerprints; changes to prompts or inputs cannot be detected; re-record with --record
```

The action step fails when the head run has stale cases.

### Composite, not JavaScript

A composite action is a list of shell steps. The tool is a Python CLI installed
with uv, so every step is a command the user could run locally: install uv,
`uv tool install` agent-evals from `${{ github.action_path }}`, check out the
base, run, compare, comment. A JavaScript action would need Node, a bundled
`dist/` committed to the repository and kept in sync, and it would still have to
call the Python CLI. Composite keeps one language and nothing to bundle.

The third-party action it uses (`astral-sh/setup-uv`) is pinned to a full commit
SHA inside `action.yml`, as GitHub recommends for actions that run with a token
of the caller. `actions/checkout` is pinned the same way.

### One comment that is updated

Each comment starts with a hidden marker, `<!-- agent-evals:SUITE_NAME -->`. The
action lists the PR's comments, and if one from `github-actions[bot]` carries
the marker it updates it (`PATCH /repos/{owner}/{repo}/issues/comments/{id}`);
otherwise it creates it (`POST /repos/{owner}/{repo}/issues/{number}/comments`).
It uses the GitHub CLI that is preinstalled on GitHub-hosted runners, so no
third-party commenting action receives the write token. A PR with three suites
has three comments, each always showing the latest push. The body includes the
commit it was computed for and a link to the run, and is cut before GitHub's
65,536-character limit with a pointer to the full report in the job summary.

### Security

- **Event:** `pull_request` only. The workflow runs the PR's code (its suites,
  its `pyproject.toml`, anything uv installs from it) with the PR's own
  privileges, which is the safe default.
- **`pull_request_target` is not supported.** It runs in the context of the
  base branch with a write token and access to secrets. Checking out and running
  the PR's code under it lets anyone who opens a PR run code with those
  privileges. GitHub's documentation says to avoid it when the workflow needs
  to build or run code from the pull request, which is exactly what an eval run
  does. The action refuses to run under that event.
- **Minimum token permissions:** `contents: read` for the checkouts and
  `pull-requests: write` for the comment. The comment endpoints accept either
  Issues or Pull requests write; the implementation will confirm the accepted
  permission with the `X-Accepted-GitHub-Permissions` response header in its
  first test run. No other scope is needed.
- **PRs from forks:** GitHub gives them a read-only token and no secrets. The
  action still runs both suites, writes the comparison to the job summary and
  sets the exit code; it detects the fork and skips the comment with a notice
  instead of failing on a 403. Commenting on fork PRs would need a second,
  privileged `workflow_run` workflow that never checks out PR code; that is left
  for later.
- **API keys:** the action only replays recordings, so it needs no key and costs
  nothing. Live runs stay where they are today: a developer runs them locally
  with `--record` and commits the recording, and the PR shows the effect through
  replay. An action input for live runs is out of scope; if it is added later,
  the key comes from a repository secret passed as an environment variable,
  never as an input, so it does not appear in logs, and it is unavailable on
  fork PRs by design.

### Using it from another repository

```yaml
# .github/workflows/evals.yml in any repository with agent-evals suites
name: Evals

on:
  pull_request:
    paths: ["evals/**", "prompts/**"]

permissions:
  contents: read
  pull-requests: write

concurrency:
  group: evals-${{ github.event.pull_request.number }}
  cancel-in-progress: true # only the latest push updates the comment

jobs:
  evals:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        suite: [support-triage, booking-assistant]
    steps:
      - uses: actions/checkout@v7

      - uses: juanmartinezjimenez/agent-evals@v0.4.0
        with:
          suite: evals/${{ matrix.suite }}/suite.yaml
          replay: evals/${{ matrix.suite }}/recording.yaml
          fail-on-regression: true # default
```

Inputs: `suite` and `replay` (paths, the same in the base and the PR),
`fail-on-regression` (default `true`) and `comment` (default `true`). Outputs:
`regressions`, `fixes` and `report` (path to the Markdown file).

## Alternatives considered

| Option | Why not |
| --- | --- |
| Base report from an artifact of the CI of `main` | Can silently compare against the wrong commit, expires, and needs an extra permission and a second workflow (see the table above) |
| A baseline report committed to the repository | Goes stale, conflicts on every PR that touches the suite, and someone has to remember to refresh it |
| JavaScript action | Adds Node, a bundled `dist/` and its upkeep, and still has to call the Python CLI |
| Docker action | Slower start on every run, Linux only, and one more image to publish and patch |
| A new comment on every push | Floods the PR and buries the current result under old ones |
| A third-party "sticky comment" action | Hands the write token to another project for something the preinstalled GitHub CLI does in a few lines |
| `pull_request_target` to comment on fork PRs | Runs untrusted PR code with a write token and secrets |
| Live model runs on every PR | Costs money on each push, needs secrets, is not deterministic, and does not work on fork PRs |
| A separate `agent-evals-action` repository | The action and the CLI would be versioned apart and could drift; one tag (`v0.4.0`) now pins both |
| Replay without stale detection | Prompt or input changes without a new recording pass silently: a false green |
| One hash of the whole suite file | Any edit, even to an expectation or a tag, would mark every case stale and force a full live run |
| Store a full copy of each prompt and input in the recording | Duplicates the suite, bloats recordings with long conversations, and a hash detects the same changes |
| Only warn on a stale case | The run would still pass, which is the false green this exists to prevent |
| Fail old recordings without fingerprints | Breaks every v0.1–v0.3 user at once; a warning plus a no-API upgrade path is enough |

## Consequences

Any repository with suites and recordings gets a regression report on each PR
with two permissions and no secrets. The baseline is always the PR's real base
commit. Fork PRs get the report in the job summary but no comment until a
`workflow_run` follow-up exists. A suite without a recording cannot use the
action; that is consistent with the record → replay loop (ADR 0002). Because
the action lives in this repository, each release tag must keep `action.yml`
working, and the CI of this repository will run the action against its own
example suites.

With fingerprints, a green comment means the replayed answers belong to the
prompts and inputs in the PR. Any change to a system prompt or a case input now
requires a live run with `--record` before the PR can pass, which is a real cost
per prompt change but the only honest one. Edits that do not change what the
model receives (expectations, tags, thresholds) never require it. Whitespace
inside prompts counts as a change. The recording format moves to version 2;
version 1 keeps working with a warning until a future major version.
