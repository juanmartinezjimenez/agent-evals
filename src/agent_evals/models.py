"""Suite and case definitions, loaded from YAML and validated with Pydantic."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal

import jsonschema
import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ExactMatch(_Strict):
    """Output must equal `value` (after optional normalisation)."""

    type: Literal["exact"]
    value: str
    case_sensitive: bool = False


class Contains(_Strict):
    """Output must contain every string in `values`."""

    type: Literal["contains"]
    values: list[str] = Field(min_length=1)
    case_sensitive: bool = False


class Regex(_Strict):
    """Output must match the regular expression `pattern`."""

    type: Literal["regex"]
    pattern: str


class JsonSchema(_Strict):
    """Output must be valid JSON that conforms to `schema`.

    `fields` optionally pins expected values for top-level keys.
    """

    type: Literal["json_schema"]
    json_schema: dict[str, Any] = Field(alias="schema")
    fields: dict[str, Any] = Field(default_factory=dict)


def _check_matchers(value: Any, where: str = "arguments") -> None:
    """`{$regex: pattern}` is the only matcher; it must be alone and compile."""
    if isinstance(value, dict):
        if "$regex" in value:
            if len(value) != 1 or not isinstance(value["$regex"], str):
                raise ValueError(f"{where}: $regex must be the only key, with a string pattern")
            try:
                re.compile(value["$regex"])
            except re.error as exc:
                raise ValueError(f"{where}: invalid $regex: {exc}") from None
            return
        for key, item in value.items():
            _check_matchers(item, f"{where}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _check_matchers(item, f"{where}[{index}]")


class ToolCallMatch(_Strict):
    """The first tool call must be to `tool`, with matching `arguments` (ADR 0008)."""

    type: Literal["tool_call"]
    tool: str
    arguments: dict[str, Any] | None = None
    match: Literal["subset", "exact"] = "subset"

    @field_validator("arguments")
    @classmethod
    def _valid_matchers(cls, arguments: dict[str, Any] | None) -> dict[str, Any] | None:
        _check_matchers(arguments)
        return arguments


class NoToolCall(_Strict):
    """The model must answer without calling any tool."""

    type: Literal["no_tool_call"]


class NoCallTo(_Strict):
    """The model must not call any of `tools`; text or another tool is fine."""

    type: Literal["no_call_to"]
    tools: list[str] = Field(min_length=1)


TextExpectation = ExactMatch | Contains | Regex | JsonSchema
ToolExpectation = ToolCallMatch | NoToolCall | NoCallTo
TOOL_EXPECTATIONS = (ToolCallMatch, NoToolCall, NoCallTo)
Expectation = Annotated[TextExpectation | ToolExpectation, Field(discriminator="type")]


@dataclass(frozen=True, slots=True)
class ToolCall:
    """A tool call the model asked for. It is scored, never executed."""

    name: str
    arguments: Any  # a JSON object when the model produced valid JSON


def _unknown_argument_keys(arguments: Any, schema: dict[str, Any], where: str) -> list[str]:
    """Expected argument keys that the tool's schema does not declare."""
    if not isinstance(arguments, dict) or "$regex" in arguments:
        return []
    properties = schema.get("properties", {})
    unknown: list[str] = []
    for key, value in arguments.items():
        path = f"{where}.{key}" if where else key
        if key not in properties:
            unknown.append(path)
        elif isinstance(properties[key], dict):
            unknown += _unknown_argument_keys(value, properties[key], path)
    return unknown


class Turn(_Strict):
    """One message of a scripted conversation."""

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1)


