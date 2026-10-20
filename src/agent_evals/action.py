"""Logic behind the GitHub Action in `action.yml` (ADR 0007). Not a public API.

On a pull request it replays a suite on the PR and on the PR's base commit,
compares both runs, writes the job summary and step outputs, and creates or
updates one comment per suite. Inputs come from environment variables set by
`action.yml`, never interpolated into shell code.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from agent_evals.compare import RunReport, compare
from agent_evals.models import Suite
from agent_evals.providers import ReplayProvider
from agent_evals.report import comparison_to_markdown, to_json, to_markdown
from agent_evals.runner import RunResult, run_suite

COMMENT_LIMIT = 65_536  # GitHub's maximum comment length, in characters
BOT_LOGIN = "github-actions[bot]"
TRUNCATED_NOTE = "\n\n> [!NOTE]\n> Report truncated to fit in a comment; see the job summary.\n"

# Runs `gh` with arguments and optional stdin, returns stdout; raises on failure.
Gh = Callable[[list[str], str | None], str]


@dataclass(frozen=True, slots=True)
class Inputs:
    suite: Path
    replay: Path
    base_dir: Path
    fail_on_regression: bool = True
    comment: bool = True


@dataclass(frozen=True, slots=True)
class Outcome:
    suite: str
    markdown: str
    regressions: int
    fixes: int
    stale: int
    failed: bool
    new_suite: bool


def _replay(suite_path: Path, recording: Path) -> tuple[Suite, RunResult]:
    suite = Suite.from_yaml(suite_path)
    return suite, run_suite(suite, ReplayProvider.from_yaml(recording))


def _report(run: RunResult) -> RunReport:
    return RunReport.model_validate_json(to_json(run))


def evaluate(inputs: Inputs) -> Outcome:
    """Replay the suite on the PR and on its base commit and compare them.

    Stale cases always fail; regressions fail unless `fail_on_regression` is off.
    A suite or recording missing on the base commit is a new suite: its own run
    report is posted and it fails like `run` would (below threshold or stale).
    """
    suite, head = _replay(inputs.suite, inputs.replay)
    base_suite, base_recording = inputs.base_dir / inputs.suite, inputs.base_dir / inputs.replay
    if not (base_suite.is_file() and base_recording.is_file()):
        note = "> [!NOTE]\n> New suite: there is no run on the base commit to compare with.\n\n"
        return Outcome(
            suite=suite.name,
            markdown=note + to_markdown(head),
            regressions=0,
            fixes=0,
            stale=head.stale,
            failed=not head.ok,
            new_suite=True,
        )

    _, base = _replay(base_suite, base_recording)
    result = compare(_report(base), _report(head))  # ValueError if the suite was renamed
    return Outcome(
        suite=suite.name,
        markdown=comparison_to_markdown(result),
        regressions=len(result.regressions),
        fixes=len(result.fixes),
        stale=len(result.stale),
        failed=bool(result.stale) or (inputs.fail_on_regression and bool(result.regressions)),
        new_suite=False,
    )


def marker(suite: str) -> str:
    return f"<!-- agent-evals:{suite} -->"


def comment_body(outcome: Outcome, head_sha: str, run_url: str) -> str:
    """Marker first (to find the comment again), report, then where it came from."""
    head = marker(outcome.suite) + "\n"
    footer = (
        f"\n---\n<sub>agent-evals · computed for {head_sha[:7]} · [workflow run]({run_url})</sub>\n"
    )
    report = outcome.markdown
    if len(head) + len(report) + len(footer) > COMMENT_LIMIT:
        room = COMMENT_LIMIT - len(head) - len(footer) - len(TRUNCATED_NOTE)
        report = report[:room].rstrip() + TRUNCATED_NOTE
    return head + report + footer


def find_comment(gh: Gh, repo: str, number: int, suite: str) -> int | None:
    """Id of this action's comment for `suite`, ignoring comments by people or other suites."""
    lines = gh(
        [
            "api",
            f"repos/{repo}/issues/{number}/comments",
            "--paginate",
            "--jq",
            ".[] | {id, login: .user.login, body}",
        ],
        None,
    )
    for line in lines.splitlines():
        if not line.strip():
            continue
        comment = json.loads(line)
        if comment["login"] == BOT_LOGIN and comment["body"].startswith(marker(suite)):
            return int(comment["id"])
    return None


