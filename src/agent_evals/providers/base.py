"""Provider protocol and the errors providers raise."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from agent_evals.models import Case, Tool, ToolCall


@dataclass(frozen=True, slots=True)
class Completion:
    text: str
    latency_ms: float
    input_tokens: int | None = None
    output_tokens: int | None = None
    tool_call: ToolCall | None = None  # the first call, never executed (ADR 0008)


class Provider(Protocol):
    """Answers the last user turn of `case.messages`; never read `case.input` directly.

    `tools` are the suite's tool definitions; a provider offers them to the model
    and returns its first call, if any. Suites without tools pass none.
    """

    name: str

    def complete(self, system: str, case: Case, tools: Sequence[Tool] = ()) -> Completion: ...


def chat_messages(case: Case) -> list[dict[str, str]]:
    """The case's conversation as `{"role", "content"}` dicts, accepted by both live APIs."""
    return [{"role": turn.role, "content": turn.content} for turn in case.messages]


class ProviderSetupError(RuntimeError):
    """The provider cannot run at all: missing SDK, missing key, bad model, no permission.

    Raised before or during the first call; the run is aborted.
    """


class ProviderCallError(RuntimeError):
    """A single call failed (rate limit, timeout, server error). The case is marked as failed."""


class MissingRecordingError(KeyError):
    """A case has no recorded output in the replay file."""


STALE_REASON = (
    "stale recording: the system prompt or input changed since this case was recorded; "
    "re-record with --record"
)


class StaleRecordingError(Exception):
    """The recorded output answers a different system prompt or input (ADR 0007).

    The case is marked as failed and stale; the run continues so every stale case is listed.
    """


# HTTP statuses that mean every other call would fail the same way.
FATAL_STATUSES = frozenset({401, 403, 404})


def translate_api_error(exc: Exception) -> ProviderSetupError | ProviderCallError:
    """Map an SDK error to a setup error (abort) or a call error (fail one case)."""
    status = getattr(exc, "status_code", None)
    message = f"{type(exc).__name__}: {exc}"
    if status in FATAL_STATUSES:
        return ProviderSetupError(message)
    return ProviderCallError(message)
