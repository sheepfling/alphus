"""Smoke test importability of every module in selected installed packages."""

from __future__ import annotations

import argparse
import keyword
import os
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from alphus.support.python_runtime import current_python_executable


@dataclass(frozen=True, slots=True)
class ModuleInventory:
    """Import names and source-layout problems for selected packages."""

    modules: tuple[str, ...]
    issues: tuple[str, ...]


def _valid_component(value: str) -> bool:
    return value.isidentifier() and not keyword.iskeyword(value)


def discover_modules(
    source_root: Path, packages: Sequence[str] | None = None
) -> ModuleInventory:
    """Map every Python file in regular packages to its qualified import name."""
    root = source_root.resolve(strict=True)
    modules: set[str] = set()
    issues: set[str] = set()
    if packages is None:
        discovered: set[str] = set()
        for file in root.rglob("*.py"):
            relative = file.relative_to(root)
            if len(relative.parts) == 1:
                issues.add(f"Python file is outside a package: {relative.as_posix()}")
            else:
                discovered.add(relative.parts[0])
        packages = tuple(sorted(discovered))
    for package in packages:
        parts = tuple(package.split("."))
        if not all(_valid_component(part) for part in parts):
            issues.add(f"invalid package name: {package!r}")
            continue
        package_dir = root.joinpath(*parts)
        if not package_dir.is_dir():
            issues.add(f"package directory is missing: {package_dir}")
            continue
        for file in sorted(package_dir.rglob("*.py")):
            if not file.is_file():
                continue
            relative = file.relative_to(root)
            parent_parts = relative.parts[:-1]
            for depth in range(1, len(parent_parts) + 1):
                directory = root.joinpath(*parent_parts[:depth])
                if not (directory / "__init__.py").is_file():
                    issues.add(
                        f"missing package initializer: {directory / '__init__.py'}"
                    )
            module_parts = (
                parent_parts
                if file.name == "__init__.py"
                else (*parent_parts, file.stem)
            )
            if not all(_valid_component(part) for part in module_parts):
                issues.add(f"invalid module path: {relative.as_posix()}")
                continue
            modules.add(".".join(module_parts))
        if not (package_dir / "__init__.py").is_file():
            issues.add(f"missing package initializer: {package_dir / '__init__.py'}")
    if not modules:
        issues.add("no Python modules found in the selected packages")
    return ModuleInventory(
        modules=tuple(sorted(modules, key=lambda name: (name.count("."), name))),
        issues=tuple(sorted(issues)),
    )


def import_failures(
    source_root: Path, modules: Sequence[str], *, timeout_seconds: int = 20
) -> tuple[str, ...]:
    """Import each module in a fresh interpreter outside the source directory."""
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    failures: list[str] = []
    command = (
        "import importlib, sys; "
        "importlib.import_module(sys.argv[1]); "
        "print('__ALPHUS_IMPORT_COMPLETE__')"
    )
    for module in modules:
        try:
            result = subprocess.run(
                [current_python_executable(), "-c", command, module],
                capture_output=True,
                text=True,
                cwd=source_root.parent,
                env=environment,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired:
            failures.append(f"{module}: import exceeded {timeout_seconds} seconds")
            continue
        except OSError as error:
            failures.append(f"{module}: could not start Python: {error}")
            continue
        if (
            result.returncode != 0
            or not result.stdout.splitlines()
            or result.stdout.splitlines()[-1] != "__ALPHUS_IMPORT_COMPLETE__"
        ):
            detail = (result.stderr or result.stdout).strip().splitlines()
            reason = detail[-1] if detail else f"exit {result.returncode}"
            failures.append(f"{module}: {reason}")
    return tuple(failures)


def main(argv: Sequence[str] | None = None) -> int:
    """Report missing packages, missing modules, and import-time exceptions."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--package", action="append")
    parser.add_argument("--timeout-seconds", type=int, default=20)
    options = parser.parse_args(argv)
    if options.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be positive")
    try:
        inventory = discover_modules(options.source_root, options.package)
    except OSError as error:
        print(f"Python import smoke: {error}", file=sys.stderr)
        return 2
    failures = (
        *inventory.issues,
        *import_failures(
            options.source_root.resolve(strict=True),
            inventory.modules,
            timeout_seconds=options.timeout_seconds,
        ),
    )
    for failure in failures:
        print(f"FAIL {failure}")
    if failures:
        print(
            f"Python import smoke: {len(failures)} issue(s) across "
            f"{len(inventory.modules)} module(s)"
        )
        return 1
    print(f"Python import smoke: {len(inventory.modules)} module(s) imported")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
