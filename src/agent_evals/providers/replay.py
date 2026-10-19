"""Replay provider: returns pre-recorded outputs, so runs are deterministic and free."""

from __future__ import annotations

import time
from pathlib import Path

import yaml

from agent_evals.models import Case
from agent_evals.providers.base import Completion, MissingRecordingError


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


def write_recording(path: Path, outputs: dict[str, str]) -> None:
    """Write outputs in the format ReplayProvider reads."""
    header = "# Recorded by agent-evals. Replay with: agent-evals run SUITE --replay THIS_FILE\n"
    body = yaml.safe_dump(outputs, allow_unicode=True, sort_keys=False, width=1000)
    path.write_text(header + body, encoding="utf-8")
