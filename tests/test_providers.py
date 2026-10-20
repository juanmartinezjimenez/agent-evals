"""Live providers, tested with fake clients shaped like the real SDK responses."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import anthropic
import httpx2
import openai
import pytest

from agent_evals.models import Case
from agent_evals.providers import (
    ProviderCallError,
    ProviderSetupError,
    ReplayProvider,
    make_provider,
    write_recording,
)
from agent_evals.providers.anthropic_provider import DEFAULT_MAX_TOKENS, AnthropicProvider
from agent_evals.providers.openai_provider import OpenAIProvider

CASE = Case.model_validate(
    {"id": "c1", "input": "Where is my parcel?", "expect": {"type": "exact", "value": "shipping"}}
)
CONVERSATION = Case.model_validate(
    {
        "id": "c2",
        "turns": [
            {"role": "user", "content": "My name is Laura. Can I book a repair?"},
            {"role": "assistant", "content": "Tuesday at 10:00 or Thursday at 17:30?"},
            {"role": "user", "content": "Thursday, please."},
        ],
        "expect": {"type": "contains", "values": ["Thursday"]},
    }
)
CONVERSATION_MESSAGES = [
    {"role": "user", "content": "My name is Laura. Can I book a repair?"},
    {"role": "assistant", "content": "Tuesday at 10:00 or Thursday at 17:30?"},
    {"role": "user", "content": "Thursday, please."},
]
REQUEST = httpx2.Request("POST", "https://api.example.test/v1")


def _usage(i: int, o: int) -> SimpleNamespace:
    return SimpleNamespace(input_tokens=i, output_tokens=o)


class _Endpoint:
    """Records the kwargs of each call and returns (or raises) a canned result."""

    def __init__(self, result: Any) -> None:
        self.calls: list[dict[str, Any]] = []
        self._result = result

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


def _openai(result: Any) -> tuple[SimpleNamespace, _Endpoint]:
    endpoint = _Endpoint(result)
    return SimpleNamespace(responses=endpoint), endpoint


def _anthropic(result: Any) -> tuple[SimpleNamespace, _Endpoint]:
    endpoint = _Endpoint(result)
    return SimpleNamespace(messages=endpoint), endpoint


# --- OpenAI -----------------------------------------------------------------


def test_openai_maps_text_and_usage() -> None:
    client, endpoint = _openai(SimpleNamespace(output_text="shipping", usage=_usage(42, 1)))
    completion = OpenAIProvider("gpt-test", client=client).complete("Be brief.", CASE)

    assert completion.text == "shipping"
    assert (completion.input_tokens, completion.output_tokens) == (42, 1)
    assert endpoint.calls == [
        {
            "model": "gpt-test",
            "input": [{"role": "user", "content": "Where is my parcel?"}],
            "instructions": "Be brief.",
        }
    ]


def test_openai_sends_optional_params_only_when_set() -> None:
    client, endpoint = _openai(SimpleNamespace(output_text="x", usage=None))
    OpenAIProvider("gpt-test", client=client).complete("", CASE)
    OpenAIProvider("gpt-test", temperature=0.0, max_output_tokens=16, client=client).complete(
        "", CASE
    )

    assert "instructions" not in endpoint.calls[0]
    assert "temperature" not in endpoint.calls[0]
    assert endpoint.calls[1]["temperature"] == 0.0
    assert endpoint.calls[1]["max_output_tokens"] == 16


def test_openai_without_usage_reports_none() -> None:
    client, _ = _openai(SimpleNamespace(output_text="x", usage=None))
    completion = OpenAIProvider("gpt-test", client=client).complete("", CASE)
    assert completion.input_tokens is None


def test_openai_sends_every_turn_in_order() -> None:
    client, endpoint = _openai(SimpleNamespace(output_text="Thursday", usage=_usage(80, 3)))
    OpenAIProvider("gpt-test", client=client).complete("Book repairs.", CONVERSATION)

    assert endpoint.calls[0]["input"] == CONVERSATION_MESSAGES
    assert endpoint.calls[0]["instructions"] == "Book repairs."


# --- Anthropic --------------------------------------------------------------


def test_anthropic_scores_only_text_blocks() -> None:
    message = SimpleNamespace(
        content=[
            SimpleNamespace(type="thinking", thinking="The user mentions a parcel..."),
            SimpleNamespace(type="text", text="ship"),
            SimpleNamespace(type="text", text="ping"),
        ],
        usage=_usage(30, 5),
    )
    client, endpoint = _anthropic(message)
    completion = AnthropicProvider("claude-test", client=client).complete("Be brief.", CASE)

    assert completion.text == "shipping"
    assert (completion.input_tokens, completion.output_tokens) == (30, 5)
    assert endpoint.calls == [
        {
            "model": "claude-test",
            "max_tokens": DEFAULT_MAX_TOKENS,
            "messages": [{"role": "user", "content": "Where is my parcel?"}],
            "system": "Be brief.",
        }
    ]


def test_anthropic_never_sends_temperature_and_omits_empty_system() -> None:
    client, endpoint = _anthropic(SimpleNamespace(content=[], usage=_usage(1, 0)))
    AnthropicProvider("claude-test", client=client).complete("", CASE)

    assert "temperature" not in endpoint.calls[0]
    assert "system" not in endpoint.calls[0]


def test_anthropic_sends_every_turn_in_order() -> None:
    client, endpoint = _anthropic(SimpleNamespace(content=[], usage=_usage(80, 3)))
    AnthropicProvider("claude-test", client=client).complete("Book repairs.", CONVERSATION)

    assert endpoint.calls[0]["messages"] == CONVERSATION_MESSAGES
    assert endpoint.calls[0]["system"] == "Book repairs."


# --- Error translation ------------------------------------------------------


def _status_error(module: Any, cls: str, status: int) -> Exception:
    error: Exception = getattr(module, cls)(
        "boom", response=httpx2.Response(status, request=REQUEST), body=None
    )
    return error


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (_status_error(openai, "RateLimitError", 429), ProviderCallError),
        (_status_error(openai, "InternalServerError", 500), ProviderCallError),
        (openai.APIConnectionError(request=REQUEST), ProviderCallError),
        (_status_error(openai, "AuthenticationError", 401), ProviderSetupError),
        (_status_error(openai, "NotFoundError", 404), ProviderSetupError),
    ],
)
def test_openai_errors_are_translated(error: Exception, expected: type[Exception]) -> None:
    client, _ = _openai(error)
    with pytest.raises(expected):
        OpenAIProvider("gpt-test", client=client).complete("", CASE)


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (_status_error(anthropic, "RateLimitError", 429), ProviderCallError),
        (anthropic.APIConnectionError(request=REQUEST), ProviderCallError),
        (_status_error(anthropic, "PermissionDeniedError", 403), ProviderSetupError),
        (_status_error(anthropic, "NotFoundError", 404), ProviderSetupError),
    ],
)
def test_anthropic_errors_are_translated(error: Exception, expected: type[Exception]) -> None:
    client, _ = _anthropic(error)
    with pytest.raises(expected):
        AnthropicProvider("claude-test", client=client).complete("", CASE)


def test_programming_errors_are_not_swallowed() -> None:
    client, _ = _openai(TypeError("bug in our code"))
    with pytest.raises(TypeError):
        OpenAIProvider("gpt-test", client=client).complete("", CASE)


def test_missing_api_key_is_a_setup_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    with pytest.raises(ProviderSetupError):
        OpenAIProvider("gpt-test")


# --- Factory and recordings -------------------------------------------------


def test_make_provider_validates_options(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="--replay"):
        make_provider("replay")
    with pytest.raises(ValueError, match="--model"):
        make_provider("anthropic")
    with pytest.raises(ValueError, match="unknown provider"):
        make_provider("llama-on-a-toaster", model="x")


def test_recording_round_trip_keeps_unicode_and_newlines(tmp_path: Path) -> None:
    outputs = {"a": "Lucía → envío", "b": '```json\n{"ok": true}\n```'}
    path = tmp_path / "rec.yaml"
    write_recording(path, outputs)

    replayed = ReplayProvider.from_yaml(path)
    for case_id, text in outputs.items():
        case = Case.model_validate(
            {"id": case_id, "input": "x", "expect": {"type": "exact", "value": "y"}}
        )
        assert replayed.complete("", case).text == text
    assert "Lucía" in path.read_text(encoding="utf-8")  # written as UTF-8, not escaped


def test_replay_answers_a_conversation_by_case_id() -> None:
    provider = ReplayProvider({"c2": "Booked for Thursday, Laura."})
    assert provider.complete("", CONVERSATION).text == "Booked for Thursday, Laura."
