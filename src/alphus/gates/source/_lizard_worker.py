"""CLI runner for the isolated Lizard API adapter process."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError

from alphus.contracts.process import ExitCode
from alphus.gates.source._lizard_analysis import analyze_lizard_files
from alphus.gates.source._lizard_contracts import (
    LizardWorkerRequest,
    LizardWorkerResponse,
)

_DEFAULT_MAX_MANIFEST_BYTES = 64 * 1024 * 1024
_MAX_CONFIGURABLE_MANIFEST_BYTES = 256 * 1024 * 1024


def _manifest_limit(value: str) -> int:
    try:
        limit = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("manifest limit must be an integer") from error
    if not 1 <= limit <= _MAX_CONFIGURABLE_MANIFEST_BYTES:
        raise argparse.ArgumentTypeError(
            "manifest limit must be between 1 and 268435456 bytes"
        )
    return limit


def main(argv: Sequence[str] | None = None) -> ExitCode:
    """Run one request and keep stdout limited to one validated JSON value."""
    parser = argparse.ArgumentParser(prog="alphus.gates.source._lizard_worker")
    parser.add_argument("root", type=Path)
    parser.add_argument("variant", choices=("standard", "modified"))
    parser.add_argument(
        "--manifest-max-bytes",
        type=_manifest_limit,
        default=_DEFAULT_MAX_MANIFEST_BYTES,
    )
    arguments = parser.parse_args(argv)
    try:
        manifest = sys.stdin.buffer.read(arguments.manifest_max_bytes + 1)
    except OSError:
        response = LizardWorkerResponse(error="Lizard file manifest could not be read")
        exit_code = ExitCode.OPERATIONAL_FAILURE
    else:
        if len(manifest) > arguments.manifest_max_bytes:
            response = LizardWorkerResponse(
                error="Lizard file manifest exceeds the size limit"
            )
            exit_code = ExitCode.OPERATIONAL_FAILURE
        else:
            try:
                request = LizardWorkerRequest.model_validate_json(manifest)
            except ValidationError:
                response = LizardWorkerResponse(
                    error="Lizard file manifest is malformed"
                )
                exit_code = ExitCode.OPERATIONAL_FAILURE
            else:
                try:
                    response = analyze_lizard_files(
                        arguments.root, arguments.variant, request.files
                    )
                except Exception as error:  # noqa: BLE001 - optional API failures are gate errors.
                    response = LizardWorkerResponse(
                        error=f"Lizard API analysis failed ({type(error).__name__})"
                    )
                    exit_code = ExitCode.OPERATIONAL_FAILURE
                else:
                    exit_code = ExitCode.SUCCESS
    sys.stdout.buffer.write(response.model_dump_json().encode("utf-8") + b"\n")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
