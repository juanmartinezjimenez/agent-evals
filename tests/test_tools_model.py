"""Tool definitions and tool expectations in suites (ADR 0008)."""

from typing import Any

import pytest
from pydantic import ValidationError

from agent_evals.models import Suite

TASKS_ADD: dict[str, Any] = {
    "name": "tasks_add",
    "description": "Add an open task.",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "due": {"type": "string", "format": "date"},
            "tags": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["title"],
        "additionalProperties": False,
    },
}


def _suite(tools: list[dict[str, Any]], *cases: dict[str, Any]) -> dict[str, Any]:
    default = {"id": "a", "input": "hi", "expect": {"type": "contains", "values": ["hi"]}}
    return {"name": "demo", "tools": tools, "cases": list(cases) or [default]}


def test_tools_are_optional_and_loaded_in_order() -> None:
    assert Suite.model_validate(_suite([])).tools == []
    suite = Suite.model_validate(_suite([TASKS_ADD, {**TASKS_ADD, "name": "notes_append"}]))
    assert [t.name for t in suite.tools] == ["tasks_add", "notes_append"]
    assert suite.tool_named("tasks_add") == suite.tools[0]
    assert suite.tool_named("missing") is None


@pytest.mark.parametrize(
    ("tool", "message"),
    [
        ({**TASKS_ADD, "name": "tasks add"}, "pattern"),
        ({**TASKS_ADD, "name": "x" * 65}, "pattern"),
        ({**TASKS_ADD, "name": ""}, "pattern"),
        ({**TASKS_ADD, "input_schema": {"type": "string"}}, "type: object"),
        ({**TASKS_ADD, "input_schema": {"properties": {}}}, "type: object"),
        (
            {
                **TASKS_ADD,
                "input_schema": {"type": "object", "properties": {"a": {"type": "nope"}}},
            },
            "not a valid JSON Schema",
        ),
        ({**TASKS_ADD, "parameters": {}}, "Extra inputs"),
    ],
)
def test_invalid_tools_are_rejected(tool: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        Suite.model_validate(_suite([tool]))


def test_tool_names_must_be_unique() -> None:
    with pytest.raises(ValidationError, match="duplicate tool names"):
        Suite.model_validate(_suite([TASKS_ADD, TASKS_ADD]))
