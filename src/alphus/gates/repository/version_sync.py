"""Check that configured metadata sources publish one matching version."""

from __future__ import annotations

import tomllib
from pathlib import Path

from alphus.config import VersionSource, VersionSyncPolicy
from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import Category, Framework, Scope, rule_tag
from alphus.support.data_access import nested_value, validate_json_value


def _read_version(root: Path, source: VersionSource) -> str | None:
    path = root / source.path
    try:
        path.resolve(strict=True).relative_to(root)
        text = path.read_text(encoding="utf-8")
        value = (
            validate_json_value(text)
            if source.format == "json"
            else tomllib.loads(text)
        )
    except (OSError, ValueError, tomllib.TOMLDecodeError):
        return None
    version = nested_value(value, source.key)
    match version:
        case str() | int() | float():
            return str(version)
        case _:
            return None


def check_version_sync(root: Path, policy: VersionSyncPolicy) -> list[Finding]:
    """Require each available configured version to equal the first source."""
    checkout = root.resolve(strict=True)
    versions = [(source, _read_version(checkout, source)) for source in policy.sources]
    if any(value is None for _, value in versions):
        return []
    reference_source, reference_version = versions[0]
    findings: list[Finding] = []
    for source, version in versions[1:]:
        if version != reference_version:
            findings.append(
                Finding(
                    rule_id=rule_tag(
                        Scope.REPOSITORY,
                        Framework.NONE,
                        Category.METADATA,
                        "version-mismatch",
                    ),
                    path=source.path,
                    message=(
                        f"version {version} differs from {reference_source.path} "
                        f"version {reference_version}"
                    ),
                )
            )
    return findings
