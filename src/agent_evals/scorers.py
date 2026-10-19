"""Deterministic scorers: each one turns (expectation, output) into a verdict."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

import jsonschema

from agent_evals.models import Contains, ExactMatch, Expectation, JsonSchema, Regex


@dataclass(frozen=True, slots=True)
class Score:
    passed: bool
    reason: str


def _normalise(text: str, case_sensitive: bool) -> str:
    collapsed = " ".join(text.split())
    return collapsed if case_sensitive else collapsed.casefold()


def score(expect: Expectation, output: str) -> Score:
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
