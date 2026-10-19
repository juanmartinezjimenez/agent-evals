"""Model providers.

v0.1 ships a `ReplayProvider` that returns recorded outputs. It makes runs
deterministic and free, so the whole pipeline can be tested in CI without an
API key. Real providers (OpenAI, Anthropic) arrive in v0.2 behind the same
`Provider` protocol.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import yaml

from agent_evals.models import Case


@dataclass(frozen=True, slots=True)
class Completion:
    text: str
    latency_ms: float


class Provider(Protocol):
    name: str

    def complete(self, system: str, case: Case) -> Completion: ...


class MissingRecordingError(KeyError):
    """A case has no recorded output in the replay file."""


class ReplayProvider:
    """Returns pre-recorded outputs keyed by case id."""

    name = "replay"

    def __init__(self, recordings: dict[str, str]) -> None:
        self._recordings = recordings

    @classmethod
    def from_yaml(cls, path: Path) -> ReplayProvider:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict) or not all(isinstance(v, str) for v in data.values()):
            raise ValueError(f"{path}: expected a mapping of case id -> output string")
        return cls({str(k): v for k, v in data.items()})

    def complete(self, system: str, case: Case) -> Completion:
        start = time.perf_counter()
        try:
            text = self._recordings[case.id]
        except KeyError:
            raise MissingRecordingError(case.id) from None
        return Completion(text=text, latency_ms=(time.perf_counter() - start) * 1000)
