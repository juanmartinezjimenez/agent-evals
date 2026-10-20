"""Render a RunResult as a terminal summary, Markdown or JSON, and a Comparison as text."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from agent_evals.compare import Comparison, RunReport
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
    if run.stale:
        pieces.append(f"{run.stale} stale")
    return " · ".join(pieces)


def _stale_notice(case_ids: list[str]) -> list[str]:
    """GitHub WARNING alert listing stale cases; goes above the metrics, which it invalidates."""
    n = len(case_ids)
    return [
        "> [!WARNING]",
        f"> **{n} case{'' if n == 1 else 's'} replayed answers recorded for a different "
        "prompt or input.**",
        "> Their results say nothing about the current suite. Re-record them with a live run",
        "> (`agent-evals run SUITE --provider ... --model ... --record RECORDING`) "
        "and push the recording.",
        ">",
        *[f"> - `{case_id}`" for case_id in case_ids],
        "",
    ]


def _warning_notice(warnings: list[str] | tuple[str, ...]) -> list[str]:
    """One GitHub NOTE alert per run warning; a blank line keeps the alerts separate."""
    lines: list[str] = []
    for warning in warnings:
        lines += ["> [!NOTE]", f"> {warning}", ""]
    return lines


def to_markdown(run: RunResult) -> str:
    stale = f" · ⚠️ {run.stale} stale" if run.stale else ""
    header = (
        f"**{'✅ PASS' if run.ok else '❌ FAIL'}** · {run.passed}/{run.total} passed "
        f"({run.pass_rate:.0%}) · threshold {run.threshold:.0%}{stale} · `{_target(run)}`"
    )
    lines = [f"## {run.suite}", "", header, ""]
    if run.stale:
        lines += _stale_notice([r.case_id for r in run.results if r.stale])
    lines += _warning_notice(run.warnings)

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
        "stale": run.stale,
        "warnings": list(run.warnings),
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


def _changes(c: Comparison) -> str:
    regressions, fixes = len(c.regressions), len(c.fixes)
    return (
        f"{regressions} regression{'' if regressions == 1 else 's'}, "
        f"{fixes} fix{'' if fixes == 1 else 'es'}"
    )


def _escape(text: str) -> str:
    return text.replace("|", "\\|")


def _rate(report: RunReport) -> str:
    return f"{report.pass_rate:.0%} ({report.passed}/{report.total})"


def _pp(c: Comparison) -> str:
    return f"{(c.head.pass_rate - c.base.pass_rate) * 100:+.0f} pp"


def _usd(value: float) -> str:
    return f"{'-' if value < 0 else '+'}${abs(value):.4f}"


def _tokens(report: RunReport) -> str | None:
    if report.input_tokens is None or report.output_tokens is None:
        return None
    return f"{report.input_tokens:,} / {report.output_tokens:,}"


def comparison_summary(c: Comparison) -> str:
    """One headline plus one line per changed case, for the terminal."""
    verdict = "PASS" if c.ok else "FAIL"
    pieces = [
        f"{verdict} {c.head.suite}: {_changes(c)}" + (f", {len(c.stale)} stale" if c.stale else ""),
        f"pass rate {c.base.pass_rate:.0%} → {c.head.pass_rate:.0%} ({_pp(c)})",
        f"{c.base.target} → {c.head.target}",
        f"latency mean {c.base.mean_latency_ms:.1f} → {c.head.mean_latency_ms:.1f} ms, "
        f"p95 {c.base.p95_latency_ms:.1f} → {c.head.p95_latency_ms:.1f} ms",
    ]
    if c.base.cost_usd is not None and c.head.cost_usd is not None:
        pieces.append(f"cost ${c.base.cost_usd:.4f} → ${c.head.cost_usd:.4f}")

    lines = [" · ".join(pieces)]
    lines += [f"  ⚠ {r.case_id}: {r.reason}" for r in c.stale]
    lines += [f"  ✗ {r.case_id}: {r.reason}" for r in c.regressions]
    lines += [f"  ✓ {f.case_id}: fixed" for f in c.fixes]
    lines += [
        f"  + {r.case_id}: added ({'passes' if r.passed else f'fails: {r.reason}'})"
        for r in c.added
    ]
    lines += [f"  - {r.case_id}: removed" for r in c.removed]
    return "\n".join(lines)


def comparison_to_markdown(c: Comparison) -> str:
    changes = _changes(c)
    if c.stale:
        n = len(c.stale)
        changes += f" · ⚠️ {n} stale recording{'' if n == 1 else 's'}"
    header = (
        f"**{'✅ PASS' if c.ok else '❌ FAIL'}** · {changes} · "
        f"`{c.base.target}` → `{c.head.target}`"
    )
    lines = [f"## {c.head.suite}: base vs head", "", header, ""]
    if c.stale:
        lines += _stale_notice([r.case_id for r in c.stale])
    lines += _warning_notice(c.head.warnings)

    rows = [
        ("Pass rate", _rate(c.base), _rate(c.head), _pp(c)),
        (
            "Mean latency",
            f"{c.base.mean_latency_ms:.1f} ms",
            f"{c.head.mean_latency_ms:.1f} ms",
            f"{c.head.mean_latency_ms - c.base.mean_latency_ms:+.1f} ms",
        ),
        (
            "p95 latency",
            f"{c.base.p95_latency_ms:.1f} ms",
            f"{c.head.p95_latency_ms:.1f} ms",
            f"{c.head.p95_latency_ms - c.base.p95_latency_ms:+.1f} ms",
        ),
    ]
    base_tokens, head_tokens = _tokens(c.base), _tokens(c.head)
    if base_tokens or head_tokens:
        rows.append(("Tokens (in / out)", base_tokens or "—", head_tokens or "—", ""))
    if c.base.cost_usd is not None or c.head.cost_usd is not None:
        change = (
            _usd(c.head.cost_usd - c.base.cost_usd)
            if c.base.cost_usd is not None and c.head.cost_usd is not None
            else ""
        )
        rows.append(
            (
                "Cost",
                f"${c.base.cost_usd:.4f}" if c.base.cost_usd is not None else "—",
                f"${c.head.cost_usd:.4f}" if c.head.cost_usd is not None else "—",
                change,
            )
        )
    lines += ["| Metric | Base | Head | Change |", "| --- | --- | --- | --- |"]
    lines += [f"| {' | '.join(row)} |" for row in rows]
    lines.append("")

    if c.regressions:
        lines += ["### Regressions", "", "| Case | Now fails because |", "| --- | --- |"]
        lines += [f"| `{r.case_id}` | {_escape(r.reason)} |" for r in c.regressions]
        lines.append("")
    if c.fixes:
        lines += ["### Fixes", "", "| Case | Used to fail because |", "| --- | --- |"]
        lines += [f"| `{f.case_id}` | {_escape(f.reason)} |" for f in c.fixes]
        lines.append("")
    if c.added:
        lines += ["### Added cases", ""]
        lines += [f"- `{r.case_id}`: {'passes' if r.passed else 'fails'}" for r in c.added]
        lines.append("")
    if c.removed:
        lines += ["### Removed cases", ""]
        lines += [f"- `{r.case_id}`" for r in c.removed]
        lines.append("")
    return "\n".join(lines)
