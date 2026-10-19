"""Model providers behind a single `Provider` protocol."""

from __future__ import annotations

from pathlib import Path

from agent_evals.providers.base import (
    Completion,
    MissingRecordingError,
    Provider,
    ProviderCallError,
    ProviderSetupError,
)
from agent_evals.providers.replay import ReplayProvider, write_recording

LIVE_PROVIDERS = ("openai", "anthropic")
PROVIDERS = ("replay", *LIVE_PROVIDERS)

__all__ = [
    "LIVE_PROVIDERS",
    "PROVIDERS",
    "Completion",
    "MissingRecordingError",
    "Provider",
    "ProviderCallError",
    "ProviderSetupError",
    "ReplayProvider",
    "make_provider",
    "write_recording",
]


def make_provider(name: str, *, model: str | None = None, replay: Path | None = None) -> Provider:
    """Build a provider from CLI-style options."""
    if name == "replay":
        if replay is None:
            raise ValueError("the replay provider needs --replay FILE")
        return ReplayProvider.from_yaml(replay)
    if name not in LIVE_PROVIDERS:
        raise ValueError(f"unknown provider {name!r}; choose one of {', '.join(PROVIDERS)}")
    if not model:
        raise ValueError(f"the {name} provider needs --model")
    if name == "openai":
        from agent_evals.providers.openai_provider import OpenAIProvider

        return OpenAIProvider(model)
    from agent_evals.providers.anthropic_provider import AnthropicProvider

    return AnthropicProvider(model)
