"""Compatibility imports for the runtime-types source gate."""

from alphus.gates.source.runtime_types import (
    TypeCheckVisitor,
    policy_issues,
    type_check_findings,
)

__all__ = [
    "TypeCheckVisitor",
    "policy_issues",
    "type_check_findings",
]
