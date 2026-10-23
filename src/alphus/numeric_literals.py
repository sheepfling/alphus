"""Compatibility imports for the numeric-literals review gate."""

from alphus.gates.review.numeric_literals import (
    NumericLiteralFinding,
    check_numeric_literals,
    numeric_literal_findings,
)

__all__ = [
    "NumericLiteralFinding",
    "check_numeric_literals",
    "numeric_literal_findings",
]
