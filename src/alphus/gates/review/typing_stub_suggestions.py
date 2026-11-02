"""Conservative, opt-in advice for explicitly mapped third-party stubs."""

from __future__ import annotations

import ast
import sys
import tomllib
from collections.abc import Iterable
from importlib import metadata
from pathlib import Path, PurePosixPath
from typing import Any, cast

from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import Version

from alphus.config import TypingStubCandidate, TypingStubSuggestionPolicy
from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import Category, Framework, Scope, rule_tag
from alphus.support.source_text import read_utf8_text

_RULE_ID = rule_tag(
    Scope.PYTHON, Framework.NONE, Category.DEPENDENCIES, "typing-stub-suggestion"
)

# Verified from typeshed's PyYAML metadata and current PyPI package metadata on
# 2026-11-02, plus scipy-stubs' official project metadata.
_BUILTIN_CANDIDATES = (
    TypingStubCandidate(
        import_name="yaml",
        runtime_distribution="PyYAML",
        stub_distribution="types-PyYAML",
        supported_runtime_versions="==6.0.*",
        supported_python_versions=">=3.10,<4",
        package_path="yaml",
    ),
    TypingStubCandidate(
        import_name="scipy",
        runtime_distribution="scipy",
        stub_distribution="scipy-stubs",
        supported_runtime_versions="==1.18.1.*",
        supported_python_versions=">=3.12,<4",
        package_path="scipy",
        stub_version_specifier="==1.18.1.*",
    ),
)


def _imports(source: str) -> set[str]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    found: set[str] = set()
    for node in ast.walk(tree):
        match node:
            case ast.Import(names=names):
                found.update(alias.name for alias in names)
            case ast.ImportFrom(module=str() as module):
                found.add(module)
            case _:
                continue
    return found


def _requirements(values: object) -> list[Requirement]:
    match values:
        case list():
            pass
        case _:
            return []
    result: list[Requirement] = []
    for value in cast(list[object], values):
        match value:
            case str() as requirement:
                try:
                    result.append(Requirement(requirement))
                except InvalidRequirement:
                    continue
            case _:
                continue
    return result


