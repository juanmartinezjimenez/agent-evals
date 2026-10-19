# 0002. A replay provider makes CI deterministic and free

- Status: accepted
- Date: 2026-10-19

## Context

Calling a real model in CI costs money on every push, needs an API key stored as
a secret, is slow, and returns slightly different outputs each time. Tests that
depend on it are flaky and cannot be run by contributors without a key.

## Decision

Providers implement a single `Provider` protocol. v0.1 ships only a
`ReplayProvider`, which returns outputs recorded in a YAML file keyed by case id.
CI runs the example suites through it. Real providers will be added behind the
same protocol and will be able to write recordings that the replay provider reads.

## Alternatives considered

| Option | Why not |
| --- | --- |
| Call a real model in CI | Cost, secrets, latency and non-deterministic results |
| Mock the HTTP client of each SDK | Couples tests to SDK internals; breaks on every SDK update |

## Consequences

The full pipeline (loading, scoring, reporting, exit codes) is tested on every
push with no key and no cost. A live run against a real model is a separate,
explicit step that will be added in v0.2.
