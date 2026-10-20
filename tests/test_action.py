"""The GitHub Action logic (ADR 0007), with a fake `gh` and a temporary repository."""

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from agent_evals.action import (
    BOT_LOGIN,
    COMMENT_LIMIT,
    Inputs,
    Outcome,
    accepted_permissions,
    comment_body,
    evaluate,
    find_comment,
    main,
    marker,
    upsert_comment,
)

SUITE = Path("evals/tickets/suite.yaml")
RECORDING = Path("evals/tickets/recording.yaml")
BASE = Path(".agent-evals-base")


@pytest.fixture
def repo(examples_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A checkout of the PR with the base commit in `.agent-evals-base`; both start equal."""
    source = examples_dir / "ticket-classification"
    for root in (tmp_path, tmp_path / BASE):
        (root / SUITE.parent).mkdir(parents=True)
        shutil.copy(source / "suite.yaml", root / SUITE)
        shutil.copy(source / "recording.yaml", root / RECORDING)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _inputs(**overrides: Any) -> Inputs:
    return Inputs(suite=SUITE, replay=RECORDING, base_dir=BASE, **overrides)


def _use_recording(repo: Path, examples_dir: Path, name: str) -> None:
    shutil.copy(examples_dir / "ticket-classification" / name, repo / RECORDING)


# --- evaluate -----------------------------------------------------------------


def test_same_suite_on_both_sides_passes(repo: Path) -> None:
    outcome = evaluate(_inputs())

    assert (outcome.suite, outcome.regressions, outcome.fixes, outcome.stale) == (
        "ticket-classification",
        0,
        0,
        0,
    )
    assert not outcome.failed
    assert not outcome.new_suite
    assert "base vs head" in outcome.markdown


def test_regression_fails_unless_disabled(repo: Path, examples_dir: Path) -> None:
    _use_recording(repo, examples_dir, "recording-new-prompt.yaml")

    outcome = evaluate(_inputs())
    assert (outcome.regressions, outcome.fixes, outcome.failed) == (1, 1, True)
    assert not evaluate(_inputs(fail_on_regression=False)).failed


def test_stale_head_always_fails(repo: Path) -> None:
    text = (repo / SUITE).read_text(encoding="utf-8")
    (repo / SUITE).write_text(
        text.replace("all the data you hold", "every record you keep"), encoding="utf-8"
    )

    outcome = evaluate(_inputs(fail_on_regression=False))

    assert (outcome.stale, outcome.regressions, outcome.failed) == (1, 0, True)
    assert "> [!WARNING]" in outcome.markdown


def test_suite_missing_on_the_base_is_new(repo: Path) -> None:
    shutil.rmtree(repo / BASE)

    outcome = evaluate(_inputs())

    assert outcome.new_suite
    assert not outcome.failed  # 9/10 meets the 0.9 threshold
    assert outcome.markdown.startswith("> [!NOTE]\n> New suite")


def test_renamed_suite_is_an_error(repo: Path) -> None:
    text = (repo / BASE / SUITE).read_text(encoding="utf-8")
    (repo / BASE / SUITE).write_text(
        text.replace("name: ticket-classification", "name: old-name"), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="different suites"):
        evaluate(_inputs())


# --- comment body -------------------------------------------------------------


def _outcome(markdown: str = "## report\n") -> Outcome:
    return Outcome("tickets", markdown, 0, 0, 0, failed=False, new_suite=False)


def test_comment_starts_with_the_marker_and_says_where_it_came_from() -> None:
    body = comment_body(_outcome(), "0123456789abcdef", "https://github.example/run/1")

    assert body.startswith(marker("tickets") + "\n")
    assert "computed for 0123456" in body
    assert "[workflow run](https://github.example/run/1)" in body


def test_long_report_is_cut_to_fit_github_limit() -> None:
    body = comment_body(_outcome("x" * (COMMENT_LIMIT + 500)), "abcdef1", "https://run")

    assert len(body) <= COMMENT_LIMIT
    assert "Report truncated" in body
    assert body.startswith(marker("tickets"))


# --- comments through gh --------------------------------------------------------


class FakeGh:
    """Answers `gh api` calls: lists canned comments, records writes."""

    def __init__(self, comments: list[dict[str, Any]] | None = None) -> None:
        self.comments = comments or []
        self.calls: list[tuple[list[str], str | None]] = []

    def __call__(self, args: list[str], stdin: str | None) -> str:
        self.calls.append((args, stdin))
        if "--paginate" in args:
            return "\n".join(json.dumps(c) for c in self.comments) + "\n"
        return "HTTP/2.0 200 OK\nX-Accepted-Github-Permissions: pull_requests=write\n\n{}"


def _comment(id_: int, login: str, body: str) -> dict[str, Any]:
    return {"id": id_, "login": login, "body": body}


def test_find_comment_needs_the_bot_and_this_suite_marker() -> None:
    gh = FakeGh(
        [
            _comment(1, "a-person", marker("tickets") + "\ncopied by hand"),
            _comment(2, BOT_LOGIN, marker("other-suite") + "\n..."),
            _comment(3, BOT_LOGIN, marker("tickets") + "\n..."),
        ]
    )
    assert find_comment(gh, "owner/repo", 7, "tickets") == 3
    assert find_comment(gh, "owner/repo", 7, "missing") is None


def test_upsert_creates_then_updates() -> None:
    gh = FakeGh()
    assert upsert_comment(gh, "owner/repo", 7, "tickets", "first") == "created"
    args, stdin = gh.calls[-1]
    assert args[:4] == ["api", "-i", "--method", "POST"]
    assert args[4] == "repos/owner/repo/issues/7/comments"
    assert json.loads(stdin or "") == {"body": "first"}

    gh.comments = [_comment(42, BOT_LOGIN, marker("tickets") + "\nfirst")]
    assert upsert_comment(gh, "owner/repo", 7, "tickets", "second") == "updated"
    args, stdin = gh.calls[-1]
    assert args[3:5] == ["PATCH", "repos/owner/repo/issues/comments/42"]
    assert json.loads(stdin or "") == {"body": "second"}


def test_accepted_permissions_header_is_read_from_gh_output() -> None:
    response = (
        "HTTP/2.0 201 Created\n"
        "X-Accepted-Github-Permissions: issues=write; pull_requests=write\n"
        "\n{}"
    )
    assert accepted_permissions(response) == "issues=write; pull_requests=write"
    assert accepted_permissions("HTTP/2.0 201 Created\n\n{}") is None


# --- main -----------------------------------------------------------------------


def _env(repo: Path, *, head_repo: str = "owner/repo", **extra: str) -> dict[str, str]:
    event = repo / "event.json"
    event.write_text(
        json.dumps(
            {
                "pull_request": {
                    "number": 7,
                    "head": {"sha": "0123456789abcdef", "repo": {"full_name": head_repo}},
                }
            }
        ),
        encoding="utf-8",
    )
    return {
        "GITHUB_EVENT_NAME": "pull_request",
        "GITHUB_EVENT_PATH": str(event),
        "GITHUB_REPOSITORY": "owner/repo",
        "GITHUB_SERVER_URL": "https://github.com",
        "GITHUB_RUN_ID": "99",
        "GITHUB_STEP_SUMMARY": str(repo / "summary.md"),
        "GITHUB_OUTPUT": str(repo / "output.txt"),
        "RUNNER_TEMP": str(repo),
        "INPUT_SUITE": str(SUITE),
        "INPUT_REPLAY": str(RECORDING),
        "AGENT_EVALS_BASE_DIR": str(BASE),
        **extra,
    }


@pytest.mark.parametrize("event", ["pull_request_target", "push", ""])
def test_main_refuses_other_events(
    repo: Path, event: str, capsys: pytest.CaptureFixture[str]
) -> None:
    gh = FakeGh()
    assert main({**_env(repo), "GITHUB_EVENT_NAME": event}, gh) == 2
    assert "runs only on pull_request" in capsys.readouterr().out
    assert gh.calls == []


def test_main_writes_summary_outputs_and_comment(repo: Path, examples_dir: Path) -> None:
    _use_recording(repo, examples_dir, "recording-new-prompt.yaml")
    gh = FakeGh()

    assert main(_env(repo), gh) == 1  # one regression

    assert "base vs head" in (repo / "summary.md").read_text(encoding="utf-8")
    outputs = (repo / "output.txt").read_text(encoding="utf-8")
    assert "regressions=1\nfixes=1\nstale=0\n" in outputs
    assert f"report={repo / 'agent-evals-ticket-classification.md'}" in outputs
    body = json.loads(gh.calls[-1][1] or "")["body"]
    assert body.startswith(marker("ticket-classification"))
    assert "https://github.com/owner/repo/actions/runs/99" in body


def test_main_on_a_fork_skips_the_comment(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    gh = FakeGh()
    assert main(_env(repo, head_repo="someone/fork"), gh) == 0
    assert gh.calls == []
    assert "Pull request from a fork" in capsys.readouterr().out
    assert (repo / "summary.md").exists()


def test_main_without_comment_input_makes_no_gh_call(repo: Path) -> None:
    gh = FakeGh()
    assert main(_env(repo, INPUT_COMMENT="false"), gh) == 0
    assert gh.calls == []


def test_main_rejects_absolute_paths(repo: Path) -> None:
    assert main(_env(repo, INPUT_SUITE=str(repo / SUITE)), FakeGh()) == 2


def test_main_reports_a_comment_permission_error(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def forbidden(args: list[str], stdin: str | None) -> str:
        raise subprocess.CalledProcessError(1, ["gh"], stderr="HTTP 403: Resource not accessible")

    assert main(_env(repo), forbidden) == 2
    assert "pull-requests: write" in capsys.readouterr().out
