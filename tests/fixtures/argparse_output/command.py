"""Trusted synthetic CLI: select a construction, then write its selected output.

The first two arguments are fixture controls, not consumer CLI options. Execute
only this repository-owned fixture, never a scanned consumer's Python source.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def build_parser(scenario: str, corrected: bool) -> argparse.ArgumentParser:
    """Build the deliberately small parser variants exercised by subprocesses."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", dest="output_path", default="root-default.txt")
    commands = parser.add_subparsers(dest="command", required=True)
    child = commands.add_parser("render")
    default = argparse.SUPPRESS if corrected else "child-default.txt"

    if scenario == "implicit":
        if corrected:
            child.add_argument(
                "--output", dest="output_path", default=argparse.SUPPRESS
            )
        else:
            child.add_argument("--output", dest="output_path")
    elif scenario == "set-before":
        child.set_defaults(output_path="command-default.txt")
        # An explicit action default takes precedence over the earlier parser
        # default, but SUPPRESS still leaves the parser-level default active.
        child.add_argument("--output", dest="output_path", default=default)
    elif scenario == "set-before-inherited":
        child.set_defaults(output_path="command-default.txt")
        child.add_argument("--output", dest="output_path")
    elif scenario in {"set-after", "suppress-reset", "intentional"}:
        child.add_argument("--output", dest="output_path", default=default)
        child.set_defaults(output_path="command-default.txt")
        if scenario == "suppress-reset":
            child.set_defaults(output_path=argparse.SUPPRESS)
    elif scenario == "required":
        child.add_argument(
            "--output", dest="output_path", default=default, required=True
        )
    else:
        option = "--report" if scenario == "custom-dest" else "--output"
        child.add_argument(option, dest="output_path", default=default)

    if scenario == "nested":
        leaves = child.add_subparsers(dest="operation", required=True)
        leaf = leaves.add_parser("detail")
        leaf.add_argument(
            "--output",
            dest="output_path",
            default=argparse.SUPPRESS if corrected else "leaf-default.txt",
        )
    return parser


def main() -> None:
    scenario, variant, *arguments = sys.argv[1:]
    args = build_parser(scenario, variant == "fixed").parse_args(arguments)
    # None models a CLI that emits no file unless an output was selected. This
    # makes implicit None clobbering observable without a namespace assertion.
    if args.output_path is not None:
        Path(args.output_path).write_text(
            "synthetic rendered output\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()
