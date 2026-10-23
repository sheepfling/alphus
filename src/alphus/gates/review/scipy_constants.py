"""Advisory SciPy constant and unit-factor review for Python arithmetic.

The curated built-in catalog uses exact definitions and SciPy's public names.
It does not import SciPy or infer dimensions from source code.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from alphus.config import NumericLiteralSpec, ScipyConstantsPolicy
from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import Framework
from alphus.gates.review.numeric_catalog import NumericLiteralFinding
from alphus.gates.review.numeric_engine import scan_numeric_literals
from alphus.support.inventory import matches_path
from alphus.support.source_text import read_python_source

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
    NumericLiteralSpec(
        name="standard gravity",
        values=(9.80665,),
        replacement="scipy.constants.g (m/s^2)",
    ),
    NumericLiteralSpec(
        name="elementary charge or electron volt",
        values=(1.602176634e-19,),
        replacement="scipy.constants.elementary_charge (C) or electron_volt (J); check units",
    ),
    NumericLiteralSpec(
        name="molar gas constant",
        values=(8.31446261815324,),
        replacement="scipy.constants.gas_constant (J/(mol K))",
    ),
)

# Exact definitions or factors calculated from them; each is SI units per named
# unit. A unit word in the expression or enclosing function limits collisions
# such as gram/liter (both 0.001) and ubiquitous factors such as 60 or 1000.
_UNIT_FACTORS = (
    ("inch", 0.0254, ("inch", "inches", "meter", "meters", "metre", "metres")),
    ("foot", 0.3048, ("foot", "feet", "meter", "meters", "metre", "metres")),
    ("yard", 0.9144, ("yard", "yards", "meter", "meters", "metre", "metres")),
    ("mile", 1609.344, ("mile", "miles", "meter", "meters", "metre", "metres")),
    ("nautical_mile", 1852, ("nautical", "meter", "meters", "metre", "metres")),
    ("minute", 60, ("minute", "minutes", "second", "seconds")),
    ("hour", 3600, ("hour", "hours", "second", "seconds")),
    ("day", 86400, ("day", "days", "second", "seconds")),
    ("week", 604800, ("week", "weeks", "second", "seconds")),
    ("year", 31536000, ("year", "years", "second", "seconds")),
    ("Julian_year", 31557600, ("julian", "second", "seconds")),
    ("gram", 0.001, ("gram", "grams", "kilogram", "kilograms")),
    ("pound", 0.45359237, ("pound", "pounds", "kilogram", "kilograms")),
    ("ounce", 0.028349523125, ("ounce", "ounces", "kilogram", "kilograms")),
    ("liter", 0.001, ("liter", "liters", "litre", "litres", "volume")),
    ("atmosphere", 101325, ("atmosphere", "atmospheres", "pascal", "pascals")),
    ("bar", 100000, ("bar", "bars", "pascal", "pascals")),
    ("hectare", 10000, ("hectare", "hectares", "acres")),
    ("acre", 4046.8564224, ("acre", "acres", "hectares")),
    ("mph", 0.44704, ("mph", "miles", "speed", "velocity")),
    ("kmh", 1000 / 3600, ("kmh", "kph", "kilometers", "kilometres")),
    ("knot", 1852 / 3600, ("knot", "knots", "nautical")),
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
    return scan_numeric_literals(source, specs, framework=Framework.SCIPY)


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
