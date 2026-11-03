"""Inventory CLI policy findings across the configured source languages."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from alphus.config import CliPolicy
from alphus.contracts.cli_policy import CliPolicyFinding, CliPolicyReport
from alphus.gates.languages.javascript.cli_policy import node_cli_files
from alphus.gates.languages.python.cli_policy import (
    python_cli_findings,
    python_cli_findings_for_sources,
    python_cli_issues,
)
from alphus.support.inventory import matches_path
from alphus.support.source_text import read_python_source

__all__ = [
    "CliPolicyFinding",
    "CliPolicyReport",
    "policy_findings",
    "policy_issues",
    "python_cli_findings",
    "python_cli_issues",
    "selected_policy_sources",
]


def selected_policy_sources(
    root: Path, paths: Iterable[Path], policy: CliPolicy
) -> tuple[list[Path], list[Path]]:
    """Resolve Python and Node source files actually inspected by CLI policy."""
    checkout = root.resolve(strict=True)
    authored = [path for path in paths if (checkout / path).is_file()]
    python_sources = [
        relative
        for relative in authored
        if relative.suffix.lower() in policy.python.extensions
        and not any(
            matches_path(relative.as_posix(), exclusion)
            for exclusion in policy.python.exclude
        )
    ]
    node_sources = (
        sorted(
            node_cli_files(checkout, authored, policy.node), key=lambda p: p.as_posix()
        )
        if policy.node is not None
        else []
    )
    return python_sources, node_sources


def policy_findings(
    root: Path, paths: Iterable[Path], policy: CliPolicy
) -> CliPolicyReport:
    """Inventory authored endpoints while retaining contract/style classification."""
    checkout = root.resolve(strict=True)
    python_sources, node_sources = selected_policy_sources(checkout, paths, policy)
    sources = {
        relative: read_python_source(checkout / relative) for relative in python_sources
    }
    findings = list(python_cli_findings_for_sources(sources, policy.python))
    if policy.node is not None:
        findings.extend(
            CliPolicyFinding(
                policy.node_endpoint_message,
                endpoint=relative.as_posix(),
            )
            for relative in node_sources
        )
    return CliPolicyReport(tuple(findings))


def policy_issues(root: Path, paths: Iterable[Path], policy: CliPolicy) -> list[str]:
    """Compatibility adapter for callers that still consume message lists."""
    return policy_findings(root, paths, policy).legacy_messages()
