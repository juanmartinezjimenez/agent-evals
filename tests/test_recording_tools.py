"""Recording format 3 and fingerprints with tools (ADR 0008)."""

from pathlib import Path
from typing import Any

import pytest
import yaml

from agent_evals.cli import EXIT_CONFIG_ERROR, EXIT_OK, main
from agent_evals.models import Suite, Tool, ToolCall
from agent_evals.providers import ReplayProvider, StaleRecordingError, fingerprint, write_recording

TASKS_ADD: dict[str, Any] = {
    "name": "tasks_add",
    "description": "Add an open task.",
    "input_schema": {
        "type": "object",
        "properties": {"title": {"type": "string"}},
        "required": ["title"],
    },
}


def _suite(tools: list[dict[str, Any]] | None = None, system: str = "Manage tasks.") -> Suite:
    return Suite.model_validate(
        {
            "name": "agent",
            "system": system,
            "tools": [TASKS_ADD] if tools is None else tools,
            "cases": [
                {
                    "id": "add",
                    "input": "Remind me to renew the library card.",
                    "expect": {"type": "tool_call", "tool": "tasks_add"},
                },
                {"id": "thanks", "input": "Thanks!", "expect": {"type": "no_tool_call"}},
            ],
        }
    )


CALL = ToolCall("tasks_add", {"title": "Renew the library card"})


def test_fingerprints_include_tools_only_when_there_are_some() -> None:
    suite = _suite()
    case = suite.cases[1]
    without = fingerprint(suite.system, case)
    assert fingerprint(suite.system, case, ()) == without  # suites without tools are unchanged
    with_tools = fingerprint(suite.system, case, suite.tools)
    assert with_tools != without

    edited = _suite([{**TASKS_ADD, "description": "Add a task to the list."}])
    assert fingerprint(edited.system, edited.cases[1], edited.tools) != with_tools
    renamed = Tool.model_validate({**TASKS_ADD, "name": "task_add"})
    assert fingerprint(suite.system, case, [renamed]) != with_tools
    crlf = _suite([{**TASKS_ADD, "description": "Add an open\r\ntask."}])
    lf = _suite([{**TASKS_ADD, "description": "Add an open\ntask."}])
    assert fingerprint(crlf.system, crlf.cases[1], crlf.tools) == fingerprint(
        lf.system, lf.cases[1], lf.tools
    )


def test_tool_suites_record_format_3_and_replay_the_call(tmp_path: Path) -> None:
    suite = _suite()
    path = tmp_path / "rec.yaml"
    write_recording(
        path,
        suite,
        {"add": "I'll add it.", "thanks": "You're welcome!"},
        tool_calls={"add": CALL, "thanks": None},
        provider="anthropic",
        model="claude-test",
    )

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["version"] == 3
    assert data["cases"]["add"]["tool_call"] == {
        "name": "tasks_add",
        "arguments": {"title": "Renew the library card"},
    }
    assert data["cases"]["thanks"]["tool_call"] is None

    replay = ReplayProvider.from_yaml(path)
    add = replay.complete(suite.system, suite.cases[0], suite.tools)
    assert (add.text, add.tool_call) == ("I'll add it.", CALL)
    assert replay.complete(suite.system, suite.cases[1], suite.tools).tool_call is None


def test_suites_without_tools_still_record_format_2(tmp_path: Path) -> None:
    suite = Suite.model_validate(
        {
            "name": "s",
            "cases": [{"id": "a", "input": "x", "expect": {"type": "exact", "value": "y"}}],
        }
    )
    path = tmp_path / "rec.yaml"
    write_recording(path, suite, {"a": "y"})
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["version"] == 2
    assert "tool_call" not in data["cases"]["a"]


def test_a_changed_tool_makes_the_replay_stale(tmp_path: Path) -> None:
    path = tmp_path / "rec.yaml"
    write_recording(path, _suite(), {"add": "", "thanks": "Bye"}, tool_calls={"add": CALL})
    edited = _suite([{**TASKS_ADD, "description": "Add a task with a due date."}])
    with pytest.raises(StaleRecordingError):
        ReplayProvider.from_yaml(path).complete(edited.system, edited.cases[0], edited.tools)


def test_record_and_replay_a_tool_suite_through_the_cli(tmp_path: Path) -> None:
    suite_file = tmp_path / "suite.yaml"
    suite_file.write_text(
        yaml.safe_dump(_suite().model_dump(by_alias=True, exclude_defaults=True)), encoding="utf-8"
    )
    source = tmp_path / "source.yaml"
    write_recording(source, _suite(), {"add": "", "thanks": "Bye!"}, tool_calls={"add": CALL})
    upgraded = tmp_path / "upgraded.yaml"

    # Replay + --record rewrites the recording, keeping each tool call.
    args = ["run", str(suite_file), "--replay", str(source), "--record", str(upgraded)]
    assert main(args) == EXIT_OK
    data = yaml.safe_load(upgraded.read_text(encoding="utf-8"))
    assert data["version"] == 3
    assert data["cases"]["add"]["tool_call"]["name"] == "tasks_add"

    suite_file.write_text(
        suite_file.read_text(encoding="utf-8").replace("Add an open task.", "Add a task."),
        encoding="utf-8",
    )
    assert main(["run", str(suite_file), "--replay", str(upgraded)]) == EXIT_CONFIG_ERROR  # stale
