import json
from pathlib import Path

import pytest

from agent_evals.cli import EXIT_BELOW_THRESHOLD, EXIT_CONFIG_ERROR, EXIT_OK, main


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
