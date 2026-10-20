"""Suite and case definitions, loaded from YAML and validated with Pydantic."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


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


Expectation = Annotated[ExactMatch | Contains | Regex | JsonSchema, Field(discriminator="type")]


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
    expect: Expectation
    tags: list[str] = Field(default_factory=list)

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


class Suite(_Strict):
    """A named set of cases with a shared system prompt and pass threshold."""

    name: str
    description: str = ""
    system: str = ""
    threshold: float = Field(default=1.0, ge=0.0, le=1.0)
    cases: list[Case] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_ids(self) -> Suite:
        counts = Counter(c.id for c in self.cases)
        duplicates = sorted(case_id for case_id, n in counts.items() if n > 1)
        if duplicates:
            raise ValueError(f"duplicate case ids: {duplicates}")
        return self

    @classmethod
    def from_yaml(cls, path: Path) -> Suite:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return cls.model_validate(data)
