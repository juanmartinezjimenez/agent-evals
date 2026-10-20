"""A scriptable live-style provider for runner and CLI tests."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from agent_evals.models import Case, Tool, ToolCall
from agent_evals.providers import Completion, ProviderCallError, ProviderSetupError

# A scripted answer: text, a tool call, both (text, call), or an exception to raise.
Scripted = str | ToolCall | tuple[str, ToolCall] | Exception


class ScriptedProvider:
    """Answers from a dict; a value that is an exception is raised instead."""

    name = "scripted"

    def __init__(
        self,
        answers: Mapping[str, Scripted],
        *,
        model: str = "test-model",
        tokens: tuple[int, int] = (100, 10),
    ) -> None:
        self.model = model
        self._answers = answers
        self._tokens = tokens
        self.seen_tools: list[tuple[str, ...]] = []

    def complete(self, system: str, case: Case, tools: Sequence[Tool] = ()) -> Completion:
        self.seen_tools.append(tuple(tool.name for tool in tools))
        answer = self._answers[case.id]
        if isinstance(answer, Exception):
            raise answer
        if isinstance(answer, ToolCall):
            text, call = "", answer
        elif isinstance(answer, tuple):
            text, call = answer
        else:
            text, call = answer, None
        return Completion(
            text=text,
            latency_ms=float(len(text) + 1),
            input_tokens=self._tokens[0],
            output_tokens=self._tokens[1],
            tool_call=call,
        )


__all__ = ["ProviderCallError", "ProviderSetupError", "ScriptedProvider", "ToolCall"]
