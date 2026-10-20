"""Scoring answers that may contain a tool call (ADR 0008)."""

from typing import Any

import pytest

from agent_evals.models import Expectation, Suite, ToolCall
from agent_evals.scorers import Answer, score_case

TOOLS: list[dict[str, Any]] = [
    {
        "name": "tasks_add",
        "description": "Add an open task.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "minLength": 1},
                "due": {"type": "string", "format": "date"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "details": {
                    "type": "object",
                    "properties": {"priority": {"type": "integer"}, "note": {"type": "string"}},
                },
            },
            "required": ["title"],
            "additionalProperties": False,
        },
    },
    {
        "name": "notes_append",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "text": {"type": "string"}},
            "required": ["path", "text"],
        },
    },
    {
        "name": "notes_write",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"],
        },
    },
]


def _score(expect: Any, text: str = "", call: ToolCall | None = None) -> tuple[bool, str]:
    suite = Suite.model_validate(
        {"name": "s", "tools": TOOLS, "cases": [{"id": "c", "input": "x", "expect": expect}]}
    )
    case = suite.cases[0]
    result = score_case(case.expectations, Answer(text, call), suite.tools)
    return result.passed, result.reason


ADD = ToolCall(
    "tasks_add", {"title": "Renew the library card", "due": "2026-11-05", "tags": ["personal"]}
)


def test_the_right_call_with_matching_arguments_passes() -> None:
    expect = {
        "type": "tool_call",
        "tool": "tasks_add",
        "arguments": {
            "due": "2026-11-05",
            "tags": ["personal"],
            "title": {"$regex": "(?i)LIBRARY"},
        },
    }
    assert _score(expect, call=ADD) == (True, "called tasks_add with matching arguments")


@pytest.mark.parametrize(
    ("call", "text", "reason"),
    [
        (None, "Sure, I added it.", "expected a call to tasks_add, got a text answer"),
        (
            ToolCall("notes_write", {"path": "a.md", "content": "x"}),
            "",
            "expected tasks_add, got notes_write",
        ),
        (ToolCall("tasks_add", "{not json"), "", "arguments of tasks_add are not a JSON object"),
        (ToolCall("tasks_add", {"due": "2026-11-05"}), "", "'title' is a required property"),
        (
            ToolCall("tasks_add", {"title": "x", "due": "5 November"}),
            "",
            "schema of tasks_add at due: '5 November' is not a 'date'",
        ),
        (
            ToolCall("tasks_add", {"title": "x", "colour": "red"}),
            "",
            "Additional properties are not allowed",
        ),
    ],
)
def test_wrong_calls_explain_why(call: ToolCall | None, text: str, reason: str) -> None:
    passed, why = _score({"type": "tool_call", "tool": "tasks_add"}, text, call)
    assert not passed
    assert reason in why


@pytest.mark.parametrize(
    ("arguments", "reason"),
    [
        ({"due": "2026-05-11"}, "argument due: expected '2026-05-11', got '2026-11-05'"),
        ({"tags": ["personal", "home"]}, "argument tags: expected ['personal', 'home']"),
        (
            {"title": {"$regex": "passport"}},
            "argument title: 'Renew the library card' does not match",
        ),
        ({"details": {"priority": 1}}, "argument details: missing"),
    ],
)
def test_argument_mismatches_name_the_argument(arguments: dict[str, Any], reason: str) -> None:
    passed, why = _score(
        {"type": "tool_call", "tool": "tasks_add", "arguments": arguments}, call=ADD
    )
    assert not passed
    assert reason in why


def test_subset_allows_extra_arguments_and_exact_does_not() -> None:
    subset = {"type": "tool_call", "tool": "tasks_add", "arguments": {"due": "2026-11-05"}}
    assert _score(subset, call=ADD)[0]
    exact = {**subset, "match": "exact"}
    passed, why = _score(exact, call=ADD)
    assert not passed
    assert why == "arguments: unexpected tags, title"


def test_nested_objects_and_numbers_match_by_value() -> None:
    call = ToolCall("tasks_add", {"title": "x", "details": {"priority": 2, "note": "call first"}})
    expect = {
        "type": "tool_call",
        "tool": "tasks_add",
        "arguments": {"details": {"priority": 2.0, "note": {"$regex": "call"}}},
    }
    assert _score(expect, call=call)[0]


def test_booleans_are_not_numbers() -> None:
    schema_tool = {
        "name": "flag",
        "input_schema": {"type": "object", "properties": {"on": {}}},
    }
    suite = Suite.model_validate(
        {
            "name": "s",
            "tools": [schema_tool],
            "cases": [
                {
                    "id": "c",
                    "input": "x",
                    "expect": {"type": "tool_call", "tool": "flag", "arguments": {"on": 1}},
                }
            ],
        }
    )
    result = score_case(
        suite.cases[0].expectations, Answer("", ToolCall("flag", {"on": True})), suite.tools
    )
    assert not result.passed


def test_no_tool_call() -> None:
    assert _score({"type": "no_tool_call"}, "You're welcome!") == (True, "no tool call")
    assert _score({"type": "no_tool_call"}, "Done.", ADD) == (
        False,
        "expected no tool call, got a call to tasks_add",
    )


def test_no_call_to_allows_text_and_other_tools() -> None:
    forbid = {"type": "no_call_to", "tools": ["notes_write", "notes_append"]}
    assert _score(forbid, "Here is the summary.")[0]
    assert _score(forbid, "", ADD)[0]
    passed, why = _score(forbid, "", ToolCall("notes_append", {"path": "inbox.md", "text": "x"}))
    assert (passed, why) == (False, "called forbidden tool notes_append")


def test_text_and_a_call_can_be_checked_together() -> None:
    both = [
        {"type": "tool_call", "tool": "tasks_add"},
        {"type": "contains", "values": ["library card"]},
    ]
    assert _score(both, "I'll add a task to renew the library card.", ADD)[0]
    passed, why = _score(both, "", ADD)
    assert not passed
    assert why == "no text in the answer, only a call to tasks_add"


def test_text_only_cases_in_a_tool_suite_must_not_call() -> None:
    expect = {"type": "contains", "values": ["lentils"]}
    assert _score(expect, "Lentils with cumin.")[0]
    passed, why = _score(
        expect, "Lentils with cumin.", ToolCall("notes_append", {"path": "a.md", "text": "x"})
    )
    assert not passed
    assert why == "expected a text answer, got a call to notes_append"


def test_all_failures_are_listed() -> None:
    expectations = [
        {"type": "no_call_to", "tools": ["notes_append"]},
        {"type": "contains", "values": ["lentils"]},
    ]
    passed, why = _score(expectations, "", ToolCall("notes_append", {"path": "a.md", "text": "x"}))
    assert not passed
    assert (
        why
        == "called forbidden tool notes_append; no text in the answer, only a call to notes_append"
    )


def test_text_suites_without_tools_are_unchanged() -> None:
    suite = Suite.model_validate(
        {
            "name": "s",
            "cases": [{"id": "c", "input": "x", "expect": {"type": "exact", "value": "billing"}}],
        }
    )
    expectations: tuple[Expectation, ...] = suite.cases[0].expectations
    assert score_case(expectations, Answer("Billing")).reason == "exact match"
