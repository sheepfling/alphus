"""Check every declaration owned by an installed stub distribution."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Literal, NoReturn, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from alphus.gates.stubs.checker_reports import (
    NativeDiagnostic,
    PyrightReport,
    parse_checker_diagnostics,
)
from alphus.gates.stubs.environments import child_environment, probe_python
from alphus.support.python_runtime import current_python_executable
from alphus.support.source_text import read_utf8_text
from alphus.support.tool_probe import probe_python_module

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


CheckerName = Literal["mypy", "pyright", "ty"]
DEFAULT_CHECKERS: tuple[CheckerName, ...] = ("mypy", "pyright", "ty")
MAX_CAPTURE = 50_000


class DeclarationCheckerResult(BaseModel):
    """Native evidence; submitted paths are not a fabricated analyzed count."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    checker: CheckerName
    argv: tuple[str, ...]
    passed: bool
    returncode: int
    submitted_paths: tuple[str, ...]
    analyzed_files: Annotated[int, Field(ge=0)] | None = None
    coverage_kind: Literal["native-count", "explicit-inputs"]
    diagnostics: tuple[NativeDiagnostic, ...] = ()
    stdout: str = ""
    stderr: str = ""
    output_truncated: bool = False
    validation_error: str | None = None

    @model_validator(mode="after")
    def validate_evidence(self) -> Self:
        if self.coverage_kind != (
            "native-count" if self.checker == "pyright" else "explicit-inputs"
        ):
            raise ValueError("checker coverage kind is inconsistent")
        if self.checker != "pyright" and self.analyzed_files is not None:
            raise ValueError("this checker does not provide a native analyzed count")
        expected = (
            bool(self.submitted_paths)
            and self.returncode == 0
            and self.validation_error is None
            and not any(item.severity == "error" for item in self.diagnostics)
        )
        if self.passed != expected:
            raise ValueError("checker outcome disagrees with evidence")
        if (
            self.passed
            and self.checker == "pyright"
            and self.analyzed_files != len(self.submitted_paths)
        ):
            raise ValueError(
                "Pyright analyzed count disagrees with submitted declarations"
            )
        return self


