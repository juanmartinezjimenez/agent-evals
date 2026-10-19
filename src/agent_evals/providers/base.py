"""Provider protocol and the errors providers raise."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from agent_evals.models import Case


@dataclass(frozen=True, slots=True)
class Completion:
    text: str
    latency_ms: float
    input_tokens: int | None = None
    output_tokens: int | None = None


class Provider(Protocol):
    name: str

    def complete(self, system: str, case: Case) -> Completion: ...


class ProviderSetupError(RuntimeError):
    """The provider cannot run at all: missing SDK, missing key, bad model, no permission.

    Raised before or during the first call; the run is aborted.
    """


class ProviderCallError(RuntimeError):
    """A single call failed (rate limit, timeout, server error). The case is marked as failed."""


class MissingRecordingError(KeyError):
    """A case has no recorded output in the replay file."""


# HTTP statuses that mean every other call would fail the same way.
FATAL_STATUSES = frozenset({401, 403, 404})


def translate_api_error(exc: Exception) -> ProviderSetupError | ProviderCallError:
    """Map an SDK error to a setup error (abort) or a call error (fail one case)."""
    status = getattr(exc, "status_code", None)
    message = f"{type(exc).__name__}: {exc}"
    if status in FATAL_STATUSES:
        return ProviderSetupError(message)
    return ProviderCallError(message)
