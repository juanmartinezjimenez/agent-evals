from pathlib import Path

import pytest

from agent_evals.models import Suite
from agent_evals.providers import MissingRecordingError, ReplayProvider
from agent_evals.runner import run_suite


def _load(examples_dir: Path, name: str) -> tuple[Suite, ReplayProvider]:
    folder = examples_dir / name
    return Suite.from_yaml(folder / "suite.yaml"), ReplayProvider.from_yaml(
        folder / "recording.yaml"
    )


def test_ticket_example_scores_nine_out_of_ten(examples_dir: Path) -> None:
    suite, provider = _load(examples_dir, "ticket-classification")
    run = run_suite(suite, provider)

    assert (run.passed, run.total) == (9, 10)
    assert run.pass_rate == pytest.approx(0.9)
    assert run.ok  # threshold is 0.9
    assert [r.case_id for r in run.results if not r.passed] == ["refund-damaged"]


def test_contact_example_catches_wrong_person(examples_dir: Path) -> None:
    suite, provider = _load(examples_dir, "contact-extraction")
    run = run_suite(suite, provider)

    assert (run.passed, run.total) == (4, 5)
    failed = next(r for r in run.results if not r.passed)
    assert failed.case_id == "two-people"
    assert "wrong field values" in failed.reason


def test_threshold_override_fails_the_run(examples_dir: Path) -> None:
    suite, provider = _load(examples_dir, "ticket-classification")
    assert not run_suite(suite, provider, threshold=0.95).ok


def test_results_are_grouped_by_tag(examples_dir: Path) -> None:
    suite, provider = _load(examples_dir, "ticket-classification")
    tags = run_suite(suite, provider).by_tag()

    assert tags["billing"] == (2, 3)
    assert tags["ambiguous"] == (2, 3)


def test_missing_recording_is_an_error(examples_dir: Path) -> None:
    suite, _ = _load(examples_dir, "ticket-classification")
    with pytest.raises(MissingRecordingError):
        run_suite(suite, ReplayProvider({}))


def test_recording_must_be_a_mapping_of_strings(tmp_path: Path) -> None:
    bad = tmp_path / "rec.yaml"
    bad.write_text("- just\n- a list\n", encoding="utf-8")
    with pytest.raises(ValueError, match="mapping"):
        ReplayProvider.from_yaml(bad)


def test_workshop_example_catches_an_invented_slot(examples_dir: Path) -> None:
    suite, provider = _load(examples_dir, "workshop-booking")
    run = run_suite(suite, provider)

    assert (run.passed, run.total) == (5, 6)
    assert run.ok  # threshold is 0.8
    assert [r.case_id for r in run.results if not r.passed] == ["no-invented-slot"]
