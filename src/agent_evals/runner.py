"""Run a suite against a provider and aggregate the results."""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean

from agent_evals.models import Suite
from agent_evals.providers import Provider
from agent_evals.scorers import score


@dataclass(frozen=True, slots=True)
class CaseResult:
    case_id: str
    passed: bool
    reason: str
    output: str
    latency_ms: float
    tags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RunResult:
    suite: str
    provider: str
    threshold: float
    results: tuple[CaseResult, ...] = field(default_factory=tuple)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> int:
        return sum(r.passed for r in self.results)

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total else 0.0

    @property
    def mean_latency_ms(self) -> float:
        return mean(r.latency_ms for r in self.results) if self.results else 0.0

    @property
    def ok(self) -> bool:
        return self.pass_rate >= self.threshold

    def by_tag(self) -> dict[str, tuple[int, int]]:
        """Return {tag: (passed, total)} for every tag used in the suite."""
        stats: dict[str, list[int]] = {}
        for r in self.results:
            for tag in r.tags:
                passed_total = stats.setdefault(tag, [0, 0])
                passed_total[0] += r.passed
                passed_total[1] += 1
        return {tag: (p, t) for tag, (p, t) in sorted(stats.items())}


def run_suite(suite: Suite, provider: Provider, threshold: float | None = None) -> RunResult:
    results = []
    for case in suite.cases:
        completion = provider.complete(suite.system, case)
        verdict = score(case.expect, completion.text)
        results.append(
            CaseResult(
                case_id=case.id,
                passed=verdict.passed,
                reason=verdict.reason,
                output=completion.text,
                latency_ms=completion.latency_ms,
                tags=tuple(case.tags),
            )
        )
    return RunResult(
        suite=suite.name,
        provider=provider.name,
        threshold=suite.threshold if threshold is None else threshold,
        results=tuple(results),
    )
