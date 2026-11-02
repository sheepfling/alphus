"""Conservative, opt-in advice for explicitly mapped third-party stubs."""

from __future__ import annotations

import ast
import sys
import tomllib
from collections.abc import Iterable
from importlib import metadata
from pathlib import Path
from typing import Any, cast

from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import Version

from alphus.config import TypingStubSuggestionPolicy
from alphus.contracts.findings import Finding


def _imports(source: str) -> set[str]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def _requirements(values: object) -> list[Requirement]:
    if not isinstance(values, list):
        return []
    result: list[Requirement] = []
    for value in cast(list[object], values):
        if isinstance(value, str):
            try:
                result.append(Requirement(value))
            except InvalidRequirement:
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
            observed.update(_imports((checkout / relative).read_text(encoding="utf-8")))
        except (OSError, UnicodeError):
            continue
    try:
        manifest_path = checkout / policy.dependency_file
        manifest_path.resolve(strict=True).relative_to(checkout)
        manifest = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, tomllib.TOMLDecodeError):
        return [
            Finding(
                rule_id="alphus/python/none/dependencies/typing-stub-suggestion",
                path=policy.dependency_file,
                message="Stub suggestions were not evaluated because the configured dependency manifest could not be read.",
                severity=policy.severity,
            )
        ]

    project_value = manifest.get("project", {})
    project: dict[str, Any] = (
        cast(dict[str, Any], project_value) if isinstance(project_value, dict) else {}
    )
    optional_value = project.get("optional-dependencies", {})
    optional: dict[str, Any] = (
        cast(dict[str, Any], optional_value) if isinstance(optional_value, dict) else {}
    )
    missing_groups = [name for name in policy.typing_groups if name not in optional]
    if missing_groups:
        return [
            Finding(
                rule_id="alphus/python/none/dependencies/typing-stub-suggestion",
                path=policy.dependency_file,
                message=f"Stub suggestions were not evaluated: configured PEP 621 typing group(s) are absent: {', '.join(missing_groups)}.",
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
    for candidate in policy.candidates:
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
                    rule_id="alphus/python/none/dependencies/typing-stub-suggestion",
                    path=policy.dependency_file,
                    message=f"Import {candidate.import_name!r} was observed, but installed metadata for {candidate.runtime_distribution} is unavailable; stub need was not evaluated.",
                    severity=policy.severity,
                )
            )
            continue
        if runtime_requirement is None or not runtime_requirement.specifier.contains(
            runtime_version, prereleases=True
        ):
            continue
        if not SpecifierSet(candidate.supported_runtime_versions).contains(
            runtime_version, prereleases=True
        ) or not SpecifierSet(candidate.supported_python_versions).contains(
            python_version, prereleases=True
        ):
            continue
        package_path = candidate.package_path or candidate.import_name.split(".")[0]
        runtime_files = runtime.files
        if runtime_files is None:
            findings.append(
                Finding(
                    rule_id="alphus/python/none/dependencies/typing-stub-suggestion",
                    path=policy.dependency_file,
                    message=f"Installed files for {candidate.runtime_distribution} could not be inspected; bundled typing support and stub need were not evaluated.",
                    severity=policy.severity,
                )
            )
            continue
        package_files = [
            item
            for item in runtime_files
            if item.as_posix().startswith(package_path + "/")
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
                rule_id="alphus/python/none/dependencies/typing-stub-suggestion",
                path=policy.dependency_file,
                message=f"{', '.join(locations)} imports resolve to declared {candidate.runtime_distribution} {runtime_version}; no inline py.typed or bundled .pyi files were found at {package_path}/, and {candidate.stub_distribution} is not declared in typing group(s) {', '.join(policy.typing_groups)}. Consider verifying and declaring it for {', '.join(policy.checkers)}.",
                severity=policy.severity,
            )
        )
    return findings