def check_typing_stub_suggestions(
    root: Path, paths: Iterable[Path], policy: TypingStubSuggestionPolicy
) -> list[Finding]:
    """Suggest only from explicit mapping, metadata, and configured version bounds."""
    checkout = root.resolve(strict=True)
    observed: set[str] = set()
    for relative in sorted(paths):
        if relative.suffix != ".py" or not (checkout / relative).is_file():
            continue
        try:
            observed.update(_imports(read_utf8_text(checkout / relative)))
        except (OSError, UnicodeError):
            continue
    try:
        manifest_path = checkout / policy.dependency_file
        manifest_path.resolve(strict=True).relative_to(checkout)
        manifest = tomllib.loads(read_utf8_text(manifest_path))
    except (OSError, ValueError, tomllib.TOMLDecodeError):
        return [
            Finding(
                rule_id=_RULE_ID,
                path=policy.dependency_file,
                message=(
                    "Stub suggestions were not evaluated because the configured "
                    "dependency manifest could not be read."
                ),
                severity=policy.severity,
            )
        ]

    project_value = manifest.get("project", {})
    match project_value:
        case dict():
            # opaque-boundary: TOML project tables contain heterogeneous fields before validation.
            project: dict[str, Any] = cast(dict[str, Any], project_value)
        case _:
            project = {}
    optional_value = project.get("optional-dependencies", {})
    match optional_value:
        case dict():
            # opaque-boundary: TOML optional groups are heterogeneous before validation.
            optional: dict[str, Any] = cast(dict[str, Any], optional_value)
        case _:
            optional = {}
    missing_groups = [name for name in policy.typing_groups if name not in optional]
    if missing_groups:
        return [
            Finding(
                rule_id=_RULE_ID,
                path=policy.dependency_file,
                message=(
                    "Stub suggestions were not evaluated: configured PEP 621 typing "
                    f"group(s) are absent: {', '.join(missing_groups)}."
                ),
                severity=policy.severity,
            )
        ]
    runtime_declared = _requirements(project.get("dependencies", []))
    environment = {"python_version": ".".join(map(str, sys.version_info[:2]))}
    runtime_declared = [
        req
        for req in runtime_declared
        if req.marker is None or req.marker.evaluate(environment)
    ]
    selected = [
        req for name in policy.typing_groups for req in _requirements(optional[name])
    ]
    selected = [
        req
        for req in selected
        if req.marker is None or req.marker.evaluate(environment)
    ]
    findings: list[Finding] = []
    python_version = Version(".".join(map(str, sys.version_info[:3])))
    candidates = {
        item.import_name: item
        for item in (_BUILTIN_CANDIDATES if policy.builtin_catalog else ())
    }
    candidates.update({item.import_name: item for item in policy.candidates})
    for import_name in policy.disabled_imports:
        candidates.pop(import_name, None)
    for candidate in candidates.values():
        if not any(
            name == candidate.import_name
            or name.startswith(candidate.import_name + ".")
            for name in observed
        ):
            continue
        runtime_key = canonicalize_name(candidate.runtime_distribution)
        stub_key = canonicalize_name(candidate.stub_distribution)
        runtime_requirement = next(
            (
                req
                for req in runtime_declared
                if canonicalize_name(req.name) == runtime_key
            ),
            None,
        )
        try:
            runtime = metadata.distribution(candidate.runtime_distribution)
            runtime_version = Version(runtime.version)
        except (metadata.PackageNotFoundError, ValueError):
            findings.append(
                Finding(
                    rule_id=_RULE_ID,
                    path=policy.dependency_file,
                    message=(
                        f"Import {candidate.import_name!r} was observed, but installed "
                        f"metadata for {candidate.runtime_distribution} is unavailable; "
                        "stub need was not evaluated."
                    ),
                    severity=policy.severity,
                )
            )
            continue
        if runtime_requirement is None or not runtime_requirement.specifier.contains(
            runtime_version, prereleases=True
        ):
            continue
        runtime_supported = SpecifierSet(candidate.supported_runtime_versions).contains(
            runtime_version, prereleases=True
        )
        python_supported = SpecifierSet(candidate.supported_python_versions).contains(
            python_version, prereleases=True
        )
        if not runtime_supported or not python_supported:
            if candidate in _BUILTIN_CANDIDATES:
                findings.append(
                    Finding(
                        rule_id=_RULE_ID,
                        path=policy.dependency_file,
                        message=(
                            f"The built-in {candidate.stub_distribution} mapping for "
                            f"{candidate.runtime_distribution} is verified only for "
                            f"runtime {candidate.supported_runtime_versions} and Python "
                            f"{candidate.supported_python_versions}; installed runtime "
                            f"{runtime_version} under Python {python_version} is outside "
                            "that verified range, so no stub recommendation was made."
                        ),
                        severity=policy.severity,
                    )
                )
            continue
        package_path = PurePosixPath(
            candidate.package_path or candidate.import_name.split(".")[0]
        )
        package_parts = package_path.parts
        runtime_files = runtime.files
        if runtime_files is None:
            findings.append(
                Finding(
                    rule_id=_RULE_ID,
                    path=policy.dependency_file,
                    message=(
                        f"Installed files for {candidate.runtime_distribution} could "
                        "not be inspected; bundled typing support and stub need were "
                        "not evaluated."
                    ),
                    severity=policy.severity,
                )
            )
            continue
        package_files = [
            item
            for item in runtime_files
            if item.parts[: len(package_parts)] == package_parts
        ]
        if any(
            item.name == "py.typed" or item.suffix == ".pyi" for item in package_files
        ):
            continue
        declared = next(
            (req for req in selected if canonicalize_name(req.name) == stub_key), None
        )
        if declared is not None:
            continue
        locations = sorted(
            name
            for name in observed
            if name == candidate.import_name
            or name.startswith(candidate.import_name + ".")
        )
        findings.append(
            Finding(
                rule_id=_RULE_ID,
                path=policy.dependency_file,
                message=(
                    f"{', '.join(locations)} imports resolve to declared "
                    f"{candidate.runtime_distribution} {runtime_version}; no inline "
                    f"py.typed or bundled .pyi files were found at {package_path}, "
                    f"and {candidate.stub_distribution}"
                    f"{candidate.stub_version_specifier or ''} is not declared in "
                    f"typing group(s) {', '.join(policy.typing_groups)}. Consider "
                    f"verifying and declaring it for {', '.join(policy.checkers)}."
                ),
                severity=policy.severity,
            )
        )
    return findings