def accepted_permissions(response: str) -> str | None:
    """Value of the X-Accepted-GitHub-Permissions header in `gh api -i` output."""
    for line in response.splitlines():
        if not line.strip():
            break  # end of headers
        name, _, value = line.partition(":")
        if name.strip().lower() == "x-accepted-github-permissions":
            return value.strip()
    return None


def upsert_comment(gh: Gh, repo: str, number: int, suite: str, body: str) -> str:
    """Update this suite's comment if it exists, otherwise create it. Returns what was done."""
    existing = find_comment(gh, repo, number, suite)
    if existing is None:
        method, path, done = "POST", f"repos/{repo}/issues/{number}/comments", "created"
    else:
        method, path, done = "PATCH", f"repos/{repo}/issues/comments/{existing}", "updated"
    response = gh(
        ["api", "-i", "--method", method, path, "--input", "-"], json.dumps({"body": body})
    )
    # ADR 0007: confirm which permission GitHub accepted for the comment endpoint.
    print(
        f"comment {done}; accepted permissions: {accepted_permissions(response) or 'not reported'}"
    )
    return done


def _gh(args: list[str], stdin: str | None) -> str:
    done = subprocess.run(
        ["gh", *args], input=stdin, capture_output=True, text=True, encoding="utf-8", check=True
    )
    return done.stdout


def _flag(value: str) -> bool:
    return value.strip().lower() in {"true", "1", "yes"}


def _append(path: str | None, text: str) -> None:
    if path:
        with open(path, "a", encoding="utf-8") as stream:
            stream.write(text)


def main(env: Mapping[str, str] | None = None, gh: Gh = _gh) -> int:
    env = os.environ if env is None else env
    event_name = env.get("GITHUB_EVENT_NAME", "")
    if event_name != "pull_request":
        print(
            f"::error::agent-evals runs only on pull_request, not {event_name or 'unknown'}. "
            "pull_request_target is refused: it would run the PR's code with a write token "
            "and secrets (ADR 0007)."
        )
        return 2

    inputs = Inputs(
        suite=Path(env["INPUT_SUITE"]),
        replay=Path(env["INPUT_REPLAY"]),
        base_dir=Path(env["AGENT_EVALS_BASE_DIR"]),
        fail_on_regression=_flag(env.get("INPUT_FAIL_ON_REGRESSION", "true")),
        comment=_flag(env.get("INPUT_COMMENT", "true")),
    )
    if inputs.suite.is_absolute() or inputs.replay.is_absolute():
        print("::error::suite and replay must be paths relative to the repository root")
        return 2

    try:
        outcome = evaluate(inputs)
    except (OSError, ValueError) as exc:  # ValueError covers invalid YAML, reports, renames
        print(f"::error::{exc}")
        return 2

    report = Path(env.get("RUNNER_TEMP", ".")) / f"agent-evals-{outcome.suite}.md"
    report.write_text(outcome.markdown, encoding="utf-8")
    _append(env.get("GITHUB_STEP_SUMMARY"), outcome.markdown + "\n")
    _append(
        env.get("GITHUB_OUTPUT"),
        f"regressions={outcome.regressions}\nfixes={outcome.fixes}\n"
        f"stale={outcome.stale}\nreport={report}\n",
    )
    print(
        f"{outcome.suite}: {outcome.regressions} regressions, {outcome.fixes} fixes, "
        f"{outcome.stale} stale{' (new suite)' if outcome.new_suite else ''}"
    )

    if inputs.comment:
        event = json.loads(Path(env["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
        pull = event["pull_request"]
        repo = env["GITHUB_REPOSITORY"]
        if pull["head"]["repo"]["full_name"] != repo:
            print(
                "::notice::Pull request from a fork: GitHub gives it a read-only token, "
                "so the report is in the job summary only."
            )
        else:
            run_url = f"{env['GITHUB_SERVER_URL']}/{repo}/actions/runs/{env['GITHUB_RUN_ID']}"
            body = comment_body(outcome, pull["head"]["sha"], run_url)
            try:
                upsert_comment(gh, repo, int(pull["number"]), outcome.suite, body)
            except subprocess.CalledProcessError as exc:
                print(
                    f"::error::could not comment on the pull request ({exc.stderr.strip()}); "
                    "the job needs `pull-requests: write`"
                )
                return 2

    return 1 if outcome.failed else 0


if __name__ == "__main__":
    sys.exit(main())
