"""SciPy numeric review has its own catalog and provisional rule identity."""

from __future__ import annotations

from pathlib import Path

import pytest

from alphus.config import NumericLiteralSpec, ScipyConstantsPolicy
from alphus.gates.review.scipy_constants import (
    check_scipy_constants,
    scipy_literal_findings,
)


def _policy(**options: bool) -> ScipyConstantsPolicy:
    return ScipyConstantsPolicy(extensions=(".py",), **options)


def test_physical_and_bidirectional_unit_factors_are_scoped() -> None:
    source = (
        "distance = seconds * 299792458\n"
        "meters = inches * 0.0254\n"
        "inches = meters * 39.37007874015748\n"
        "hours = seconds / 3600\n"
        "seconds = hours * 3600\n"
        "ratio = value * 0.0254\n"
    )

    findings = scipy_literal_findings(source, _policy())

    assert [(finding.line, finding.rule_id) for finding in findings] == [
        (1, "alphus/python/scipy/style/inline-constant"),
        (2, "alphus/python/scipy/style/inline-conversion"),
        (3, "alphus/python/scipy/style/inline-conversion"),
        (4, "alphus/python/scipy/style/inline-conversion"),
        (5, "alphus/python/scipy/style/inline-conversion"),
    ]
    assert "scipy.constants.speed_of_light" in findings[0].message
    assert "scipy.constants.inch" in findings[1].message


def test_catalog_flags_and_explicit_extensions() -> None:
    source = (
        "inches = meters * 39.37007874015748\n"
        "meters = inches * 0.0254\n"
        "distance = seconds * 299792458\n"
        "custom = item * 9.81\n"
    )
    policy = ScipyConstantsPolicy(
        extensions=(".py",),
        physical_constants=False,
        inverse_conversions=False,
        constants=(
            NumericLiteralSpec(
                name="project gravity",
                values=(9.81,),
                replacement="project.GRAVITY",
            ),
        ),
    )

    findings = scipy_literal_findings(source, policy)

    assert [finding.line for finding in findings] == [2, 4]
    assert "project.GRAVITY" in findings[1].message


def test_repository_scan_emits_warning_findings(tmp_path: Path) -> None:
    source = tmp_path / "physics.py"
    source.write_text("energy = frequency * 6.62607015e-34\n", encoding="utf-8")

    findings = check_scipy_constants(tmp_path, [Path("physics.py")], _policy())

    assert len(findings) == 1
    assert findings[0].path == "physics.py"
    assert findings[0].severity == "warning"
    assert findings[0].rule_id == "alphus/python/scipy/style/inline-constant"


def test_scipy_review_accepts_bom_prefixed_python_source(tmp_path: Path) -> None:
    source = tmp_path / "physics.py"
    source.write_bytes(b"\xef\xbb\xbfenergy = frequency * 6.62607015e-34\n")
    findings = check_scipy_constants(tmp_path, [Path("physics.py")], _policy())
    assert len(findings) == 1


@pytest.mark.parametrize(
    ("name", "factor", "token"),
    [
        ("yard", 0.9144, "yards"),
        ("nautical_mile", 1852, "nautical"),
        ("minute", 60, "minutes"),
        ("week", 604800, "weeks"),
        ("year", 31536000, "years"),
        ("Julian_year", 31557600, "julian"),
        ("gram", 0.001, "grams"),
        ("pound", 0.45359237, "pounds"),
        ("ounce", 0.028349523125, "ounces"),
        ("liter", 0.001, "liters"),
        ("atmosphere", 101325, "atmospheres"),
        ("bar", 100000, "bars"),
        ("hectare", 10000, "hectares"),
        ("acre", 4046.8564224, "acres"),
        ("mph", 0.44704, "mph"),
        ("kmh", 1000 / 3600, "kmh"),
        ("knot", 1852 / 3600, "knots"),
    ],
)
def test_added_unit_factors_and_reciprocals(
    name: str, factor: float, token: str
) -> None:
    source = (
        f"direct = reading_{token} * {factor!r}\n"
        f"inverse = reading_{token} * {1 / factor!r}\n"
    )
    findings = scipy_literal_findings(source, _policy())
    assert [finding.line for finding in findings] == [1, 2]
    assert all(f"scipy.constants.{name}" in finding.message for finding in findings)


def test_new_physical_constants_and_ambiguous_charge_are_reviewed() -> None:
    source = (
        "force = mass * 9.80665\n"
        "coulombs = electrons * 1.602176634e-19\n"
        "energy = moles * 8.31446261815324 * temperature\n"
    )
    findings = scipy_literal_findings(source, _policy())
    assert [finding.line for finding in findings] == [1, 2, 3]
    assert "scipy.constants.g" in findings[0].message
    assert "electron_volt" in findings[1].message
    assert "check units" in findings[1].message
    assert "scipy.constants.gas_constant" in findings[2].message


def test_same_numeric_factor_uses_unit_context_without_double_reporting() -> None:
    source = (
        "weight = reading_grams * 0.001\n"
        "capacity = reading_liters * 0.001\n"
        "unlabelled = reading * 0.001\n"
    )
    findings = scipy_literal_findings(source, _policy())
    assert [finding.line for finding in findings] == [1, 2]
    assert "scipy.constants.gram" in findings[0].message
    assert "scipy.constants.liter" in findings[1].message


def test_expanded_catalog_is_exact_and_configurable() -> None:
    source = (
        "seconds = elapsed_minutes * 60\n"
        "liters = volume * 0.001\n"
        "seconds = minutes * 0.016666666\n"
        "force = mass * 9.80665\n"
    )
    policy = _policy(physical_constants=False, unit_conversions=False)
    assert scipy_literal_findings(source, policy) == []
    findings = scipy_literal_findings(source, _policy(inverse_conversions=False))
    assert [finding.line for finding in findings] == [1, 2, 4]
