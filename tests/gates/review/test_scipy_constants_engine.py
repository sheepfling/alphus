"""SciPy numeric review has its own catalog and provisional rule identity."""

from __future__ import annotations

from pathlib import Path

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
