import pytest

from agent_evals.pricing import Pricing


def test_cost_per_call() -> None:
    pricing = Pricing(input_per_mtok=1.0, output_per_mtok=5.0)
    assert pricing.cost(1_000_000, 0) == pytest.approx(1.0)
    assert pricing.cost(200, 10) == pytest.approx(0.00025)


def test_unknown_usage_gives_unknown_cost() -> None:
    assert Pricing(1.0, 5.0).cost(None, 10) is None


def test_negative_prices_are_rejected() -> None:
    with pytest.raises(ValueError):
        Pricing(-1.0, 5.0)
