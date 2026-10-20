"""Replay provider: returns pre-recorded outputs, so runs are deterministic and free.

Recording formats (ADR 0007, ADR 0008):

- Version 3, written by `--record` for suites with tools: like version 2, and
  each case also stores its first `tool_call` (`{name, arguments}` or null).
- Version 2, written by `--record` for suites without tools: `version`, optional
  `provider` and `model`, and `cases` mapping each case id to its `fingerprint`
  and `output`.
- Version 1, written by v0.1-v0.3: a flat mapping of case id -> output. It still
  replays, but changes to prompts or inputs cannot be detected.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from agent_evals.models import Case, Suite, Tool, ToolCall
from agent_evals.providers.base import (
    Completion,
    MissingRecordingError,
    StaleRecordingError,
    chat_messages,
)

RECORDING_VERSION = 2
TOOLS_RECORDING_VERSION = 3
NO_FINGERPRINTS_WARNING = (
    "recording has no fingerprints; changes to prompts or inputs cannot be detected; "
    "re-record with --record"
)


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def fingerprint(system: str, case: Case, tools: Sequence[Tool] = ()) -> str:
    """Hash of exactly what a provider sends for this case: system prompt, messages, tools.

    The same on every platform: line breaks are normalized to `\\n` (so a suite
    saved with CRLF on Windows hashes like the LF copy in CI), then the payload is
    serialized as canonical JSON (sorted keys, fixed separators, UTF-8, no ASCII
    escaping) and hashed with SHA-256.

    Tool definitions are part of what the model sees, so they are included, in
    suite order, but only for suites that declare tools: suites without tools
    keep the fingerprints they had before tools existed (ADR 0008).

    `expect` and `tags` are left out on purpose: changing what counts as correct
    re-scores the same answer and does not need a new recording.
    """
    payload: dict[str, Any] = {
        "system": _normalize_newlines(system),
        "messages": [
            {"role": m["role"], "content": _normalize_newlines(m["content"])}
            for m in chat_messages(case)
        ],
    }
    if tools:
        payload["tools"] = [
            {
                "name": tool.name,
                "description": _normalize_newlines(tool.description),
                "input_schema": tool.input_schema,
            }
            for tool in tools
        ]
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _RecordedCase(_Strict):
    fingerprint: str = Field(pattern=r"^sha256:[0-9a-f]{16}$")
    output: str


class _RecordedToolCall(_Strict):
    name: str
    arguments: Any


class _RecordedToolCase(_RecordedCase):
    tool_call: _RecordedToolCall | None = None


class _RecordingV2(_Strict):
    version: int
    provider: str | None = None
    model: str | None = None
    cases: dict[str, _RecordedCase]


class _RecordingV3(_RecordingV2):
    cases: dict[str, _RecordedToolCase]  # type: ignore[assignment]


class ReplayProvider:
    """Returns pre-recorded outputs (and tool calls) keyed by case id.

    With fingerprints, a case whose system prompt, input or tools changed since
    it was recorded raises `StaleRecordingError` instead of replaying an old answer.
    """

    name = "replay"

    def __init__(
        self,
        outputs: dict[str, str],
        fingerprints: dict[str, str] | None = None,
        *,
        tool_calls: Mapping[str, ToolCall | None] | None = None,
        recorded_provider: str | None = None,
        recorded_model: str | None = None,
    ) -> None:
        self._outputs = outputs
        self._fingerprints = fingerprints
        self._tool_calls = dict(tool_calls or {})
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
            version = data["version"]
            if version == RECORDING_VERSION:
                recording: _RecordingV2 = _RecordingV2.model_validate(data)
                calls: dict[str, ToolCall | None] = {}
            elif version == TOOLS_RECORDING_VERSION:
                v3 = _RecordingV3.model_validate(data)
                recording = v3
                calls = {
                    case_id: ToolCall(c.tool_call.name, c.tool_call.arguments)
                    if c.tool_call
                    else None
                    for case_id, c in v3.cases.items()
                }
            else:
                raise ValueError(f"{path}: unsupported recording version {version}")
            return cls(
                {case_id: c.output for case_id, c in recording.cases.items()},
                {case_id: c.fingerprint for case_id, c in recording.cases.items()},
                tool_calls=calls,
                recorded_provider=recording.provider,
                recorded_model=recording.model,
            )
        if not all(isinstance(v, str) for v in data.values()):
            raise ValueError(f"{path}: expected a mapping of case id -> output string")
        return cls({str(k): v for k, v in data.items()})

    def complete(self, system: str, case: Case, tools: Sequence[Tool] = ()) -> Completion:
        start = time.perf_counter()
        try:
            text = self._outputs[case.id]
        except KeyError:
            raise MissingRecordingError(case.id) from None
        if self._fingerprints is not None and (
            self._fingerprints.get(case.id) != fingerprint(system, case, tools)
        ):
            raise StaleRecordingError(case.id)
        return Completion(
            text=text,
            latency_ms=(time.perf_counter() - start) * 1000,
            tool_call=self._tool_calls.get(case.id),
        )


def write_recording(
    path: Path,
    suite: Suite,
    outputs: Mapping[str, str],
    *,
    tool_calls: Mapping[str, ToolCall | None] | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> None:
    """Write outputs fingerprinted against `suite`: format 3 with tools, else format 2."""
    with_tools = bool(suite.tools)
    calls = tool_calls or {}
    document: dict[str, object] = {
        "version": TOOLS_RECORDING_VERSION if with_tools else RECORDING_VERSION
    }
    if provider:
        document["provider"] = provider
    if model:
        document["model"] = model
    cases: dict[str, object] = {}
    for case in suite.cases:
        if case.id not in outputs:
            continue
        entry: dict[str, object] = {
            "fingerprint": fingerprint(suite.system, case, suite.tools),
            "output": outputs[case.id],
        }
        if with_tools:
            call = calls.get(case.id)
            entry["tool_call"] = (
                {"name": call.name, "arguments": call.arguments} if call is not None else None
            )
        cases[case.id] = entry
    document["cases"] = cases
    header = "# Recorded by agent-evals. Replay with: agent-evals run SUITE --replay THIS_FILE\n"
    body = yaml.safe_dump(document, allow_unicode=True, sort_keys=False, width=1000)
    path.write_text(header + body, encoding="utf-8")
