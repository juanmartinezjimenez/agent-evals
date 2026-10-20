"""Replay provider: returns pre-recorded outputs, so runs are deterministic and free.

Recording formats (ADR 0007):

- Version 2, written by `--record`: `version`, optional `provider` and `model`, and
  `cases` mapping each case id to its `fingerprint` and `output`.
- Version 1, written by v0.1-v0.3: a flat mapping of case id -> output. It still
  replays, but changes to prompts or inputs cannot be detected.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from agent_evals.models import Case, Suite
from agent_evals.providers.base import (
    Completion,
    MissingRecordingError,
    StaleRecordingError,
    chat_messages,
)

RECORDING_VERSION = 2
NO_FINGERPRINTS_WARNING = (
    "recording has no fingerprints; changes to prompts or inputs cannot be detected; "
    "re-record with --record"
)


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def fingerprint(system: str, case: Case) -> str:
    """Hash of exactly what a provider sends for this case: system prompt and messages.

    The same on every platform: line breaks are normalized to `\\n` (so a suite
    saved with CRLF on Windows hashes like the LF copy in CI), then the payload is
    serialized as canonical JSON (sorted keys, fixed separators, UTF-8, no ASCII
    escaping) and hashed with SHA-256.

    `expect` and `tags` are left out on purpose: changing what counts as correct
    re-scores the same answer and does not need a new recording.
    """
    payload = {
        "system": _normalize_newlines(system),
        "messages": [
            {"role": m["role"], "content": _normalize_newlines(m["content"])}
            for m in chat_messages(case)
        ],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


class _RecordedCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    fingerprint: str = Field(pattern=r"^sha256:[0-9a-f]{16}$")
    output: str


class _RecordingV2(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: int
    provider: str | None = None
    model: str | None = None
    cases: dict[str, _RecordedCase]


class ReplayProvider:
    """Returns pre-recorded outputs keyed by case id.

    With fingerprints, a case whose system prompt or input changed since it was
    recorded raises `StaleRecordingError` instead of replaying an old answer.
    """

    name = "replay"

    def __init__(
        self,
        outputs: dict[str, str],
        fingerprints: dict[str, str] | None = None,
        *,
        recorded_provider: str | None = None,
        recorded_model: str | None = None,
    ) -> None:
        self._outputs = outputs
        self._fingerprints = fingerprints
        self.recorded_provider = recorded_provider
        self.recorded_model = recorded_model

    @property
    def warnings(self) -> tuple[str, ...]:
        return () if self._fingerprints is not None else (NO_FINGERPRINTS_WARNING,)

    @classmethod
    def from_yaml(cls, path: Path) -> ReplayProvider:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise ValueError(f"{path}: expected a recording mapping")
        # Version 1 values are all strings, so an int `version` with a `cases`
        # mapping can only be version 2 or later.
        if isinstance(data.get("version"), int) and isinstance(data.get("cases"), dict):
            recording = _RecordingV2.model_validate(data)
            if recording.version != RECORDING_VERSION:
                raise ValueError(f"{path}: unsupported recording version {recording.version}")
            return cls(
                {case_id: c.output for case_id, c in recording.cases.items()},
                {case_id: c.fingerprint for case_id, c in recording.cases.items()},
                recorded_provider=recording.provider,
                recorded_model=recording.model,
            )
        if not all(isinstance(v, str) for v in data.values()):
            raise ValueError(f"{path}: expected a mapping of case id -> output string")
        return cls({str(k): v for k, v in data.items()})

    def complete(self, system: str, case: Case) -> Completion:
        start = time.perf_counter()
        try:
            text = self._outputs[case.id]
        except KeyError:
            raise MissingRecordingError(case.id) from None
        if self._fingerprints is not None and (
            self._fingerprints.get(case.id) != fingerprint(system, case)
        ):
            raise StaleRecordingError(case.id)
        return Completion(text=text, latency_ms=(time.perf_counter() - start) * 1000)


def write_recording(
    path: Path,
    suite: Suite,
    outputs: dict[str, str],
    *,
    provider: str | None = None,
    model: str | None = None,
) -> None:
    """Write outputs in format version 2, fingerprinted against `suite`."""
    document: dict[str, object] = {"version": RECORDING_VERSION}
    if provider:
        document["provider"] = provider
    if model:
        document["model"] = model
    document["cases"] = {
        case.id: {"fingerprint": fingerprint(suite.system, case), "output": outputs[case.id]}
        for case in suite.cases
        if case.id in outputs
    }
    header = "# Recorded by agent-evals. Replay with: agent-evals run SUITE --replay THIS_FILE\n"
    body = yaml.safe_dump(document, allow_unicode=True, sort_keys=False, width=1000)
    path.write_text(header + body, encoding="utf-8")
