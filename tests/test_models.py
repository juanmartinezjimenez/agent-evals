from pathlib import Path

import pytest
from pydantic import ValidationError

from agent_evals.models import Contains, ExactMatch, JsonSchema, Suite


def _suite(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "name": "demo",
        "cases": [{"id": "a", "input": "hi", "expect": {"type": "exact", "value": "hello"}}],
    }
    data.update(overrides)
    return data


def test_loads_example_suites(examples_dir: Path) -> None:
    tickets = Suite.from_yaml(examples_dir / "ticket-classification" / "suite.yaml")
    contacts = Suite.from_yaml(examples_dir / "contact-extraction" / "suite.yaml")

    assert len(tickets.cases) == 10
    assert all(isinstance(c.expect, ExactMatch) for c in tickets.cases)
    assert all(isinstance(c.expect, JsonSchema) for c in contacts.cases)


def test_expectation_type_selects_model() -> None:
    suite = Suite.model_validate(
        _suite(cases=[{"id": "a", "input": "x", "expect": {"type": "contains", "values": ["y"]}}])
    )
    assert isinstance(suite.cases[0].expect, Contains)


def test_duplicate_case_ids_are_rejected() -> None:
    case = {"id": "a", "input": "hi", "expect": {"type": "exact", "value": "x"}}
    with pytest.raises(ValidationError, match="duplicate case ids"):
        Suite.model_validate(_suite(cases=[case, case]))


def test_unknown_expectation_type_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Suite.model_validate(_suite(cases=[{"id": "a", "input": "x", "expect": {"type": "vibes"}}]))


def test_unknown_keys_are_rejected() -> None:
    with pytest.raises(ValidationError):
        Suite.model_validate(_suite(treshold=0.5))  # typo must not pass silently


@pytest.mark.parametrize("threshold", [-0.1, 1.5])
def test_threshold_must_be_a_ratio(threshold: float) -> None:
    with pytest.raises(ValidationError):
        Suite.model_validate(_suite(threshold=threshold))


def test_case_id_format() -> None:
    with pytest.raises(ValidationError):
        Suite.model_validate(
            _suite(
                cases=[{"id": "Bad Id", "input": "x", "expect": {"type": "exact", "value": "y"}}]
            )
        )
