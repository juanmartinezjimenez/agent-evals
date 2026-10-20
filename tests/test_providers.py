"""Live providers, tested with fake clients shaped like the real SDK responses."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import anthropic
import httpx2
import openai
import pytest

from agent_evals.models import Case, Suite
from agent_evals.providers import (
    ProviderCallError,
    ProviderSetupError,
    ReplayProvider,
    StaleRecordingError,
    fingerprint,
    make_provider,
    write_recording,
)
from agent_evals.providers.anthropic_provider import DEFAULT_MAX_TOKENS, AnthropicProvider
from agent_evals.providers.openai_provider import OpenAIProvider
from agent_evals.providers.replay import NO_FINGERPRINTS_WARNING

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


def _suite(*cases: Case, system: str = "Be brief.") -> Suite:
    return Suite(name="demo", system=system, cases=list(cases))


def _case(case_id: str, text: str = "x") -> Case:
    return Case.model_validate(
        {"id": case_id, "input": text, "expect": {"type": "exact", "value": "y"}}
    )


def test_recording_round_trip_keeps_unicode_and_newlines(tmp_path: Path) -> None:
    outputs = {"a": "Lucía → envío", "b": '```json\n{"ok": true}\n```'}
    suite = _suite(_case("a"), _case("b"))
    path = tmp_path / "rec.yaml"
    write_recording(path, suite, outputs, provider="anthropic", model="claude-test")

    replayed = ReplayProvider.from_yaml(path)
    for case in suite.cases:
        assert replayed.complete(suite.system, case).text == outputs[case.id]
    assert replayed.warnings == ()
    assert (replayed.recorded_provider, replayed.recorded_model) == ("anthropic", "claude-test")
    text = path.read_text(encoding="utf-8")
    assert "Lucía" in text  # written as UTF-8, not escaped
    assert "version: 2" in text


# --- Fingerprints and stale recordings (ADR 0007) ---------------------------


def test_fingerprint_covers_system_prompt_and_messages() -> None:
    case = _case("a", "Where is my parcel?")
    base = fingerprint("Be brief.", case)

    assert base.startswith("sha256:")
    assert len(base) == len("sha256:") + 16
    assert fingerprint("Be brief.", case) == base  # deterministic
    assert fingerprint("Be very brief.", case) != base
    assert fingerprint("Be brief.", _case("a", "Where is my order?")) != base


def test_fingerprint_ignores_expectations_tags_and_id() -> None:
    other = Case.model_validate(
        {
            "id": "b",
            "input": "Where is my parcel?",
            "expect": {"type": "contains", "values": ["ship"]},
            "tags": ["new"],
        }
    )
    assert fingerprint("s", _case("a", "Where is my parcel?")) == fingerprint("s", other)


def test_input_and_single_user_turn_have_the_same_fingerprint() -> None:
    as_turn = Case.model_validate(
        {
            "id": "a",
            "turns": [{"role": "user", "content": "Where is my parcel?"}],
            "expect": {"type": "exact", "value": "y"},
        }
    )
    assert fingerprint("s", _case("a", "Where is my parcel?")) == fingerprint("s", as_turn)


def test_changed_input_or_system_prompt_makes_the_replay_stale(tmp_path: Path) -> None:
    path = tmp_path / "rec.yaml"
    write_recording(path, _suite(_case("a", "old question")), {"a": "old answer"})

    replayed = ReplayProvider.from_yaml(path)
    assert replayed.complete("Be brief.", _case("a", "old question")).text == "old answer"
    with pytest.raises(StaleRecordingError):
        replayed.complete("Be brief.", _case("a", "new question"))
    with pytest.raises(StaleRecordingError):
        replayed.complete("A new system prompt.", _case("a", "old question"))


def test_old_flat_recordings_replay_with_a_warning(tmp_path: Path) -> None:
    path = tmp_path / "rec.yaml"
    path.write_text("a: old answer\nversion: also a case id\n", encoding="utf-8")

    replayed = ReplayProvider.from_yaml(path)
    assert replayed.complete("anything", _case("a", "anything")).text == "old answer"
    assert replayed.warnings == (NO_FINGERPRINTS_WARNING,)


@pytest.mark.parametrize(
    "body",
    [
        "version: 3\ncases: {}\n",
        "version: 2\ncases:\n  a: {output: hi}\n",
        "version: 2\ncases:\n  a: {fingerprint: 'md5:123', output: hi}\n",
        "version: 2\ncases: {}\nextra: field\n",
    ],
)
def test_invalid_versioned_recordings_are_rejected(tmp_path: Path, body: str) -> None:
    path = tmp_path / "rec.yaml"
    path.write_text(body, encoding="utf-8")
    with pytest.raises(ValueError):
        ReplayProvider.from_yaml(path)


def test_replay_answers_a_conversation_by_case_id() -> None:
    provider = ReplayProvider({"c2": "Booked for Thursday, Laura."})
    assert provider.complete("", CONVERSATION).text == "Booked for Thursday, Laura."


def test_same_suite_with_lf_and_crlf_has_the_same_fingerprints(
    examples_dir: Path, tmp_path: Path
) -> None:
    text = (examples_dir / "workshop-booking" / "suite.yaml").read_text(encoding="utf-8")
    lf, crlf = tmp_path / "lf.yaml", tmp_path / "crlf.yaml"
    lf.write_bytes(text.replace("\r\n", "\n").encode("utf-8"))
    crlf.write_bytes(text.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8"))
    assert b"\r\n" in crlf.read_bytes()
    assert b"\r\n" not in lf.read_bytes()

    a, b = Suite.from_yaml(lf), Suite.from_yaml(crlf)

    assert [fingerprint(a.system, c) for c in a.cases] == [
        fingerprint(b.system, c) for c in b.cases
    ]


def test_fingerprint_normalizes_line_breaks_in_any_text() -> None:
    # Quoted YAML strings and suites built in code keep \r, so it must not rely on the parser.
    lf = _case("a", "line one\nline two")
    assert fingerprint("a\nb", lf) == fingerprint("a\r\nb", _case("a", "line one\r\nline two"))
    assert fingerprint("a\nb", lf) == fingerprint("a\rb", _case("a", "line one\rline two"))
    assert fingerprint("a\nb", lf) != fingerprint("a b", lf)
