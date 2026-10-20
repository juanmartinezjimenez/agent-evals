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


def _conversation(*turns: tuple[str, str], **extra: object) -> dict[str, object]:
    case: dict[str, object] = {
        "id": "chat",
        "turns": [{"role": role, "content": content} for role, content in turns],
        "expect": {"type": "exact", "value": "x"},
    }
    case.update(extra)
    return _suite(cases=[case])


def test_turns_are_loaded_as_the_conversation() -> None:
    suite = Suite.model_validate(
        _conversation(
            ("user", "Book me in"), ("assistant", "Tuesday or Thursday?"), ("user", "Thu")
        )
    )
    case = suite.cases[0]

    assert case.input is None
    assert [(t.role, t.content) for t in case.messages] == [
        ("user", "Book me in"),
        ("assistant", "Tuesday or Thursday?"),
        ("user", "Thu"),
    ]


def test_input_is_a_single_user_turn() -> None:
    case = Suite.model_validate(_suite()).cases[0]
    assert [(t.role, t.content) for t in case.messages] == [("user", "hi")]


def test_case_needs_input_or_turns() -> None:
    with pytest.raises(ValidationError, match="exactly one of 'input' or 'turns'"):
        Suite.model_validate(_suite(cases=[{"id": "a", "expect": {"type": "exact", "value": "x"}}]))


def test_case_cannot_have_both_input_and_turns() -> None:
    with pytest.raises(ValidationError, match="exactly one of 'input' or 'turns'"):
        Suite.model_validate(_conversation(("user", "hi"), input="hi"))


def test_turns_must_start_with_the_user() -> None:
    with pytest.raises(ValidationError, match="turn 1 must be from the user"):
        Suite.model_validate(_conversation(("assistant", "Hello"), ("user", "hi")))


def test_turns_must_alternate_roles() -> None:
    with pytest.raises(ValidationError, match="turn 2 must be from the assistant"):
        Suite.model_validate(_conversation(("user", "hi"), ("user", "again"), ("user", "?")))


def test_last_turn_must_be_from_the_user() -> None:
    with pytest.raises(ValidationError, match="last turn must be from the user"):
        Suite.model_validate(_conversation(("user", "hi"), ("assistant", "prefilled answer")))


@pytest.mark.parametrize(
    "turns",
    [
        [],
        [{"role": "system", "content": "be nice"}],
        [{"role": "user", "content": ""}],
        [{"role": "user", "content": "hi", "name": "Laura"}],
    ],
)
def test_invalid_turns_are_rejected(turns: list[dict[str, str]]) -> None:
    case = {"id": "a", "turns": turns, "expect": {"type": "exact", "value": "x"}}
    with pytest.raises(ValidationError):
        Suite.model_validate(_suite(cases=[case]))


def test_empty_input_is_still_rejected() -> None:
    case = {"id": "a", "input": "", "expect": {"type": "exact", "value": "x"}}
    with pytest.raises(ValidationError):
        Suite.model_validate(_suite(cases=[case]))


def test_workshop_example_mixes_conversations_and_single_messages(examples_dir: Path) -> None:
    suite = Suite.from_yaml(examples_dir / "workshop-booking" / "suite.yaml")

    conversations = [c for c in suite.cases if c.turns is not None]
    assert len(conversations) == 5
    assert all(len(c.messages) == 3 for c in conversations)
    assert [c.id for c in suite.cases if c.input is not None] == ["opening-hours"]