class Case(_Strict):
    """One input sent to the model and what a correct answer looks like.

    The input is either a single message (`input`) or a scripted conversation
    (`turns`) whose last turn is from the user. Only the model's answer to that
    last turn is scored (ADR 0006).
    """

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")
    input: str | None = Field(default=None, min_length=1)
    turns: list[Turn] | None = Field(default=None, min_length=1)
    # One expectation, or a list where every one must pass (ADR 0008).
    expect: Expectation | Annotated[list[Expectation], Field(min_length=1)]
    tags: list[str] = Field(default_factory=list)

    @property
    def expectations(self) -> tuple[Expectation, ...]:
        return tuple(self.expect) if isinstance(self.expect, list) else (self.expect,)

    @model_validator(mode="after")
    def _valid_conversation(self) -> Case:
        if (self.input is None) == (self.turns is None):
            raise ValueError("a case needs exactly one of 'input' or 'turns'")
        for number, turn in enumerate(self.turns or [], start=1):
            expected = "user" if number % 2 else "assistant"
            if turn.role != expected:
                raise ValueError(
                    f"turn {number} must be from the {expected}: "
                    "turns start with the user and alternate roles"
                )
        if self.turns and self.turns[-1].role != "user":
            raise ValueError("the last turn must be from the user")
        return self

    @property
    def messages(self) -> tuple[Turn, ...]:
        """The conversation sent to the model; `input` is a single user turn."""
        if self.turns is not None:
            return tuple(self.turns)
        return (Turn(role="user", content=self.input or ""),)


class Tool(_Strict):
    """A tool the model may call, declared as JSON Schema (ADR 0008).

    The name pattern is the intersection of what OpenAI (64 characters) and
    Anthropic (128) accept.
    """

    name: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    description: str = ""
    input_schema: dict[str, Any]

    @field_validator("input_schema")
    @classmethod
    def _valid_schema(cls, schema: dict[str, Any]) -> dict[str, Any]:
        if schema.get("type") != "object":
            raise ValueError("input_schema must be a JSON Schema with type: object")
        try:
            jsonschema.Draft202012Validator.check_schema(schema)
        except jsonschema.SchemaError as exc:
            raise ValueError(f"input_schema is not a valid JSON Schema: {exc.message}") from None
        return schema


def _duplicates(values: list[str]) -> list[str]:
    return sorted(value for value, n in Counter(values).items() if n > 1)


class Suite(_Strict):
    """A named set of cases with a shared system prompt and pass threshold."""

    name: str
    description: str = ""
    system: str = ""
    threshold: float = Field(default=1.0, ge=0.0, le=1.0)
    tools: list[Tool] = Field(default_factory=list)
    cases: list[Case] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_ids(self) -> Suite:
        duplicates = _duplicates([c.id for c in self.cases])
        if duplicates:
            raise ValueError(f"duplicate case ids: {duplicates}")
        duplicate_tools = _duplicates([t.name for t in self.tools])
        if duplicate_tools:
            raise ValueError(f"duplicate tool names: {duplicate_tools}")
        return self

    @model_validator(mode="after")
    def _valid_tool_expectations(self) -> Suite:
        """ADR 0008 rules 3-5: known tools, known argument keys, no contradictions."""
        for case in self.cases:
            kinds = [type(e) for e in case.expectations]
            if NoToolCall in kinds and ToolCallMatch in kinds:
                raise ValueError(f"case {case.id}: no_tool_call and tool_call can never both pass")
            for expect in case.expectations:
                if not isinstance(expect, TOOL_EXPECTATIONS):
                    continue
                if not self.tools:
                    raise ValueError(f"case {case.id}: tool expectations need tools in the suite")
                if isinstance(expect, ToolCallMatch):
                    tool = self.tool_named(expect.tool)
                    if tool is None:
                        raise ValueError(f"case {case.id}: unknown tool {expect.tool!r}")
                    unknown = _unknown_argument_keys(expect.arguments, tool.input_schema, "")
                    if unknown:
                        raise ValueError(
                            f"case {case.id}: {expect.tool} has no argument {', '.join(unknown)}"
                        )
                elif isinstance(expect, NoCallTo):
                    missing = [name for name in expect.tools if self.tool_named(name) is None]
                    if missing:
                        raise ValueError(f"case {case.id}: unknown tools {missing}")
        return self

    def tool_named(self, name: str) -> Tool | None:
        return next((tool for tool in self.tools if tool.name == name), None)

    @classmethod
    def from_yaml(cls, path: Path) -> Suite:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return cls.model_validate(data)
