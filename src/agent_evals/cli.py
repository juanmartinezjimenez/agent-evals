"""Command-line interface.

Exit codes for `run`:
    0  the suite met its threshold
    1  the suite ran but scored below its threshold
    2  the suite, recordings or provider could not be set up, or a replayed case is
       stale (its recording answers a different prompt or input); reports are still written

Exit codes for `compare`:
    0  no case that passed in the base run fails in the head run, and none is stale
    1  at least one regression or stale case
    2  a report could not be read, or the reports are for different suites
"""

from __future__ import annotations

import argparse
import io
import sys
from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError

from agent_evals import __version__
from agent_evals.compare import RunReport, compare
from agent_evals.models import Suite
from agent_evals.pricing import Pricing
from agent_evals.providers import (
    PROVIDERS,
    MissingRecordingError,
    ProviderSetupError,
    ReplayProvider,
    make_provider,
    write_recording,
)
from agent_evals.report import (
    comparison_summary,
    comparison_to_markdown,
    summary_line,
    to_json,
    to_markdown,
)
from agent_evals.runner import RunResult, run_suite

EXIT_OK, EXIT_BELOW_THRESHOLD, EXIT_CONFIG_ERROR = 0, 1, 2
EXIT_REGRESSION = 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent-evals", description="Evaluate LLM agents against versioned test cases."
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run a suite and score every case")
    run.add_argument("suite", type=Path, help="path to the suite YAML file")

    source = run.add_argument_group("provider")
    source.add_argument(
        "--provider",
        choices=PROVIDERS,
        help="where outputs come from (default: replay if --replay is given)",
    )
    source.add_argument("--model", help="model id for live providers, e.g. claude-haiku-5-5")
    source.add_argument("--replay", type=Path, help="recorded outputs to replay (case id -> text)")
    source.add_argument(
        "--record",
        type=Path,
        help="save outputs here for later replay; with --replay, upgrades an old recording",
    )

    cost = run.add_argument_group("cost (USD per million tokens, from the provider's price list)")
    cost.add_argument("--price-input", type=float, metavar="USD", help="input token price")
    cost.add_argument("--price-output", type=float, metavar="USD", help="output token price")

    out = run.add_argument_group("output")
    out.add_argument("--threshold", type=float, help="override the suite's pass threshold (0-1)")
    out.add_argument("--json", type=Path, dest="json_out", help="write the full result as JSON")
    out.add_argument("--markdown", type=Path, help="write a Markdown report")

    diff = sub.add_parser("compare", help="compare two JSON reports and fail if any case regressed")
    diff.add_argument("base", type=Path, help="report of the reference run (run --json)")
    diff.add_argument("head", type=Path, help="report of the run being checked (run --json)")
    diff.add_argument("--markdown", type=Path, help="write the comparison as Markdown")
    return parser


def _pricing(args: argparse.Namespace) -> Pricing | None:
    given = (args.price_input is not None, args.price_output is not None)
    if given == (False, False):
        return None
    if given != (True, True):
        raise ValueError("--price-input and --price-output must be given together")
    return Pricing(args.price_input, args.price_output)


def _execute(args: argparse.Namespace) -> RunResult:
    provider_name = args.provider or ("replay" if args.replay else None)
    if provider_name is None:
        raise ValueError("choose a source: --replay FILE or --provider openai|anthropic --model M")

    suite = Suite.from_yaml(args.suite)
    provider = make_provider(provider_name, model=args.model, replay=args.replay)
    run = run_suite(suite, provider, threshold=args.threshold, pricing=_pricing(args))

    if args.record:
        if run.stale:
            # Re-recording a stale replay would stamp a new fingerprint on an old answer.
            raise ValueError(
                f"not recording: {run.stale} stale case(s); re-record them with a live provider"
            )
        if isinstance(provider, ReplayProvider):  # upgrade: keep where the outputs came from
            source = (provider.recorded_provider, provider.recorded_model)
        else:
            source = (provider.name, run.model)
        outputs = {r.case_id: r.output for r in run.results if not r.error}
        write_recording(args.record, suite, outputs, provider=source[0], model=source[1])
    return run


def _compare(args: argparse.Namespace) -> int:
    try:
        result = compare(RunReport.from_json(args.base), RunReport.from_json(args.head))
    except (OSError, ValueError) as exc:  # ValueError covers invalid JSON and ValidationError
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_CONFIG_ERROR

    print(comparison_summary(result))
    if args.markdown:
        args.markdown.write_text(comparison_to_markdown(result), encoding="utf-8")
    return EXIT_OK if result.ok else EXIT_REGRESSION


def _run(args: argparse.Namespace) -> int:
    try:
        run = _execute(args)
    except (OSError, ValueError, ValidationError, ProviderSetupError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_CONFIG_ERROR
    except MissingRecordingError as exc:
        print(f"error: no recorded output for case {exc.args[0]!r}", file=sys.stderr)
        return EXIT_CONFIG_ERROR

    for warning in run.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    print(summary_line(run))
    for r in run.results:
        if not r.passed:
            print(f"  {'⚠' if r.stale else '✗'} {r.case_id}: {r.reason}")

    if args.json_out:
        args.json_out.write_text(to_json(run) + "\n", encoding="utf-8")
    if args.markdown:
        args.markdown.write_text(to_markdown(run), encoding="utf-8")

    if run.stale:
        sys.stdout.flush()  # keep the summary above the error when both go to one log
        print(
            f"error: {run.stale} stale case(s); results do not reflect the suite", file=sys.stderr
        )
        return EXIT_CONFIG_ERROR
    return EXIT_OK if run.ok else EXIT_BELOW_THRESHOLD


def _use_utf8_output() -> None:
    """Reports contain ✗ and →; Windows pipes default to cp1252, which cannot encode them."""
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    _use_utf8_output()
    args = _build_parser().parse_args(argv)
    return _compare(args) if args.command == "compare" else _run(args)


if __name__ == "__main__":
    sys.exit(main())
