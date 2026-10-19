import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from agent_evals.cli import (
    EXIT_BELOW_THRESHOLD,
    EXIT_CONFIG_ERROR,
    EXIT_OK,
    EXIT_REGRESSION,
    main,
)


def _args(examples_dir: Path, name: str, *extra: str) -> list[str]:
    folder = examples_dir / name
    return ["run", str(folder / "suite.yaml"), "--replay", str(folder / "recording.yaml"), *extra]


def test_passing_suite_exits_zero(examples_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(_args(examples_dir, "ticket-classification")) == EXIT_OK
    out = capsys.readouterr().out
    assert out.startswith("PASS ticket-classification: 9/10 passed")
    assert "refund-damaged" in out


def test_below_threshold_exits_one(examples_dir: Path) -> None:
    args = _args(examples_dir, "ticket-classification", "--threshold", "0.95")
    assert main(args) == EXIT_BELOW_THRESHOLD


def test_writes_json_and_markdown_reports(examples_dir: Path, tmp_path: Path) -> None:
    json_out, md_out = tmp_path / "run.json", tmp_path / "run.md"
    main(
        _args(
            examples_dir, "contact-extraction", "--json", str(json_out), "--markdown", str(md_out)
        )
    )

    data = json.loads(json_out.read_text(encoding="utf-8"))
    assert data["passed"] == 4
    assert data["ok"] is True
    assert data["by_tag"]["quote"] == {"passed": 1, "total": 2}

    markdown = md_out.read_text(encoding="utf-8")
    assert "✅ PASS" in markdown
    assert "`two-people`" in markdown


def test_invalid_suite_exits_two(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    suite = tmp_path / "suite.yaml"
    suite.write_text("name: broken\ncases: []\n", encoding="utf-8")
    recording = tmp_path / "rec.yaml"
    recording.write_text("{}\n", encoding="utf-8")

    assert main(["run", str(suite), "--replay", str(recording)]) == EXIT_CONFIG_ERROR
    assert "error:" in capsys.readouterr().err


def test_missing_recording_exits_two(examples_dir: Path, tmp_path: Path) -> None:
    empty = tmp_path / "rec.yaml"
    empty.write_text("{}\n", encoding="utf-8")
    suite = examples_dir / "ticket-classification" / "suite.yaml"
    assert main(["run", str(suite), "--replay", str(empty)]) == EXIT_CONFIG_ERROR


def _report(examples_dir: Path, tmp_path: Path, recording: str) -> Path:
    folder = examples_dir / "ticket-classification"
    out = tmp_path / f"{recording}.json"
    main(
        [
            "run",
            str(folder / "suite.yaml"),
            "--replay",
            str(folder / f"{recording}.yaml"),
            "--json",
            str(out),
        ]
    )
    return out


def test_compare_exits_one_on_a_regression_hidden_by_the_same_pass_rate(
    examples_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    base = _report(examples_dir, tmp_path, "recording")
    head = _report(examples_dir, tmp_path, "recording-new-prompt")
    capsys.readouterr()

    assert main(["compare", str(base), str(head)]) == EXIT_REGRESSION
    out = capsys.readouterr().out
    assert out.startswith("FAIL ticket-classification: 1 regression, 1 fix")
    assert "pass rate 90% → 90% (+0 pp)" in out
    assert "✗ wrong-address: expected 'shipping', got 'account'" in out
    assert "✓ refund-damaged: fixed" in out


def test_compare_of_a_run_with_itself_passes_and_writes_markdown(
    examples_dir: Path, tmp_path: Path
) -> None:
    base = _report(examples_dir, tmp_path, "recording")
    md_out = tmp_path / "compare.md"

    assert main(["compare", str(base), str(base), "--markdown", str(md_out)]) == EXIT_OK
    markdown = md_out.read_text(encoding="utf-8")
    assert "✅ PASS" in markdown
    assert "| Pass rate | 90% (9/10) | 90% (9/10) | +0 pp |" in markdown
    assert "### Regressions" not in markdown


def test_compare_markdown_lists_regressions_and_fixes(examples_dir: Path, tmp_path: Path) -> None:
    base = _report(examples_dir, tmp_path, "recording")
    head = _report(examples_dir, tmp_path, "recording-new-prompt")
    md_out = tmp_path / "compare.md"

    main(["compare", str(base), str(head), "--markdown", str(md_out)])
    markdown = md_out.read_text(encoding="utf-8")
    assert "❌ FAIL" in markdown
    assert "| `wrong-address` | expected 'shipping', got 'account' |" in markdown
    assert "| `refund-damaged` | expected 'billing', got 'shipping' |" in markdown


def test_compare_with_unreadable_report_exits_two(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text("not json", encoding="utf-8")

    assert main(["compare", str(broken), str(tmp_path / "missing.json")]) == EXIT_CONFIG_ERROR
    assert "error:" in capsys.readouterr().err


def test_output_survives_a_non_utf8_stdout(examples_dir: Path) -> None:
    # Windows pipes default to cp1252, which cannot encode the ✗ and → markers.
    folder = examples_dir / "ticket-classification"
    command = [sys.executable, "-m", "agent_evals.cli", "run", str(folder / "suite.yaml")]
    command += ["--replay", str(folder / "recording.yaml")]

    done = subprocess.run(
        command,
        capture_output=True,
        env={**os.environ, "PYTHONIOENCODING": "cp1252"},
        check=False,
    )

    assert done.returncode == EXIT_OK, done.stderr.decode(errors="replace")
    assert "✗ refund-damaged" in done.stdout.decode("utf-8")
