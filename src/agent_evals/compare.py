"""Compare two JSON run reports case by case to detect regressions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict


class _Report(BaseModel):
    # Reports may gain fields in later versions; ignore what this version does not use.
    model_config = ConfigDict(extra="ignore", frozen=True)


class CaseReport(_Report):
    case_id: str
    passed: bool
    reason: str


class RunReport(_Report):
    """The parts of a `run --json` report that a comparison needs."""

    suite: str
    provider: str
    model: str | None = None
    passed: int
    total: int
    pass_rate: float
    mean_latency_ms: float
    p95_latency_ms: float
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None
    results: list[CaseReport]

    @property
    def target(self) -> str:
        return f"{self.provider}:{self.model}" if self.model else self.provider

    @classmethod
    def from_json(cls, path: Path) -> RunReport:
        return cls.model_validate_json(path.read_text(encoding="utf-8"))


@dataclass(frozen=True, slots=True)
class CaseChange:
    case_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class Comparison:
    base: RunReport
    head: RunReport
    regressions: tuple[CaseChange, ...]  # passed in base, fails in head; reason from head
    fixes: tuple[CaseChange, ...]  # failed in base, passes in head; reason from base
    added: tuple[CaseReport, ...]
    removed: tuple[CaseReport, ...]

    @property
    def ok(self) -> bool:
        return not self.regressions


def compare(base: RunReport, head: RunReport) -> Comparison:
    """Match cases by id. Only regressions make the comparison fail.

    Raises ValueError when the reports belong to different suites.
    """
    if base.suite != head.suite:
        raise ValueError(f"reports are for different suites: {base.suite!r} vs {head.suite!r}")

    before = {r.case_id: r for r in base.results}
    after = {r.case_id: r for r in head.results}
    common = [r for r in head.results if r.case_id in before]

    return Comparison(
        base=base,
        head=head,
        regressions=tuple(
            CaseChange(r.case_id, r.reason)
            for r in common
            if before[r.case_id].passed and not r.passed
        ),
        fixes=tuple(
            CaseChange(r.case_id, before[r.case_id].reason)
            for r in common
            if not before[r.case_id].passed and r.passed
        ),
        added=tuple(r for r in head.results if r.case_id not in before),
        removed=tuple(r for r in base.results if r.case_id not in after),
    )