class DeclarationReport(BaseModel):
    """Version 1 public JSON envelope for installed declaration verification."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    schema_version: Literal[1] = 1
    kind: Literal["stub-declarations"] = "stub-declarations"
    distribution: str
    inventory: tuple[str, ...] = ()
    checkers: tuple[CheckerName, ...] = ()
    results: tuple[DeclarationCheckerResult, ...] = ()
    errors: tuple[str, ...] = ()
    passed: bool

    @model_validator(mode="after")
    def validate_outcome(self) -> Self:
        if (
            self.results
            and tuple(result.checker for result in self.results) != self.checkers
        ):
            raise ValueError("checker results do not match selection")
        if len(set(self.checkers)) != len(self.checkers):
            raise ValueError("duplicate checker selection")
        if len(set(self.inventory)) != len(self.inventory):
            raise ValueError("duplicate declaration inventory")
        if any(
            len(result.submitted_paths) != len(self.inventory)
            or len(set(result.submitted_paths)) != len(self.inventory)
            for result in self.results
        ):
            raise ValueError("submitted declarations do not cover inventory")
        expected = (
            bool(self.inventory and self.results)
            and not self.errors
            and all(result.passed for result in self.results)
        )
        if self.passed != expected:
            raise ValueError("declaration outcome disagrees with evidence")
        return self


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
    paths: Sequence[Path],
    destination: Path,
    installation_root: Path,
    *,
    preserve_stub_layout: bool = False,
) -> tuple[Path, ...]:
    """Preserve installed module identities and partial-package runtime fallback."""
    if not paths:
        raise ValueError("installed declaration inventory is empty")
    base = installation_root.resolve()
    if not installation_root.is_absolute() or not base.is_dir():
        raise ValueError("installed declaration root must be an absolute directory")
    relative_paths = tuple(path.resolve().relative_to(base) for path in paths)
    stub_packages = {
        Path(*relative.parts[: index + 1])
        for relative in relative_paths
        for index, part in enumerate(relative.parts[:-1])
        if part.endswith("-stubs")
    }
    for package_path in sorted(stub_packages):
        package = base / package_path
        marker = package / "py.typed"
        if not marker.is_file():
            continue
        if preserve_stub_layout:
            marker_parts = tuple(
                part if index == 0 else part.removesuffix("-stubs")
                for index, part in enumerate(package_path.parts)
            )
            snapshot_marker = destination.joinpath(*marker_parts, "py.typed")
            snapshot_marker.parent.mkdir(parents=True, exist_ok=True)
            snapshot_marker.write_bytes(marker.read_bytes())
        if "partial" not in read_utf8_text(marker).splitlines():
            continue
        # PEP 561 partial stubs supplement their installed runtime package.
        # Copy only that package's Python sources, never the checker environment.
        runtime_path = Path(
            *(part.removesuffix("-stubs") for part in package_path.parts)
        )
        runtime = base / runtime_path
        if runtime.is_dir():
            for source in sorted(runtime.rglob("*")):
                if source.is_file() and (
                    source.suffix in {".py", ".pyi"} or source.name == "py.typed"
                ):
                    target = destination / runtime_path / source.relative_to(runtime)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(source.read_bytes())
    copied: list[Path] = []
    for path, relative in zip(paths, relative_paths, strict=True):
        # A foo-stubs distribution supplies the importable foo package. Keep
        # the full package hierarchy, including for a lone nested declaration.
        *parents, filename = relative.parts
        target = destination.joinpath(
            *(
                part
                if preserve_stub_layout and index == 0
                else part.removesuffix("-stubs")
                for index, part in enumerate(parents)
            ),
            filename,
        )
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


def checker_command(
    checker: CheckerName,
    paths: Sequence[Path],
    root: Path,
    target_python: str,
    python_version: str,
) -> list[str]:
    """Build explicit installed-snapshot inputs without consumer exclusions."""
    command = [current_python_executable(), "-m", checker]
    if checker == "pyright":
        return command + [
            "--project",
            str(root / "pyrightconfig.json"),
            "--pythonpath",
            target_python,
            "--outputjson",
        ]
    if checker == "mypy":
        return command + [
            "--strict",
            "--output",
            "json",
            "--config-file",
            str(root / "mypy.ini"),
            "--cache-dir",
            str(root / "mypy-cache"),
            "--python-executable",
            target_python,
            "--python-version",
            python_version,
            "--explicit-package-bases",
            "--namespace-packages",
            *(str(path) for path in paths),
        ]
    return command + [
        "check",
        "--output-format",
        "gitlab",
        "--no-progress",
        "--no-respect-ignore-files",
        "--no-force-exclude",
        "--config-file",
        str(root / "ty.toml"),
        "--project",
        str(root / "ty-declarations"),
        "--extra-search-path",
        str(root / "ty-declarations"),
        "--python",
        target_python,
        "--python-version",
        python_version,
        *(str(path) for path in paths),
    ]


def run_declaration_checker(
    checker: CheckerName,
    paths: Sequence[Path],
    root: Path,
    target_python: str,
    python_version: str,
) -> DeclarationCheckerResult:
    command = checker_command(checker, paths, root, target_python, python_version)
    environment = child_environment(os.environ, current_python_executable())
    if checker == "mypy":
        environment["MYPYPATH"] = str(root / "declarations")
    stdout = stderr = ""
    returncode = 127
    diagnostics: tuple[NativeDiagnostic, ...] = ()
    analyzed_files: int | None = None
    error: str | None = None
    try:
        probe = probe_python_module(current_python_executable(), checker)
        if not probe.available:
            raise ValueError(
                f"selected checker {checker} unavailable: {probe.detail or 'module missing'}"
            )
        result = subprocess.run(
            command,
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
            timeout=180,
        )
        stdout, stderr, returncode = result.stdout, result.stderr, result.returncode
        diagnostics = parse_checker_diagnostics(checker, stdout)
        if checker == "pyright":
            analyzed_files = PyrightReport.model_validate_json(
                stdout
            ).summary.files_analyzed
            validate_declaration_report(stdout, returncode, len(paths))
        elif returncode != 0 or any(item.severity == "error" for item in diagnostics):
            raise ValueError(f"{checker} declaration check failed: exit={returncode}")
    except (OSError, ValueError, subprocess.SubprocessError) as failure:
        error = str(failure)
    return DeclarationCheckerResult(
        checker=checker,
        argv=tuple(command),
        passed=error is None,
        returncode=returncode,
        submitted_paths=tuple(str(path) for path in paths),
        analyzed_files=analyzed_files,
        coverage_kind="native-count" if checker == "pyright" else "explicit-inputs",
        diagnostics=diagnostics,
        stdout=stdout[:MAX_CAPTURE],
        stderr=stderr[:MAX_CAPTURE],
        output_truncated=len(stdout) > MAX_CAPTURE or len(stderr) > MAX_CAPTURE,
        validation_error=error,
    )


def verify_declarations(
    distribution: str, target_python: str, checkers: Sequence[CheckerName]
) -> DeclarationReport:
    """Gather target inventory and run every requested checker, preserving failures."""
    inventory_paths: tuple[str, ...] = ()
    results: tuple[DeclarationCheckerResult, ...] = ()
    errors: tuple[str, ...] = ()
    try:
        if (
            not checkers
            or len(set(checkers)) != len(checkers)
            or any(checker not in DEFAULT_CHECKERS for checker in checkers)
        ):
            raise ValueError("select at least one checker without duplicates")
        target = probe_python(target_python)
        with tempfile.TemporaryDirectory(prefix="alphus-declarations-") as temporary:
            root = Path(temporary).resolve()
            inventory_result = subprocess.run(
                [target.executable, "-I", "-c", INVENTORY_SCRIPT, distribution],
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
            inventory_paths = tuple(str(path) for path in paths)
            snapshot = root / "declarations"
            copied = snapshot_declarations(
                paths, snapshot, Path(inventory.installation_root)
            )
            (root / "pyrightconfig.json").write_text(
                declaration_config(
                    copied, root, target.minor, snapshot
                ).model_dump_json(by_alias=True),
                encoding="utf-8",
            )
            (root / "mypy.ini").write_text("[mypy]\n", encoding="utf-8")
            (root / "ty.toml").write_text(
                '[rules]\ndeprecated = "error"\n', encoding="utf-8"
            )
            ty_copied = (
                snapshot_declarations(
                    paths,
                    root / "ty-declarations",
                    Path(inventory.installation_root),
                    preserve_stub_layout=True,
                )
                if "ty" in checkers
                else ()
            )
            results = tuple(
                run_declaration_checker(
                    checker,
                    ty_copied if checker == "ty" else copied,
                    root,
                    target.executable,
                    target.minor,
                )
                for checker in checkers
            )
    except (OSError, ValueError, subprocess.SubprocessError) as failure:
        errors = (str(failure),)
    return DeclarationReport(
        distribution=distribution,
        checkers=tuple(dict.fromkeys(checkers)),
        inventory=inventory_paths,
        results=results,
        errors=errors,
        passed=bool(inventory_paths and results)
        and not errors
        and all(item.passed for item in results),
    )


def render_human(report: DeclarationReport) -> str:
    """Render the same structured result without dumping native JSON."""
    lines = [
        f"Installed declarations: {report.distribution} ({len(report.inventory)} files)"
    ]
    for result in report.results:
        coverage = (
            f"{result.analyzed_files} analyzed"
            if result.analyzed_files is not None
            else (
                f"{len(result.submitted_paths)} explicit inputs; native analyzed count unavailable"
            )
        )
        lines.append(
            f"{'PASS' if result.passed else 'FAIL'} {result.checker}: {coverage}"
        )
        for diagnostic in result.diagnostics:
            lines.append(
                f"  {diagnostic.path}:{diagnostic.line}: "
                f"{diagnostic.severity}: {diagnostic.message}"
            )
        if result.validation_error:
            lines.append(f"  {result.validation_error}")
        if result.stderr:
            lines.append(result.stderr)
    lines.extend(f"ERROR: {error}" for error in report.errors)
    if report.passed:
        lines.append(
            f"Verified {len(report.inventory)} installed declarations for {report.distribution}"
        )
    return "\n".join(lines)


class DeclarationArgumentParser(argparse.ArgumentParser):
    """Route parse errors through the same versioned result envelope."""

    def error(self, message: str) -> NoReturn:
        raise ValueError(message)


def requested_output(arguments: Sequence[str]) -> str:
    """Recover only the output channel even if required arguments are missing."""
    output = "human"
    for index, argument in enumerate(arguments):
        if argument.startswith("--output="):
            output = argument.removeprefix("--output=")
        elif argument == "--output" and index + 1 < len(arguments):
            output = arguments[index + 1]
    return output


def main(argv: Sequence[str] | None = None) -> int:
    arguments = tuple(sys.argv[1:] if argv is None else argv)
    parser = DeclarationArgumentParser(description=__doc__)
    parser.add_argument("--distribution", required=True)
    parser.add_argument("--target-python", required=True)
    parser.add_argument(
        "--checkers", nargs="+", choices=DEFAULT_CHECKERS, default=DEFAULT_CHECKERS
    )
    parser.add_argument("--output", choices=("human", "json"), default="human")
    output = requested_output(arguments)
    try:
        args = parser.parse_args(arguments)
        report = verify_declarations(
            args.distribution, args.target_python, args.checkers
        )
    except ValueError as failure:
        report = DeclarationReport(
            distribution="", errors=(str(failure),), passed=False
        )
    print(report.model_dump_json() if output == "json" else render_human(report))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
