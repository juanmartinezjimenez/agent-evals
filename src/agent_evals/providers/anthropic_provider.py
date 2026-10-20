"""Anthropic provider, using the Messages API.

Requires the optional dependency: `pip install "agent-evals[anthropic]"`.

Current Claude models use adaptive thinking and the SDK no longer accepts a
`temperature` argument, so none is sent. Responses can contain thinking blocks,
which are ignored: the text is every text block, and the tool call (ADR 0008)
is the first tool_use block.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from typing import Any

from agent_evals.models import Case, Tool, ToolCall
from agent_evals.providers.base import (
    Completion,
    ProviderSetupError,
    chat_messages,
    translate_api_error,
)

DEFAULT_MAX_TOKENS = 1024


class AnthropicProvider:
    name = "anthropic"

    def __init__(
        self,
        model: str,
        *,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        client: Any = None,
    ) -> None:
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - depends on the environment
            raise ProviderSetupError(
                'Anthropic support is not installed: pip install "agent-evals[anthropic]"'
            ) from exc

        self.model = model
        self._max_tokens = max_tokens
        self._api_error: type[Exception] = anthropic.APIError
        if client is None:
            try:
                client = anthropic.Anthropic()
            except anthropic.AnthropicError as exc:
                raise ProviderSetupError(f"cannot create Anthropic client: {exc}") from exc
        self._client = client

    def complete(self, system: str, case: Case, tools: Sequence[Tool] = ()) -> Completion:
        params: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self._max_tokens,
            "messages": chat_messages(case),
        }
        if system:
            params["system"] = system
        if tools:
            # ADR 0008: "auto" (forced choice is rejected by several current
            # models and would rule out "no tool" cases), one call at most.
            params["tools"] = [
                {
                    "name": tool.name,
                    **({"description": tool.description} if tool.description else {}),
                    "input_schema": tool.input_schema,
                }
                for tool in tools
            ]
            params["tool_choice"] = {"type": "auto", "disable_parallel_tool_use": True}

        start = time.perf_counter()
        try:
            message = self._client.messages.create(**params)
        except self._api_error as exc:
            raise translate_api_error(exc) from exc
        latency_ms = (time.perf_counter() - start) * 1000

        text = "".join(block.text for block in message.content if block.type == "text")
        usage = getattr(message, "usage", None)
        return Completion(
            text=text,
            latency_ms=latency_ms,
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
            tool_call=next(
                (
                    ToolCall(block.name, block.input)
                    for block in message.content
                    if block.type == "tool_use"
                ),
                None,
            ),
        )
