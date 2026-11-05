"""Check Python test directories against configured source package layouts."""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum
from pathlib import Path, PurePosixPath

from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import Category, Framework, Scope, rule_tag
from alphus.policy.test_layout import TestLayoutPair, TestLayoutPolicy


class TestLayoutRuleId(StrEnum):
    """Stable identifiers emitted by Python test-layout checks."""

    ROOT_UNAVAILABLE = rule_tag(
        Scope.REPOSITORY,
        Framework.NONE,
        Category.TESTING,
        "test-layout-root-unavailable",
    )
    MODULE_MISPLACED = rule_tag(
        Scope.REPOSITORY, Framework.NONE, Category.TESTING, "test-module-misplaced"
    )
    DIRECTORY_UNMIRRORED = rule_tag(
        Scope.REPOSITORY, Framework.NONE, Category.TESTING, "test-directory-unmirrored"
    )


def _safe_directory(root: Path, relative: str) -> Path | None:
    candidate = root.joinpath(*PurePosixPath(relative).parts)
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        return None
    if (
        candidate.is_symlink()
        or resolved != candidate
        or not resolved.is_dir()
        or not resolved.is_relative_to(root)
    ):
        return None
    return resolved


def _safe_inventory_paths(
    root: Path, files: Sequence[Path]
) -> tuple[PurePosixPath, ...]:
    safe_paths: set[PurePosixPath] = set()
    for path in files:
        relative = PurePosixPath(path.as_posix())
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or "\\" in relative.as_posix()
        ):
            continue
        candidate = root.joinpath(*relative.parts)
        try:
            resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError, ValueError):
            continue
        if (
            candidate.is_symlink()
            or resolved != candidate
            or not resolved.is_file()
            or not resolved.is_relative_to(root)
        ):
            continue
        safe_paths.add(relative)
    return tuple(sorted(safe_paths))


def _source_directories(
    source_files: Sequence[PurePosixPath],
) -> frozenset[PurePosixPath]:
    directories: set[PurePosixPath] = {PurePosixPath(".")}
    for source in source_files:
        parts = source.parent.parts
        directories.update(
            PurePosixPath(*parts[:index]) for index in range(1, len(parts) + 1)
        )
    return frozenset(directories)


def _source_module_locations(
    source_files: Sequence[PurePosixPath],
) -> dict[str, frozenset[tuple[PurePosixPath, str]]]:
    modules: dict[str, set[tuple[PurePosixPath, str]]] = {}
    for source in source_files:
        if source.name == "__init__.py":
            continue
        location = (source.parent, source.stem)
        modules.setdefault(source.stem, set()).add(location)
        if source.parent.parts:
            flattened = "_".join((*source.parent.parts, source.stem))
            modules.setdefault(flattened, set()).add(location)
    return {name: frozenset(directories) for name, directories in modules.items()}


def _test_module_stem(path: PurePosixPath) -> str | None:
    if not path.name.endswith(".py"):
        return None
    if path.name.startswith("test_"):
        stem = path.stem.removeprefix("test_")
        return stem or None
    if path.name.endswith("_test.py"):
        stem = path.stem.removesuffix("_test")
        return stem or None
    return None


def _is_integration_directory(
    directory: PurePosixPath, integration_roots: Sequence[str]
) -> bool:
    return any(
        directory.is_relative_to(PurePosixPath(integration_root))
        for integration_root in integration_roots
    )


def _reported_path(root_name: str, directory: PurePosixPath, filename: str) -> str:
    path = PurePosixPath(root_name)
    if directory.parts:
        path /= directory
    return (path / filename).as_posix()


def _test_filename(test: PurePosixPath, source_stem: str) -> str:
    if test.name.startswith("test_"):
        return f"test_{source_stem}.py"
    return f"{source_stem}_test.py"


def _check_pair(
    root: Path,
    pair: TestLayoutPair,
    inventory: Sequence[PurePosixPath],
) -> list[Finding]:
    source_root = PurePosixPath(pair.source_root)
    test_root = PurePosixPath(pair.test_root)
    findings: list[Finding] = []
    for configured, role in (
        (pair.source_root, "source"),
        (pair.test_root, "test"),
    ):
        if _safe_directory(root, configured) is None:
            findings.append(
                Finding(
                    rule_id=TestLayoutRuleId.ROOT_UNAVAILABLE,
                    path=configured,
                    severity="error",
                    message=f"configured {role} root is missing or unsafe",
                )
            )
    if any(
        finding.rule_id == TestLayoutRuleId.ROOT_UNAVAILABLE for finding in findings
    ):
        return findings

    source_files = tuple(
        path.relative_to(source_root)
        for path in inventory
        if path.is_relative_to(source_root) and path.suffix == ".py"
    )
    test_files = tuple(
        path.relative_to(test_root)
        for path in inventory
        if path.is_relative_to(test_root)
        and path.suffix == ".py"
        and path.name not in {"__init__.py", "conftest.py"}
        and _test_module_stem(path) is not None
    )
    source_directories = _source_directories(source_files)
    module_locations = _source_module_locations(source_files)

    for test in test_files:
        test_directory = test.parent
        if _is_integration_directory(test_directory, pair.integration_roots):
            continue
        stem = _test_module_stem(test)
        if stem is None:
            continue
        matching_locations = module_locations.get(stem, frozenset())
        if matching_locations:
            matching_directories = {
                directory for directory, _source_stem in matching_locations
            }
            if test_directory not in matching_directories:
                expected = tuple(
                    _reported_path(
                        pair.test_root,
                        directory,
                        _test_filename(test, source_stem),
                    )
                    for directory, source_stem in sorted(
                        matching_locations,
                        key=lambda location: (
                            location[0].as_posix(),
                            location[1],
                        ),
                    )
                )
                findings.append(
                    Finding(
                        rule_id=TestLayoutRuleId.MODULE_MISPLACED,
                        path=(test_root / test).as_posix(),
                        severity="error",
                        message=(
                            "test module is outside the mirrored source package; "
                            f"expected it under {', '.join(repr(path) for path in expected)}"
                        ),
                    )
                )
            continue
        if test_directory == PurePosixPath("."):
            findings.append(
                Finding(
                    rule_id=TestLayoutRuleId.DIRECTORY_UNMIRRORED,
                    path=(test_root / test).as_posix(),
                    severity="error",
                    message=(
                        "root-level test has no matching source module; place "
                        "cross-module tests under an integration root or a mirrored package"
                    ),
                )
            )
        elif test_directory not in source_directories:
            findings.append(
                Finding(
                    rule_id=TestLayoutRuleId.DIRECTORY_UNMIRRORED,
                    path=(test_root / test).as_posix(),
                    severity="error",
                    message=(
                        f"test directory {test_directory.as_posix()!r} does not "
                        "mirror a source package directory; use a mirrored package "
                        "or configured integration root"
                    ),
                )
            )
    return findings


def check_test_layout(
    root: Path,
    files: Sequence[Path],
    policy: TestLayoutPolicy,
) -> list[Finding]:
    """Require package tests to follow source directories or named integration roots."""
    checkout = root.resolve(strict=True)
    if not checkout.is_dir():
        raise ValueError(f"repository root is not a directory: {checkout}")
    inventory = _safe_inventory_paths(checkout, files)
    return [
        finding
        for pair in policy.pairs
        for finding in _check_pair(checkout, pair, inventory)
    ]
