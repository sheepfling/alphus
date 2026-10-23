"""Advisory SciPy constant and unit-factor review for Python arithmetic.

The small built-in catalog uses exact SI definitions and SciPy's public names.
It does not import SciPy or infer dimensions from source code.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from alphus.config import NumericLiteralSpec, ScipyConstantsPolicy
from alphus.contracts.findings import Finding
from alphus.gates.review.numeric_engine import (
    NumericLiteralFinding,
    scan_numeric_literals,
)
from alphus.support.inventory import matches_path

_PHYSICAL_CONSTANTS = (
    NumericLiteralSpec(
        name="speed of light",
        values=(299792458,),
        replacement="scipy.constants.speed_of_light (m/s)",
    ),
    NumericLiteralSpec(
        name="Planck constant",
        values=(6.62607015e-34,),
        replacement="scipy.constants.Planck (J s)",
    ),
    NumericLiteralSpec(
        name="Boltzmann constant",
        values=(1.380649e-23,),
        replacement="scipy.constants.Boltzmann (J/K)",
    ),
    NumericLiteralSpec(
        name="Avogadro constant",
        values=(6.02214076e23,),
        replacement="scipy.constants.Avogadro (1/mol)",
    ),
)

# Each factor is the number of SI units in one named unit.
_UNIT_FACTORS = (
    ("inch", 0.0254, ("inch", "inches", "meter", "meters", "metre", "metres")),
    ("foot", 0.3048, ("foot", "feet", "meter", "meters", "metre", "metres")),
    ("mile", 1609.344, ("mile", "miles", "meter", "meters", "metre", "metres")),
    ("hour", 3600, ("hour", "hours", "second", "seconds")),
    ("day", 86400, ("day", "days", "second", "seconds")),
)


def _unit_specs(include_inverses: bool) -> tuple[NumericLiteralSpec, ...]:
    """Build exact direct and reciprocal factors from one reviewed catalog."""
    return tuple(
        NumericLiteralSpec(
            name=f"{unit} to SI",
            values=(factor, 1 / factor) if include_inverses else (factor,),
            kind="conversion",
            replacement=f"scipy.constants.{unit} or its reciprocal (check direction)",
            name_tokens=tokens,
        )
        for unit, factor, tokens in _UNIT_FACTORS
    )


def scipy_literal_findings(
    source: str, policy: ScipyConstantsPolicy
) -> list[NumericLiteralFinding]:
    """Review exact configured SciPy values in arithmetic source expressions."""
    specs = (
        *(_PHYSICAL_CONSTANTS if policy.physical_constants else ()),
        *(_unit_specs(policy.inverse_conversions) if policy.unit_conversions else ()),
        *policy.constants,
    )
    return scan_numeric_literals(source, specs, framework="scipy")


def check_scipy_constants(
    root: Path, paths: Iterable[Path], policy: ScipyConstantsPolicy
) -> list[Finding]:
    """Return advisory SciPy findings for the selected Python inventory."""
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
            for finding in scipy_literal_findings(
                path.read_text(encoding="utf-8-sig"), policy
            )
        )
    return findings
