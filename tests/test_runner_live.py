"""Runner behaviour with live-style providers: usage, cost and error handling."""

import pytest

from agent_evals.models import Suite
from agent_evals.pricing import Pricing
from agent_evals.runner import run_suite
from tests.fakes import ProviderCallError, ProviderSetupError, ScriptedProvider

SUITE = Suite.model_validate(
    {
        "name": "mini",
        "threshold": 0.5,
        "cases": [
            {"id": f"c{i}", "input": "x", "expect": {"type": "exact", "value": "yes"}}
            for i in range(1, 4)
        ],
    }
)


def test_tokens_and_cost_are_aggregated() -> None:
    provider = ScriptedProvider({"c1": "yes", "c2": "yes", "c3": "no"}, tokens=(1000, 100))
    run = run_suite(SUITE, provider, pricing=Pricing(input_per_mtok=1.0, output_per_mtok=10.0))

    assert (run.input_tokens, run.output_tokens) == (3000, 300)
    assert run.cost_usd == pytest.approx(0.006)  # 3 calls * (0.001 + 0.001)
    assert run.model == "test-model"


def test_cost_is_unknown_without_pricing() -> None:
    run = run_suite(SUITE, ScriptedProvider({"c1": "yes", "c2": "yes", "c3": "yes"}))
    assert run.input_tokens == 300
    assert run.cost_usd is None


def test_call_error_fails_only_its_case() -> None:
    provider = ScriptedProvider(
        {"c1": "yes", "c2": ProviderCallError("429 slow down"), "c3": "yes"}
    )
    run = run_suite(SUITE, provider)

    assert (run.passed, run.errors, run.total) == (2, 1, 3)
    failed = next(r for r in run.results if r.error)
    assert failed.case_id == "c2"
    assert failed.reason.startswith("provider error:")
    assert run.input_tokens == 200  # errored calls are not counted


def test_setup_error_aborts_the_run() -> None:
    provider = ScriptedProvider({"c1": ProviderSetupError("401 bad key"), "c2": "yes", "c3": "yes"})
    with pytest.raises(ProviderSetupError):
        run_suite(SUITE, provider)


def test_p95_latency() -> None:
    answers: dict[str, str | Exception] = {"c1": "yes", "c2": "yes", "c3": "y" * 40}
    run = run_suite(SUITE, ScriptedProvider(answers))
    assert run.p95_latency_ms > run.mean_latency_ms
