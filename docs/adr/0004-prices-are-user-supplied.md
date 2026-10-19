# 0004. Token prices are supplied by the user

- Status: accepted
- Date: 2026-10-19

## Context

Cost per run is one of the numbers that decides between two models. Providers
change prices, add tiers (batch, cached input, long context) and release new
models several times a year. A price table inside the package would be wrong
within months, and a wrong cost is worse than no cost because it looks
authoritative.

## Decision

The tool records token usage for every call, as reported by the provider. Cost
is computed only when the user passes `--price-input` and `--price-output` (USD
per million tokens), copied from the provider's current price list. Without
prices, the report shows tokens and no cost.

## Alternatives considered

| Option | Why not |
| --- | --- |
| Built-in price table | Goes stale silently; needs a release for every price change |
| Fetch prices from the provider at run time | No stable public pricing API across providers |

## Consequences

Costs are always as current as the user's source. The README points to where
to find prices. Usage numbers are exact; cost is an estimate that ignores
discounts the run did not use (batch, caching).
