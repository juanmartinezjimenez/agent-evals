"""OpenAI provider, using the Responses API.

Requires the optional dependency: `pip install "agent-evals[openai]"`.
"""

from __future__ import annotations

import time
from typing import Any

from agent_evals.models import Case
from agent_evals.providers.base import Completion, ProviderSetupError, translate_api_error


class OpenAIProvider:
    name = "openai"

    def __init__(
        self,
        model: str,
        *,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
        client: Any = None,
    ) -> None:
        try:
            import openai
        except ImportError as exc:  # pragma: no cover - depends on the environment
            raise ProviderSetupError(
                'OpenAI support is not installed: pip install "agent-evals[openai]"'
            ) from exc

        self.model = model
        self._temperature = temperature
        self._max_output_tokens = max_output_tokens
        self._api_error: type[Exception] = openai.APIError
        if client is None:
            try:
                client = openai.OpenAI()
            except openai.OpenAIError as exc:
                raise ProviderSetupError(f"cannot create OpenAI client: {exc}") from exc
        self._client = client

    def complete(self, system: str, case: Case) -> Completion:
        params: dict[str, Any] = {"model": self.model, "input": case.input}
        if system:
            params["instructions"] = system
        if self._temperature is not None:
            params["temperature"] = self._temperature
        if self._max_output_tokens is not None:
            params["max_output_tokens"] = self._max_output_tokens

        start = time.perf_counter()
        try:
            response = self._client.responses.create(**params)
        except self._api_error as exc:
            raise translate_api_error(exc) from exc
        latency_ms = (time.perf_counter() - start) * 1000

        usage = getattr(response, "usage", None)
        return Completion(
            text=response.output_text,
            latency_ms=latency_ms,
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
        )
