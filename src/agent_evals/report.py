"""Render a RunResult as a terminal summary, Markdown or JSON."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from agent_evals.runner import RunResult


def summary_line(run: RunResult) -> str:
    verdict = "PASS" if run.ok else "FAIL"
    return (
        f"{verdict} {run.suite}: {run.passed}/{run.total} passed "
        f"({run.pass_rate:.0%}, threshold {run.threshold:.0%}) "
        f"· provider {run.provider} · mean latency {run.mean_latency_ms:.1f} ms"
    )


def to_markdown(run: RunResult) -> str:
    lines = [
        f"## {run.suite}",
        "",
        f"**{'✅ PASS' if run.ok else '❌ FAIL'}** · {run.passed}/{run.total} passed "
        f"({run.pass_rate:.0%}) · threshold {run.threshold:.0%} · provider `{run.provider}`",
        "",
    ]
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
        "threshold": run.threshold,
        "passed": run.passed,
        "total": run.total,
        "pass_rate": run.pass_rate,
        "mean_latency_ms": run.mean_latency_ms,
        "ok": run.ok,
        "by_tag": {tag: {"passed": p, "total": t} for tag, (p, t) in run.by_tag().items()},
        "results": [asdict(r) for r in run.results],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)
