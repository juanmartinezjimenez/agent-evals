"""Token pricing, always supplied by the user (see ADR 0004)."""

from __future__ import annotations

from dataclasses import dataclass

PER_MILLION = 1_000_000


@dataclass(frozen=True, slots=True)
class Pricing:
    """USD per million tokens, as published by the provider."""

    input_per_mtok: float
    output_per_mtok: float

    def __post_init__(self) -> None:
        if self.input_per_mtok < 0 or self.output_per_mtok < 0:
            raise ValueError("prices cannot be negative")

    def cost(self, input_tokens: int | None, output_tokens: int | None) -> float | None:
        """Cost of one call in USD, or None if the provider did not report usage."""
        if input_tokens is None or output_tokens is None:
            return None
        return (
            input_tokens * self.input_per_mtok + output_tokens * self.output_per_mtok
        ) / PER_MILLION
