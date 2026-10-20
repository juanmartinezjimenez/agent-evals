"""Run a suite against a provider and aggregate the results."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from statistics import mean, quantiles

from agent_evals.models import Suite
from agent_evals.pricing import Pricing
from agent_evals.providers import STALE_REASON, Provider, ProviderCallError, StaleRecordingError
from agent_evals.scorers import score


@dataclass(frozen=True, slots=True)
class CaseResult:
    case_id: str
    passed: bool
    reason: str
    output: str
    latency_ms: float
    tags: tuple[str, ...] = ()
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None
    error: bool = False
    stale: bool = False

    @property
    def measured(self) -> bool:
        """Whether latency and usage come from a real answer (not an error or a stale replay)."""
        return not (self.error or self.stale)


@dataclass(frozen=True, slots=True)
class RunResult:
    suite: str
    provider: str
    threshold: float
    results: tuple[CaseResult, ...] = field(default_factory=tuple)
    model: str | None = None
    warnings: tuple[str, ...] = ()

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> int:
        return sum(r.passed for r in self.results)

    @property
    def errors(self) -> int:
        return sum(r.error for r in self.results)

    @property
    def stale(self) -> int:
        return sum(r.stale for r in self.results)

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total else 0.0

    @property
    def ok(self) -> bool:
        return self.pass_rate >= self.threshold

    @property
    def mean_latency_ms(self) -> float:
        timed = [r.latency_ms for r in self.results if r.measured]
        return mean(timed) if timed else 0.0

    @property
    def p95_latency_ms(self) -> float:
        timed = sorted(r.latency_ms for r in self.results if r.measured)
        if len(timed) < 2:
            return timed[0] if timed else 0.0
        return quantiles(timed, n=20, method="inclusive")[-1]

    @property
    def input_tokens(self) -> int | None:
        return _sum_or_none(r.input_tokens for r in self.results if r.measured)

    @property
    def output_tokens(self) -> int | None:
        return _sum_or_none(r.output_tokens for r in self.results if r.measured)

    @property
    def cost_usd(self) -> float | None:
        costs = [r.cost_usd for r in self.results if r.measured]
        if not costs or any(c is None for c in costs):
            return None
        return sum(c for c in costs if c is not None)

    def by_tag(self) -> dict[str, tuple[int, int]]:
        """Return {tag: (passed, total)} for every tag used in the suite."""
        stats: dict[str, list[int]] = {}
        for r in self.results:
            for tag in r.tags:
                passed_total = stats.setdefault(tag, [0, 0])
                passed_total[0] += r.passed
                passed_total[1] += 1
        return {tag: (p, t) for tag, (p, t) in sorted(stats.items())}


def _sum_or_none(values: Iterable[int | None]) -> int | None:
    """Sum the values, or None if the provider reported no usage for any of them."""
    items = list(values)
    if not items or any(v is None for v in items):
        return None
    return sum(v for v in items if v is not None)


def run_suite(
    suite: Suite,
    provider: Provider,
    threshold: float | None = None,
    pricing: Pricing | None = None,
) -> RunResult:
    """Run every case in order.

    A `ProviderCallError` fails only its case; a `ProviderSetupError` propagates
    and aborts the run, because every other case would fail the same way. A
    `StaleRecordingError` fails its case as stale, so every stale case is listed.
    """
    results = []
    for case in suite.cases:
        tags = tuple(case.tags)
        try:
            completion = provider.complete(suite.system, case)
        except ProviderCallError as exc:
            results.append(
                CaseResult(
                    case_id=case.id,
                    passed=False,
                    reason=f"provider error: {exc}",
                    output="",
                    latency_ms=0.0,
                    tags=tags,
                    error=True,
                )
            )
            continue
        except StaleRecordingError:
            results.append(
                CaseResult(
                    case_id=case.id,
                    passed=False,
                    reason=STALE_REASON,
                    output="",
                    latency_ms=0.0,
                    tags=tags,
                    stale=True,
                )
            )
            continue

        verdict = score(case.expect, completion.text)
        results.append(
            CaseResult(
                case_id=case.id,
                passed=verdict.passed,
                reason=verdict.reason,
                output=completion.text,
                latency_ms=completion.latency_ms,
                tags=tags,
                input_tokens=completion.input_tokens,
                output_tokens=completion.output_tokens,
                cost_usd=(
                    pricing.cost(completion.input_tokens, completion.output_tokens)
                    if pricing
                    else None
                ),
            )
        )
    return RunResult(
        suite=suite.name,
        provider=provider.name,
        threshold=suite.threshold if threshold is None else threshold,
        results=tuple(results),
        model=getattr(provider, "model", None),
        warnings=tuple(getattr(provider, "warnings", ())),
    )
