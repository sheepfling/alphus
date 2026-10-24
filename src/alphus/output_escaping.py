"""Compatibility imports for the output-escaping source gate."""

from alphus.gates.languages.javascript.output_escaping import (
    escape_findings as js_escape_findings,
)
from alphus.gates.languages.python.output_escaping import (
    escape_findings as python_escape_findings,
)
from alphus.gates.source.output_escaping import check_output_escaping

__all__ = [
    "check_output_escaping",
    "js_escape_findings",
    "python_escape_findings",
]
