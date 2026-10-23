"""Compatibility imports for the cli-policy source gate."""

from alphus.gates.source.cli_policy import (
    call_name,
    has_main_guard,
    imported_names,
    node_cli_files,
    policy_issues,
    python_cli_issues,
)

__all__ = [
    "call_name",
    "has_main_guard",
    "imported_names",
    "node_cli_files",
    "policy_issues",
    "python_cli_issues",
]
