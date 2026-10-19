"""Command-line interface.

Exit codes:
    0  the suite met its threshold
    1  the suite ran but scored below its threshold
    2  the suite or recordings could not be loaded
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError

from agent_evals import __version__
from agent_evals.models import Suite
from agent_evals.providers import MissingRecordingError, ReplayProvider
from agent_evals.report import summary_line, to_json, to_markdown
from agent_evals.runner import run_suite

EXIT_OK, EXIT_BELOW_THRESHOLD, EXIT_CONFIG_ERROR = 0, 1, 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent-evals", description="Evaluate LLM agents against versioned test cases."
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run a suite and score every case")
    run.add_argument("suite", type=Path, help="path to the suite YAML file")
    run.add_argument(
        "--replay",
        type=Path,
        required=True,
        help="YAML file mapping case id -> recorded model output",
    )
    run.add_argument("--threshold", type=float, help="override the suite's pass threshold (0-1)")
    run.add_argument("--json", type=Path, dest="json_out", help="write the full result as JSON")
    run.add_argument("--markdown", type=Path, help="write a Markdown report")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    try:
        suite = Suite.from_yaml(args.suite)
        provider = ReplayProvider.from_yaml(args.replay)
        run = run_suite(suite, provider, threshold=args.threshold)
    except (OSError, ValueError, ValidationError) as exc:
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
