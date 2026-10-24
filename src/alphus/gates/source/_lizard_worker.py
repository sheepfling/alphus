"""CLI runner for the isolated Lizard API adapter process."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from alphus.contracts.process import ExitCode
from alphus.gates.source._lizard_analysis import analyze_lizard_files
from alphus.gates.source._lizard_contracts import LizardWorkerResponse


def main(argv: Sequence[str] | None = None) -> ExitCode:
    """Run one request and keep stdout limited to one validated JSON value."""
    parser = argparse.ArgumentParser(prog="alphus.gates.source._lizard_worker")
    parser.add_argument("root", type=Path)
    parser.add_argument("variant", choices=("standard", "modified"))
    parser.add_argument("files", nargs="+")
    arguments = parser.parse_args(argv)
    try:
        response = analyze_lizard_files(
            arguments.root, arguments.variant, arguments.files
        )
    except Exception as error:  # noqa: BLE001 - optional API failures are gate errors.
        response = LizardWorkerResponse(error=f"Lizard API analysis failed: {error}")
        exit_code = ExitCode.OPERATIONAL_FAILURE
    else:
        exit_code = ExitCode.SUCCESS
    sys.stdout.write(response.model_dump_json() + "\n")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
