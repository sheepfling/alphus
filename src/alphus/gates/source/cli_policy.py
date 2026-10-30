"""Route CLI convention checks to the owning source language."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from alphus.config import CliPolicy
from alphus.gates.languages.javascript.cli_policy import node_cli_files
from alphus.gates.languages.python.cli_policy import python_cli_issues
from alphus.support.inventory import matches_path
from alphus.support.source_text import read_python_source


def policy_issues(root: Path, paths: Iterable[Path], policy: CliPolicy) -> list[str]:
    """Inventory all authored runnable commands without exemptions."""
    checkout = root.resolve(strict=True)
    authored = [path for path in paths if (checkout / path).is_file()]
    issues: list[str] = []
    for relative in authored:
        if relative.suffix.lower() not in policy.python.extensions or any(
            matches_path(relative.as_posix(), exclusion)
            for exclusion in policy.python.exclude
        ):
            continue
        source = read_python_source(checkout / relative)
        for issue in python_cli_issues(source, policy.python):
            issues.append(f"{relative.as_posix()}: {issue}")
    if policy.node is not None:
        for relative in sorted(node_cli_files(checkout, authored, policy.node)):
            issues.append(f"{relative.as_posix()}: {policy.node_endpoint_message}")
    return issues
