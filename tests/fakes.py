"""A scriptable live-style provider for runner and CLI tests."""

from __future__ import annotations

from agent_evals.models import Case
from agent_evals.providers import Completion, ProviderCallError, ProviderSetupError


class ScriptedProvider:
    """Answers from a dict; a value that is an exception is raised instead."""

    name = "scripted"

    def __init__(
        self,
        answers: dict[str, str | Exception],
        *,
        model: str = "test-model",
        tokens: tuple[int, int] = (100, 10),
    ) -> None:
        self.model = model
        self._answers = answers
        self._tokens = tokens

    def complete(self, system: str, case: Case) -> Completion:
        answer = self._answers[case.id]
        if isinstance(answer, Exception):
            raise answer
        return Completion(
            text=answer,
            latency_ms=float(len(answer)),
            input_tokens=self._tokens[0],
            output_tokens=self._tokens[1],
        )


__all__ = ["ProviderCallError", "ProviderSetupError", "ScriptedProvider"]
