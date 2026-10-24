"""Read-only analysis utilities for the isolated Lizard worker."""

from __future__ import annotations

import importlib
import importlib.metadata
from collections.abc import Sequence
from pathlib import Path
from typing import cast

from alphus.gates.source._lizard_contracts import (
    LizardApi,
    LizardFileRecord,
    LizardFunctionRecord,
    LizardWorkerResponse,
)


def analyze_lizard_files(
    root: Path, variant: str, files: Sequence[str]
) -> LizardWorkerResponse:
    """Analyze the explicitly selected C-family paths with the pinned API."""
    lizard = cast(LizardApi, importlib.import_module("lizard"))

    checkout = root.resolve(strict=True)
    selected_paths: list[Path] = []
    for value in files:
        path = (checkout / value).resolve(strict=True)
        if not path.is_file() or not path.is_relative_to(checkout):
            raise ValueError(f"selected path is not a checkout file: {value}")
        selected_paths.append(path)

    extension_names = ("mccabe",) if variant == "modified" else ()
    extensions = lizard.get_extensions(extension_names)
    results: list[LizardFileRecord] = []
    analyzed_file_count = 0
    for source_file in lizard.analyze_files(
        tuple(str(path) for path in selected_paths), exts=extensions
    ):
        if source_file is None:
            continue
        analyzed_file_count += 1
        source_path = Path(source_file.filename).resolve(strict=True)
        if not source_path.is_relative_to(checkout):
            raise ValueError(
                f"Lizard returned a path outside the checkout: {source_file.filename}"
            )
        functions = tuple(
            LizardFunctionRecord(
                name=str(function.long_name or function.name),
                line=function.start_line,
                value=function.cyclomatic_complexity,
            )
            for function in source_file.function_list
            if function is not None and function.name != "*global*"
        )
        results.append(
            LizardFileRecord(
                path=source_path.relative_to(checkout).as_posix(),
                functions=functions,
            )
        )

    return LizardWorkerResponse(
        version=importlib.metadata.version("lizard"),
        analyzed_file_count=analyzed_file_count,
        files=tuple(results),
    )
