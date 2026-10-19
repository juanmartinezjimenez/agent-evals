"""CLI paths for live providers, with the provider factory replaced by a fake."""

import json
from pathlib import Path
from typing import Any

import pytest

from agent_evals import cli
from agent_evals.cli import EXIT_CONFIG_ERROR, EXIT_OK, main
from agent_evals.providers import ReplayProvider
from tests.fakes import ProviderSetupError, ScriptedProvider

TICKETS = Path(__file__).resolve().parent.parent / "examples" / "ticket-classification"
CORRECT = {
    "double-charge": "billing",
    "invoice-copy": "billing",
    "app-crash": "technical",
    "sync-error": "technical",
    "password-reset": "account",
    "change-email": "account",
    "delete-account": "account",
    "late-parcel": "shipping",
    "wrong-address": "shipping",
    "refund-damaged": "billing",
}


@pytest.fixture
def live(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Make `--provider anthropic` return a scripted provider and remember the call."""
    seen: dict[str, Any] = {}

    def fake_make_provider(name: str, **kwargs: Any) -> Any:
        seen.update(name=name, **kwargs)
        if name == "replay":
            return ReplayProvider.from_yaml(kwargs["replay"])
        return ScriptedProvider(dict(CORRECT), model=kwargs["model"])

    monkeypatch.setattr(cli, "make_provider", fake_make_provider)
    return seen


def _live_args(*extra: str) -> list[str]:
    suite = str(TICKETS / "suite.yaml")
    return ["run", suite, "--provider", "anthropic", "--model", "claude-test", *extra]


def test_live_run_reports_usage_and_cost(
    live: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(_live_args("--price-input", "1", "--price-output", "5"))
    out = capsys.readouterr().out

    assert code == EXIT_OK
    assert live == {"name": "anthropic", "model": "claude-test", "replay": None}
    assert "10/10 passed" in out
    assert "scripted:claude-test" in out
    assert "1,000 in / 100 out tokens" in out
    assert "$0.0015" in out


def test_record_then_replay_gives_the_same_result(live: dict[str, Any], tmp_path: Path) -> None:
    recording = tmp_path / "rec.yaml"
    assert main(_live_args("--record", str(recording))) == EXIT_OK

    replayed = tmp_path / "replayed.json"
    args = ["run", str(TICKETS / "suite.yaml"), "--replay", str(recording)]
    assert main([*args, "--json", str(replayed)]) == EXIT_OK
    assert json.loads(replayed.read_text(encoding="utf-8"))["passed"] == 10


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        (("--price-input", "1"), "must be given together"),
        (("--price-input", "-1", "--price-output", "1"), "negative"),
    ],
)
def test_invalid_pricing_exits_two(
    live: dict[str, Any], capsys: pytest.CaptureFixture[str], extra: tuple[str, ...], message: str
) -> None:
    assert main(_live_args(*extra)) == EXIT_CONFIG_ERROR
    assert message in capsys.readouterr().err


def test_record_with_replay_is_rejected(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    args = ["run", str(TICKETS / "suite.yaml"), "--replay", str(TICKETS / "recording.yaml")]
    assert main([*args, "--record", str(tmp_path / "x.yaml")]) == EXIT_CONFIG_ERROR
    assert "live provider" in capsys.readouterr().err


def test_no_source_is_rejected(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["run", str(TICKETS / "suite.yaml")]) == EXIT_CONFIG_ERROR
    assert "choose a source" in capsys.readouterr().err


def test_setup_error_exits_two(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def broken(name: str, **kwargs: Any) -> Any:
        raise ProviderSetupError("cannot create Anthropic client: no API key")

    monkeypatch.setattr(cli, "make_provider", broken)
    assert main(_live_args()) == EXIT_CONFIG_ERROR
    assert "no API key" in capsys.readouterr().err
