"""Advisory SciPy constant and unit-factor review for Python arithmetic.

The small built-in catalog uses exact SI definitions and SciPy's public names.
It does not import SciPy or infer dimensions from source code.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from alphus.config import NumericLiteralSpec, ScipyConstantsPolicy
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

# Keep reviewed defaults in declarative, version-independent registries. Policy
# flags select groups and `constants` adds consumer-owned entries without loading
# SciPy at runtime.
_SCIPY_CONSTANTS_REFERENCE = "https://docs.scipy.org/doc/scipy/reference/constants.html"
_BUILTIN_PHYSICAL_CONSTANTS = (
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
    NumericLiteralSpec(
        name="molar gas constant",
        values=(8.31446261815324,),
        replacement="scipy.constants.R (J mol^-1 K^-1)",
    ),
    NumericLiteralSpec(
        name="Faraday constant",
        values=(96485.33212331001,),
        replacement='scipy.constants.value("Faraday constant") (C mol^-1)',
    ),
    NumericLiteralSpec(
        name="atomic mass constant",
        values=(1.66053906892e-27,),
        replacement="scipy.constants.atomic_mass (kg)",
    ),
)

# Each factor is the number of SI units in one named unit.
_BUILTIN_UNIT_FACTORS = (
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
        for unit, factor, tokens in _BUILTIN_UNIT_FACTORS
    )


def scipy_literal_findings(
    source: str, policy: ScipyConstantsPolicy
) -> list[NumericLiteralFinding]:
    """Review exact configured SciPy values in arithmetic source expressions."""
    builtin_specs = (
        *(_BUILTIN_PHYSICAL_CONSTANTS if policy.physical_constants else ()),
        *(_unit_specs(policy.inverse_conversions) if policy.unit_conversions else ()),
    )
    occurrences = scan_python_numeric_occurrences(source)
    findings = match_numeric_occurrences(
        occurrences,
        NumericCatalog(
            realm="scipy",
            framework=Framework.SCIPY,
            provenance=_SCIPY_CONSTANTS_REFERENCE,
            specs=builtin_specs,
        ),
        scope=Scope.PYTHON,
    )
    if policy.constants:
        findings.extend(
            match_numeric_occurrences(
                occurrences,
                NumericCatalog(
                    realm="consumer",
                    framework=Framework.SCIPY,
                    provenance=None,
                    specs=policy.constants,
                ),
                scope=Scope.PYTHON,
            )
        )
    return sorted(set(findings))


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
            for finding in scipy_literal_findings(read_python_source(path), policy)
        )
    return findings
