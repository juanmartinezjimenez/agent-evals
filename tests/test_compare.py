from pathlib import Path

import pytest
from pydantic import ValidationError

from agent_evals.compare import CaseChange, CaseReport, RunReport, compare
from agent_evals.models import Suite
from agent_evals.providers import ReplayProvider
from agent_evals.report import to_json
from agent_evals.runner import run_suite


def _report(*cases: tuple[str, bool], suite: str = "demo") -> RunReport:
    results = [
        CaseReport(case_id=case_id, passed=passed, reason="ok" if passed else f"{case_id} wrong")
        for case_id, passed in cases
    ]
    passed = sum(r.passed for r in results)
    return RunReport(
        suite=suite,
        provider="replay",
        passed=passed,
        total=len(results),
        pass_rate=passed / len(results),
        mean_latency_ms=1.0,
        p95_latency_ms=2.0,
        results=results,
    )


def test_case_that_starts_failing_is_a_regression() -> None:
    result = compare(_report(("a", True), ("b", True)), _report(("a", True), ("b", False)))

    assert result.regressions == (CaseChange("b", "b wrong"),)
    assert result.fixes == ()
    assert not result.ok


def test_case_that_starts_passing_is_a_fix_with_the_old_reason() -> None:
    result = compare(_report(("a", False)), _report(("a", True)))

    assert result.fixes == (CaseChange("a", "a wrong"),)
    assert result.ok


def test_unchanged_failures_are_neither_regressions_nor_fixes() -> None:
    result = compare(_report(("a", False)), _report(("a", False)))
    assert (result.regressions, result.fixes, result.ok) == ((), (), True)


def test_same_pass_rate_can_hide_a_regression() -> None:
    base = _report(("a", True), ("b", False))
    head = _report(("a", False), ("b", True))

    result = compare(base, head)

    assert base.pass_rate == head.pass_rate
    assert [c.case_id for c in result.regressions] == ["a"]
    assert [c.case_id for c in result.fixes] == ["b"]
    assert not result.ok


def test_added_and_removed_cases_do_not_count_as_regressions() -> None:
    result = compare(_report(("a", True), ("old", True)), _report(("a", True), ("new", False)))

    assert [r.case_id for r in result.added] == ["new"]
    assert [r.case_id for r in result.removed] == ["old"]
    assert result.ok


def test_different_suites_cannot_be_compared() -> None:
    with pytest.raises(ValueError, match="different suites"):
        compare(_report(("a", True), suite="one"), _report(("a", True), suite="two"))


def test_reads_the_json_written_by_run(examples_dir: Path, tmp_path: Path) -> None:
    folder = examples_dir / "ticket-classification"
    run = run_suite(
        Suite.from_yaml(folder / "suite.yaml"),
        ReplayProvider.from_yaml(folder / "recording.yaml"),
    )
    path = tmp_path / "run.json"
    path.write_text(to_json(run), encoding="utf-8")

    report = RunReport.from_json(path)

    assert (report.suite, report.passed, report.total) == ("ticket-classification", 9, 10)
    assert report.target == "replay"
    assert [r.case_id for r in report.results if not r.passed] == ["refund-damaged"]


def test_invalid_report_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "run.json"
    path.write_text('{"suite": "demo"}', encoding="utf-8")
    with pytest.raises(ValidationError):
        RunReport.from_json(path)
