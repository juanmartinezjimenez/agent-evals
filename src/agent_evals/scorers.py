"""Deterministic scorers: each one turns (expectation, output) into a verdict."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import jsonschema

from agent_evals.models import (
    TOOL_EXPECTATIONS,
    Contains,
    ExactMatch,
    Expectation,
    JsonSchema,
    NoCallTo,
    NoToolCall,
    Regex,
    TextExpectation,
    Tool,
    ToolCall,
    ToolCallMatch,
)


@dataclass(frozen=True, slots=True)
class Score:
    passed: bool
    reason: str


@dataclass(frozen=True, slots=True)
class Answer:
    """What the model returned for a case: its text and, maybe, its first tool call."""

    text: str
    tool_call: ToolCall | None = None


def score_case(
    expectations: Sequence[Expectation], answer: Answer, tools: Sequence[Tool] = ()
) -> Score:
    """Every expectation must pass; the reason lists the ones that failed (ADR 0008).

    Tool expectations read the tool call, text expectations read the text. In a
    suite with tools, a case with only text expectations also requires no call.
    """
    by_name = {tool.name: tool for tool in tools}
    scores = [_score_one(expect, answer, by_name) for expect in expectations]
    only_text = not any(isinstance(e, TOOL_EXPECTATIONS) for e in expectations)
    if by_name and only_text and answer.tool_call is not None:
        scores.append(
            Score(False, f"expected a text answer, got a call to {answer.tool_call.name}")
        )
    failed = [s.reason for s in scores if not s.passed]
    if failed:
        return Score(False, "; ".join(failed))
    return Score(True, "; ".join(s.reason for s in scores))


def _score_one(expect: Expectation, answer: Answer, tools: dict[str, Tool]) -> Score:
    call = answer.tool_call
    match expect:
        case ToolCallMatch():
            return _tool_call(expect, call, tools)
        case NoToolCall():
            if call is None:
                return Score(True, "no tool call")
            return Score(False, f"expected no tool call, got a call to {call.name}")
        case NoCallTo():
            if call is not None and call.name in expect.tools:
                return Score(False, f"called forbidden tool {call.name}")
            return Score(True, f"none of {expect.tools} called")
        case _:
            if call is not None and not answer.text.strip():
                return Score(False, f"no text in the answer, only a call to {call.name}")
            return score(expect, answer.text)


def _tool_call(expect: ToolCallMatch, call: ToolCall | None, tools: dict[str, Tool]) -> Score:
    if call is None:
        return Score(False, f"expected a call to {expect.tool}, got a text answer")
    if call.name != expect.tool:
        return Score(False, f"expected {expect.tool}, got {call.name}")
    if not isinstance(call.arguments, dict):
        return Score(False, f"arguments of {call.name} are not a JSON object: {call.arguments!r}")

    validator = jsonschema.Draft202012Validator(
        tools[call.name].input_schema, format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER
    )
    errors = sorted(validator.iter_errors(call.arguments), key=lambda e: list(e.path))
    if errors:
        first = errors[0]
        where = ".".join(str(p) for p in first.path)
        at = f" at {where}" if where else ""
        return Score(
            False, f"arguments do not match the schema of {call.name}{at}: {first.message}"
        )

    if expect.arguments is not None:
        problem = _match(expect.arguments, call.arguments, expect.match == "exact", "")
        if problem:
            return Score(False, problem)
    return Score(True, f"called {call.name} with matching arguments")


def _same_value(want: Any, got: Any) -> bool:
    if isinstance(want, bool) or isinstance(got, bool):
        return type(want) is type(got) and want == got
    if isinstance(want, int | float) and isinstance(got, int | float):
        return float(want) == float(got)
    return bool(want == got)


def _match(want: Any, got: Any, exact: bool, path: str) -> str | None:
    """Why `got` does not match `want`, or None. Subset unless `exact`."""
    label = f"argument {path}" if path else "arguments"
    if isinstance(want, dict) and "$regex" in want:
        pattern = want["$regex"]
        if isinstance(got, str) and re.search(pattern, got):
            return None
        return f"{label}: {got!r} does not match /{pattern}/"
    if isinstance(want, dict):
        if not isinstance(got, dict):
            return f"{label}: expected an object, got {got!r}"
        for key, value in want.items():
            child = f"{path}.{key}" if path else key
            if key not in got:
                return f"argument {child}: missing"
            problem = _match(value, got[key], exact, child)
            if problem:
                return problem
        extra = sorted(set(got) - set(want)) if exact else []
        if extra:
            return f"{label}: unexpected {', '.join(extra)}"
        return None
    if isinstance(want, list):
        if not isinstance(got, list) or len(got) != len(want):
            return f"{label}: expected {want!r}, got {got!r}"
        for index, (w, g) in enumerate(zip(want, got, strict=True)):
            problem = _match(w, g, exact, f"{path}[{index}]")
            if problem:
                return problem
        return None
    if _same_value(want, got):
        return None
    return f"{label}: expected {want!r}, got {got!r}"


def _normalise(text: str, case_sensitive: bool) -> str:
    collapsed = " ".join(text.split())
    return collapsed if case_sensitive else collapsed.casefold()


def score(expect: TextExpectation, output: str) -> Score:
    match expect:
        case ExactMatch():
            return _exact(expect, output)
        case Contains():
            return _contains(expect, output)
        case Regex():
            return _regex(expect, output)
        case JsonSchema():
            return _json_schema(expect, output)


def _exact(expect: ExactMatch, output: str) -> Score:
    got = _normalise(output, expect.case_sensitive)
    want = _normalise(expect.value, expect.case_sensitive)
    if got == want:
        return Score(True, "exact match")
    return Score(False, f"expected {expect.value!r}, got {output.strip()!r}")


def _contains(expect: Contains, output: str) -> Score:
    haystack = _normalise(output, expect.case_sensitive)
    missing = [v for v in expect.values if _normalise(v, expect.case_sensitive) not in haystack]
    if not missing:
        return Score(True, f"contains all {len(expect.values)} values")
    return Score(False, f"missing {missing}")


def _regex(expect: Regex, output: str) -> Score:
    if re.search(expect.pattern, output):
        return Score(True, "pattern matched")
    return Score(False, f"no match for /{expect.pattern}/")


def _json_schema(expect: JsonSchema, output: str) -> Score:
    try:
        data = json.loads(_strip_code_fence(output))
    except json.JSONDecodeError as exc:
        return Score(False, f"invalid JSON: {exc.msg}")

    errors = sorted(
        jsonschema.Draft202012Validator(expect.json_schema).iter_errors(data),
        key=lambda e: list(e.path),
    )
    if errors:
        first = errors[0]
        where = "/".join(str(p) for p in first.path) or "<root>"
        return Score(False, f"schema error at {where}: {first.message}")

    wrong = {key: data.get(key) for key, value in expect.fields.items() if data.get(key) != value}
    if wrong:
        return Score(False, f"wrong field values: {wrong}")
    return Score(True, "valid JSON matching schema and fields")


def _strip_code_fence(text: str) -> str:
    """Models often wrap JSON in ```json fences; accept that."""
    stripped = text.strip()
    fence = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", stripped, flags=re.DOTALL)
    return fence.group(1) if fence else stripped
