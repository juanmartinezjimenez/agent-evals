# 0001. Record architecture decisions

- Status: accepted
- Date: 2026-10-19

## Context

Decisions made in a solo project are easy to forget and hard to explain later,
in a code review, an interview or six months from now.

## Decision

Every decision that is expensive to reverse (a database, a framework, a data
model, a trade-off between cost and quality) gets a short ADR in `docs/adr/`,
numbered in order, using `0000-template.md`.

## Alternatives considered

| Option | Why not |
| --- | --- |
| Comments in code | Explain *how*, rarely *why*; lost when code moves |
| A wiki | Lives outside the repo and drifts out of date |

## Consequences

Each important choice has a written reason next to the code. ADRs are never
edited after acceptance; a new ADR supersedes an old one.
