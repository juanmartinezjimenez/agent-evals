import pytest

from agent_evals.models import Contains, ExactMatch, JsonSchema, Regex
from agent_evals.scorers import score

SCHEMA = {
    "type": "object",
    "required": ["name", "intent"],
    "properties": {"name": {"type": "string"}, "intent": {"enum": ["quote", "other"]}},
}


@pytest.mark.parametrize(
    ("output", "passed"),
    [("billing", True), ("  Billing \n", True), ("billing.", False), ("technical", False)],
)
def test_exact_is_case_and_whitespace_insensitive_by_default(output: str, passed: bool) -> None:
    assert score(ExactMatch(type="exact", value="billing"), output).passed is passed


def test_exact_can_be_case_sensitive() -> None:
    expect = ExactMatch(type="exact", value="OK", case_sensitive=True)
    assert score(expect, "OK").passed
    assert not score(expect, "ok").passed


def test_contains_reports_missing_values() -> None:
    result = score(Contains(type="contains", values=["refund", "order 42"]), "Refund issued")
    assert not result.passed
    assert "order 42" in result.reason


def test_regex() -> None:
    expect = Regex(type="regex", pattern=r"\bINV-\d{4}\b")
    assert score(expect, "see INV-2026 attached").passed
    assert not score(expect, "see INV-26").passed


def _json(fields: dict[str, object] | None = None) -> JsonSchema:
    return JsonSchema.model_validate(
        {"type": "json_schema", "schema": SCHEMA, "fields": fields or {}}
    )


def test_json_schema_accepts_valid_output_and_fields() -> None:
    result = score(_json({"intent": "quote"}), '{"name": "Laura", "intent": "quote"}')
    assert result.passed, result.reason


def test_json_schema_accepts_code_fence() -> None:
    output = '```json\n{"name": "Laura", "intent": "other"}\n```'
    assert score(_json(), output).passed


@pytest.mark.parametrize(
    ("output", "reason"),
    [
        ("not json", "invalid JSON"),
        ('{"name": "Laura"}', "schema error"),
        ('{"name": "Laura", "intent": "refund"}', "schema error at intent"),
        ('{"name": "Irene", "intent": "quote"}', "wrong field values"),
    ],
)
def test_json_schema_failures_explain_why(output: str, reason: str) -> None:
    result = score(_json({"name": "Laura"}), output)
    assert not result.passed
    assert reason in result.reason
