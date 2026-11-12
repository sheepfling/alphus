"""Check every declaration owned by an installed stub distribution."""

from __future__ import annotations

import argparse
import os
import subprocess
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from alphus.gates.stubs.checker_reports import PyrightReport
from alphus.gates.stubs.environments import child_environment, probe_python
from alphus.support.python_runtime import current_python_executable
from alphus.support.source_text import read_utf8_text

INVENTORY_SCRIPT = """
import importlib.metadata as metadata
import json
import pathlib
import sys
record = metadata.distribution(sys.argv[1])
if record.files is None:
    raise SystemExit('installed distribution has no file inventory')
files = sorted(str(pathlib.Path(record.locate_file(item)).resolve())
               for item in record.files if str(item).endswith('.pyi'))
print(json.dumps({'distribution': record.metadata['Name'], 'files': files,
                  'installation_root': str(pathlib.Path(record.locate_file('')).resolve())}))
"""


class InstalledDeclarations(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    distribution: str
    installation_root: str
    files: Annotated[tuple[str, ...], Field(min_length=1)]


def declaration_paths(inventory: InstalledDeclarations) -> tuple[Path, ...]:
    """Reject missing, duplicate and non-declaration inventory entries."""
    paths = tuple(Path(item).resolve() for item in inventory.files)
    if len(set(paths)) != len(paths):
        raise ValueError("installed declaration inventory contains duplicates")
    if any(not Path(item).is_absolute() for item in inventory.files):
        raise ValueError("installed declaration inventory paths must be absolute")
    if any(path.suffix != ".pyi" or not path.is_file() for path in paths):
        raise ValueError(
            "installed declaration inventory contains missing or invalid files"
        )
    return paths


def snapshot_declarations(
    paths: Sequence[Path], destination: Path, installation_root: Path
) -> tuple[Path, ...]:
    """Preserve installed module identities and partial-package runtime fallback."""
    if not paths:
        raise ValueError("installed declaration inventory is empty")
    base = installation_root.resolve()
    if not installation_root.is_absolute() or not base.is_dir():
        raise ValueError("installed declaration root must be an absolute directory")
    relative_paths = tuple(path.resolve().relative_to(base) for path in paths)
    for name in sorted({path.parts[0] for path in relative_paths}):
        package = base / name
        marker = package / "py.typed"
        if not name.endswith("-stubs") or not marker.is_file():
            continue
        if "partial" not in read_utf8_text(marker).splitlines():
            continue
        # PEP 561 partial stubs supplement their installed runtime package.
        # Copy only that package's Python sources, never the checker environment.
        runtime = base / name.removesuffix("-stubs")
        if runtime.is_dir():
            for source in sorted(runtime.rglob("*")):
                if source.is_file() and (
                    source.suffix in {".py", ".pyi"} or source.name == "py.typed"
                ):
                    target = destination / runtime.name / source.relative_to(runtime)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(source.read_bytes())
    copied: list[Path] = []
    for path, relative in zip(paths, relative_paths, strict=True):
        # A foo-stubs distribution supplies the importable foo package. Keep
        # the full package hierarchy, including for a lone nested declaration.
        top, *rest = relative.parts
        target = destination / top.removesuffix("-stubs")
        target = target.joinpath(*rest)
        if target in copied:
            raise ValueError("installed declarations map to duplicate modules")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())
        copied.append(target)
    return tuple(copied)


class DeclarationConfig(BaseModel):
    model_config = ConfigDict(frozen=True, populate_by_name=True)
    type_checking_mode: Annotated[
        Literal["strict"], Field(alias="typeCheckingMode")
    ] = "strict"
    python_version: Annotated[str, Field(alias="pythonVersion")]
    include: tuple[str, ...]
    extra_paths: Annotated[tuple[str, ...], Field(alias="extraPaths")] = ()
    report_missing_module_source: Annotated[
        bool, Field(alias="reportMissingModuleSource")
    ] = False
    report_deprecated: Annotated[Literal["error"], Field(alias="reportDeprecated")] = (
        "error"
    )


def declaration_config(
    paths: Sequence[Path],
    config_directory: Path,
    python_version: str,
    import_root: Path | None = None,
) -> DeclarationConfig:
    """Resolve snapshot paths relative to their canonical configuration base."""
    base = config_directory.resolve()
    return DeclarationConfig(
        python_version=python_version,
        extra_paths=(str(import_root.resolve().relative_to(base)),)
        if import_root
        else (),
        include=tuple(str(path.resolve().relative_to(base)) for path in paths),
    )


def validate_declaration_report(
    output: str, returncode: int, expected_files: int
) -> None:
    report = PyrightReport.model_validate_json(output)
    if expected_files < 1 or report.summary.files_analyzed != expected_files:
        raise ValueError(
            f"expected {expected_files} analyzed declarations, got {report.summary.files_analyzed}"
        )
    errors = tuple(item for item in report.diagnostics if item.severity == "error")
    if report.summary.error_count != len(errors):
        raise ValueError("Pyright errorCount disagrees with declaration diagnostics")
    if returncode != 0 or errors:
        raise ValueError(
            f"declaration check failed: exit={returncode}, errors={len(errors)}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--distribution", required=True)
    parser.add_argument("--target-python", required=True)
    args = parser.parse_args()
    target = probe_python(args.target_python)
    environment = child_environment(os.environ, current_python_executable())
    try:
        with tempfile.TemporaryDirectory(prefix="alphus-declarations-") as temporary:
            root = Path(temporary).resolve()
            inventory_result = subprocess.run(
                [target.executable, "-I", "-c", INVENTORY_SCRIPT, args.distribution],
                cwd=root,
                capture_output=True,
                text=True,
                check=True,
                timeout=60,
            )
            inventory = InstalledDeclarations.model_validate_json(
                inventory_result.stdout
            )
            paths = declaration_paths(inventory)
            config = root / "pyrightconfig.json"
            copied = snapshot_declarations(
                paths, root / "declarations", Path(inventory.installation_root)
            )
            config.write_text(
                declaration_config(
                    copied, root, target.minor, root / "declarations"
                ).model_dump_json(by_alias=True),
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    current_python_executable(),
                    "-m",
                    "pyright",
                    "--project",
                    str(config),
                    "--pythonpath",
                    target.executable,
                    "--outputjson",
                ],
                cwd=root,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
                timeout=180,
            )
            print(result.stdout)
            if result.stderr:
                print(result.stderr)
            validate_declaration_report(result.stdout, result.returncode, len(paths))
            print(
                f"Verified {len(paths)} installed declarations for {inventory.distribution}"
            )
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"Installed declaration check failed: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
