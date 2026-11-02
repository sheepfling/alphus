"""pyproj numeric review has a separate contextual WGS 84 catalog."""

from __future__ import annotations

from pathlib import Path

from alphus.config import PyprojConstantsPolicy
from alphus.gates.review.pyproj_constants import (
    check_pyproj_constants,
    pyproj_literal_findings,
)


def _policy(**options: bool) -> PyprojConstantsPolicy:
    return PyprojConstantsPolicy(extensions=(".py",), **options)


def test_wgs84_values_are_flagged_in_pyproj_calls_and_named_arithmetic() -> None:
    source = (
        "from pyproj import Geod\n"
        'geod = Geod(ellps="WGS84", a=6378137, rf=298.257223563)\n'
        "minor_axis = axis_wgs84 * 6356752.314245179\n"
        "semi_major_axis_wgs84 = 6378137\n"
        "UNRELATED = 6378137\n"
        "unrelated = value * 6378137\n"
    )

    findings = pyproj_literal_findings(source, _policy())

    assert [finding.line for finding in findings] == [2, 2, 3, 4]
    assert all(
        finding.rule_id == "alphus/python/pyproj/style/inline-constant"
        for finding in findings
    )
    messages = [finding.message for finding in findings]
    assert any("semi_major_metre" in message for message in messages)
    assert any("inverse_flattening" in message for message in messages)
    assert any("semi_minor_metre" in message for message in messages)


def test_pyproj_catalog_can_be_disabled_without_disabling_custom_values() -> None:
    source = "geod = Geod(a=6378137)\nvalue = item * 9.81\n"
    policy = PyprojConstantsPolicy(
        extensions=(".py",),
        wgs84_ellipsoid=False,
        constants=(
            {
                "name": "project constant",
                "values": (9.81,),
                "replacement": "project.GRAVITY",
            },
        ),
    )

    findings = pyproj_literal_findings(source, policy)

    assert len(findings) == 1
    assert "project.GRAVITY" in findings[0].message


def test_repository_scan_respects_extensions_and_exclusions(tmp_path: Path) -> None:
    python_file = tmp_path / "geo.py"
    ignored_file = tmp_path / "generated" / "geo.py"
    other_file = tmp_path / "geo.txt"
    ignored_file.parent.mkdir()
    python_file.write_text("geod = Geod(a=6378137)\n", encoding="utf-8")
    ignored_file.write_text("geod = Geod(a=6378137)\n", encoding="utf-8")
    other_file.write_text("geod = Geod(a=6378137)\n", encoding="utf-8")

    findings = check_pyproj_constants(
        tmp_path,
        [Path("geo.py"), Path("generated/geo.py"), Path("geo.txt")],
        PyprojConstantsPolicy(extensions=(".py",), exclude=("generated/**",)),
    )

    assert [(finding.path, finding.line) for finding in findings] == [("geo.py", 1)]
