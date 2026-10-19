# 0005. `compare` gates on case regressions, not on metric deltas

- Status: accepted
- Date: 2026-10-19

## Context

`agent-evals compare BASE HEAD` decides whether a change (a new prompt, a new
model) can be merged. It has several signals to choose from: per-case results,
pass rate, latency, tokens and cost. A threshold on the pass rate alone misses
the common case where a change fixes one case and breaks another: the rate does
not move, but a behaviour that used to work is now broken. Latency is noisy
between runs, and cost depends on prices the user supplies (ADR 0004).

## Decision

Cases are matched by id. A **regression** is a case that passed in the base run
and fails in the head run, for any reason, including a provider error. The
command exits `1` if there is at least one regression and `0` otherwise.

Fixes, added cases and removed cases are reported but never fail the
comparison. Changes in pass rate, latency, tokens and cost are reported as
information only. Comparing reports from different suites is a setup error
(exit `2`), because case ids would not mean the same thing.

## Alternatives considered

| Option | Why not |
| --- | --- |
| Fail when the pass rate drops | Misses regressions hidden by a fix elsewhere, the case this command exists for |
| Fail on any latency or cost increase | Too noisy to gate on by default; a budget flag can be added when there is a real need |
| Treat a new failing case as a regression | There is no baseline to regress from; the suite threshold already covers it in `run` |

## Consequences

The exit code is easy to explain: "a case that used to pass now fails". A
regression accepted on purpose (for example, an expectation that changed) has to
be resolved by updating the case or the base report, which leaves a trace in
code review. Metric budgets (`--max-cost-increase`, `--max-p95-increase`) remain
possible additions that would not change this rule.
