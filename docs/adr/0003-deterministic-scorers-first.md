# 0003. Deterministic scorers before LLM-as-judge

- Status: accepted
- Date: 2026-10-19

## Context

Outputs can be scored by deterministic checks (exact value, substrings, regex,
JSON Schema) or by asking another model to grade them. Model grading handles
open-ended answers but adds cost, latency and its own errors, which then need
evaluating too.

## Decision

v0.1 ships only deterministic scorers. Every failure carries a human-readable
reason. An LLM-as-judge scorer may be added later for open-ended answers, and it
will report its own agreement rate against a hand-labelled sample.

## Alternatives considered

| Option | Why not |
| --- | --- |
| LLM-as-judge from day one | A grader that is not itself evaluated hides errors behind a number |
| Similarity metrics (BLEU, embeddings) | Hard to interpret and to set a threshold for |

## Consequences

Scores are reproducible and cheap, and a failing case explains itself.
Classification, extraction and formatting tasks are covered; free-form answers
are not yet.
