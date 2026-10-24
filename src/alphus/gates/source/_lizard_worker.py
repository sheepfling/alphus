"""Isolated, version-pinned adapter for Lizard's Python API."""

from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import json
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Protocol, cast


class _FunctionInfo(Protocol):
    name: str
    long_name: str
    start_line: int
    cyclomatic_complexity: int


class _FileInfo(Protocol):
    filename: str
    function_list: Sequence[_FunctionInfo | None]


class _LizardApi(Protocol):
    def get_extensions(self, names: Sequence[str]) -> Sequence[object]: ...

    def analyze_files(
        self, files: Sequence[str], *, exts: Sequence[object]
    ) -> Iterable[_FileInfo | None]: ...


def _analyze(root: Path, variant: str, files: Sequence[str]) -> dict[str, object]:
    """Analyze only the explicitly selected C-family paths with Lizard."""
    lizard = cast(_LizardApi, importlib.import_module("lizard"))

    checkout = root.resolve(strict=True)
    paths: list[Path] = []
    for value in files:
        path = (checkout / value).resolve(strict=True)
        if not path.is_file() or not path.is_relative_to(checkout):
            raise ValueError(f"selected path is not a checkout file: {value}")
        paths.append(path)

    extension_names = ["mccabe"] if variant == "modified" else []
    extensions = lizard.get_extensions(extension_names)
    file_results: list[dict[str, object]] = []
    analyzed_file_count = 0
    for source_file in lizard.analyze_files(
        [str(path) for path in paths], exts=extensions
    ):
        if source_file is None:
            continue
        analyzed_file_count += 1
        source_path = Path(source_file.filename).resolve(strict=True)
        if not source_path.is_relative_to(checkout):
            raise ValueError(
                f"Lizard returned a path outside the checkout: {source_file.filename}"
            )
        functions: list[dict[str, object]] = []
        for function in source_file.function_list:
            if function is None or function.name == "*global*":
                continue
            identity = function.long_name or function.name
            functions.append(
                {
                    "name": str(identity),
                    "line": function.start_line,
                    "value": function.cyclomatic_complexity,
                }
            )
        file_results.append(
            {
                "path": source_path.relative_to(checkout).as_posix(),
                "functions": functions,
            }
        )

    return {
        "version": importlib.metadata.version("lizard"),
        "analyzed_file_count": analyzed_file_count,
        "files": file_results,
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Run the adapter protocol and keep stdout limited to one JSON value."""
    parser = argparse.ArgumentParser(prog="alphus.gates.source._lizard_worker")
    parser.add_argument("root", type=Path)
    parser.add_argument("variant", choices=("standard", "modified"))
    parser.add_argument("files", nargs="+")
    arguments = parser.parse_args(argv)
    try:
        payload = _analyze(arguments.root, arguments.variant, arguments.files)
    except Exception as error:  # noqa: BLE001 - opaque optional API failures are gates.
        payload = {"error": f"Lizard API analysis failed: {error}"}
        json.dump(payload, sys.stdout, sort_keys=True)
        sys.stdout.write("\n")
        return 2
    json.dump(payload, sys.stdout, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
