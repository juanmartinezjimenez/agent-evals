"""Command-line interface.

Exit codes:
    0  the suite met its threshold
    1  the suite ran but scored below its threshold
    2  the suite, recordings or provider could not be set up
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError

from agent_evals import __version__
from agent_evals.models import Suite
from agent_evals.pricing import Pricing
from agent_evals.providers import (
    PROVIDERS,
    MissingRecordingError,
    ProviderSetupError,
    make_provider,
    write_recording,
)
from agent_evals.report import summary_line, to_json, to_markdown
from agent_evals.runner import RunResult, run_suite

EXIT_OK, EXIT_BELOW_THRESHOLD, EXIT_CONFIG_ERROR = 0, 1, 2


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
        "--record", type=Path, help="after a live run, save outputs here for later replay"
    )

    cost = run.add_argument_group("cost (USD per million tokens, from the provider's price list)")
    cost.add_argument("--price-input", type=float, metavar="USD", help="input token price")
    cost.add_argument("--price-output", type=float, metavar="USD", help="output token price")

    out = run.add_argument_group("output")
    out.add_argument("--threshold", type=float, help="override the suite's pass threshold (0-1)")
    out.add_argument("--json", type=Path, dest="json_out", help="write the full result as JSON")
    out.add_argument("--markdown", type=Path, help="write a Markdown report")
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
    if args.record and provider_name == "replay":
        raise ValueError("--record only makes sense with a live provider")

    suite = Suite.from_yaml(args.suite)
    provider = make_provider(provider_name, model=args.model, replay=args.replay)
    run = run_suite(suite, provider, threshold=args.threshold, pricing=_pricing(args))

    if args.record:
        write_recording(args.record, {r.case_id: r.output for r in run.results if not r.error})
    return run


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    try:
        run = _execute(args)
    except (OSError, ValueError, ValidationError, ProviderSetupError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_CONFIG_ERROR
    except MissingRecordingError as exc:
        print(f"error: no recorded output for case {exc.args[0]!r}", file=sys.stderr)
        return EXIT_CONFIG_ERROR

    print(summary_line(run))
    for r in run.results:
        if not r.passed:
            print(f"  ✗ {r.case_id}: {r.reason}")

    if args.json_out:
        args.json_out.write_text(to_json(run) + "\n", encoding="utf-8")
    if args.markdown:
        args.markdown.write_text(to_markdown(run), encoding="utf-8")

    return EXIT_OK if run.ok else EXIT_BELOW_THRESHOLD


if __name__ == "__main__":
    sys.exit(main())
