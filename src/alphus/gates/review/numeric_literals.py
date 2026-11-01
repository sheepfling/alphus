"""Conservative warnings for explicit math constants used in arithmetic.

Matching an exact literal suggests review; it does not establish meaning or
correctness. Consumer constants and factors require explicit configuration.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from alphus.config import NumericLiteralPolicy, NumericLiteralSpec
from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import Framework, Scope
from alphus.gates.review.numeric_engine import (
    NumericCatalog,
    NumericLiteralFinding,
    match_numeric_occurrences,
)
from alphus.gates.review.numeric_python import scan_python_numeric_occurrences
from alphus.support.inventory import matches_path
from alphus.support.source_text import read_python_source

_MATH_CONSTANTS = (
    NumericLiteralSpec(
        name="pi",
        values=(3.14, 3.14159, 3.141592653589793),
        replacement="math.pi",
    ),
    NumericLiteralSpec(
        name="e",
        values=(2.71828, 2.718281828459045),
        replacement="math.e",
    ),
    NumericLiteralSpec(
        name="tau",
        values=(6.28318, 6.283185307179586),
        replacement="math.tau",
    ),
)


def numeric_literal_findings(
    source: str, policy: NumericLiteralPolicy
) -> list[NumericLiteralFinding]:
    """Review exact configured literals in arithmetic without guessing dimensions."""
    occurrences = scan_python_numeric_occurrences(source)
    findings: list[NumericLiteralFinding] = []
    if policy.math_constants:
        findings.extend(
            match_numeric_occurrences(
                occurrences,
                NumericCatalog(
                    realm="numeric-literals",
                    framework=Framework.NONE,
                    provenance="https://docs.python.org/3/library/math.html#constants",
                    specs=_MATH_CONSTANTS,
                ),
                scope=Scope.PYTHON,
            )
        )
    if policy.constants:
        findings.extend(
            match_numeric_occurrences(
                occurrences,
                NumericCatalog(
                    realm="consumer",
                    framework=Framework.NONE,
                    provenance=None,
                    specs=policy.constants,
                ),
                scope=Scope.PYTHON,
            )
        )
    return sorted(set(findings))


def check_numeric_literals(
    root: Path, paths: Iterable[Path], policy: NumericLiteralPolicy
) -> list[Finding]:
    """Return advisory findings for Python files in the caller's selected scope."""
    findings: list[Finding] = []
    checkout = root.resolve(strict=True)
    for relative in sorted(paths):
        name = relative.as_posix()
        if relative.suffix.lower() not in policy.extensions or any(
            matches_path(name, pattern) for pattern in policy.exclude
        ):
            continue
        path = checkout / relative
        if not path.is_file():
            continue
        findings.extend(
            Finding(
                rule_id=finding.rule_id,
                path=name,
                line=finding.line,
                message=finding.message,
                severity="warning",
            )
            for finding in numeric_literal_findings(read_python_source(path), policy)
        )
    return findings
