"""Render a RunResult as a terminal summary, Markdown or JSON."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from agent_evals.runner import RunResult


def _target(run: RunResult) -> str:
    return f"{run.provider}:{run.model}" if run.model else run.provider


def _usage(run: RunResult) -> str:
    parts = []
    if run.input_tokens is not None and run.output_tokens is not None:
        parts.append(f"{run.input_tokens:,} in / {run.output_tokens:,} out tokens")
    if run.cost_usd is not None:
        parts.append(f"${run.cost_usd:.4f}")
    return " · ".join(parts)


def summary_line(run: RunResult) -> str:
    verdict = "PASS" if run.ok else "FAIL"
    pieces = [
        f"{verdict} {run.suite}: {run.passed}/{run.total} passed "
        f"({run.pass_rate:.0%}, threshold {run.threshold:.0%})",
        _target(run),
        f"latency mean {run.mean_latency_ms:.1f} ms, p95 {run.p95_latency_ms:.1f} ms",
    ]
    if usage := _usage(run):
        pieces.append(usage)
    if run.errors:
        pieces.append(f"{run.errors} provider errors")
    return " · ".join(pieces)


def to_markdown(run: RunResult) -> str:
    header = (
        f"**{'✅ PASS' if run.ok else '❌ FAIL'}** · {run.passed}/{run.total} passed "
        f"({run.pass_rate:.0%}) · threshold {run.threshold:.0%} · `{_target(run)}`"
    )
    lines = [f"## {run.suite}", "", header, ""]

    metrics = [
        ("Mean latency", f"{run.mean_latency_ms:.1f} ms"),
        ("p95 latency", f"{run.p95_latency_ms:.1f} ms"),
    ]
    if run.input_tokens is not None and run.output_tokens is not None:
        metrics.append(("Tokens (in / out)", f"{run.input_tokens:,} / {run.output_tokens:,}"))
    if run.cost_usd is not None:
        metrics.append(("Cost", f"${run.cost_usd:.4f}"))
    if run.errors:
        metrics.append(("Provider errors", str(run.errors)))
    lines += ["| Metric | Value |", "| --- | --- |"]
    lines += [f"| {name} | {value} |" for name, value in metrics]
    lines.append("")

    tags = run.by_tag()
    if tags:
        lines += ["| Tag | Passed |", "| --- | --- |"]
        lines += [f"| {tag} | {p}/{t} |" for tag, (p, t) in tags.items()]
        lines.append("")

    failures = [r for r in run.results if not r.passed]
    if failures:
        lines += ["### Failures", "", "| Case | Reason |", "| --- | --- |"]
        lines += [f"| `{r.case_id}` | {r.reason.replace('|', '\\|')} |" for r in failures]
        lines.append("")
    return "\n".join(lines)


def to_json(run: RunResult) -> str:
    payload: dict[str, Any] = {
        "suite": run.suite,
        "provider": run.provider,
        "model": run.model,
        "threshold": run.threshold,
        "passed": run.passed,
        "total": run.total,
        "errors": run.errors,
        "pass_rate": run.pass_rate,
        "ok": run.ok,
        "mean_latency_ms": run.mean_latency_ms,
        "p95_latency_ms": run.p95_latency_ms,
        "input_tokens": run.input_tokens,
        "output_tokens": run.output_tokens,
        "cost_usd": run.cost_usd,
        "by_tag": {tag: {"passed": p, "total": t} for tag, (p, t) in run.by_tag().items()},
        "results": [asdict(r) for r in run.results],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)
