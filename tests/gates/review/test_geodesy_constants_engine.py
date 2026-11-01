"""Geodetic catalogs match explicit WGS 84 ellipsoid call arguments."""

from __future__ import annotations

from alphus.config import GeodesyConstantsPolicy
from alphus.gates.review.geodesy_constants import geodesy_literal_findings


def _policy(**options: bool) -> GeodesyConstantsPolicy:
    return GeodesyConstantsPolicy(extensions=(".py",), **options)


def test_wgs84_pair_matches_imported_pyproj_geod_alias() -> None:
    source = (
        "from pyproj import Geod as Geodesic\n"
        "earth = Geodesic(a=6378137.0, rf=298.257223563)\n"
    )

    findings = geodesy_literal_findings(source, _policy())

    assert [finding.line for finding in findings] == [2, 2]
    assert {finding.rule_id for finding in findings} == {
        "alphus/python/pyproj/style/inline-constant"
    }
    assert any("WGS 84 semi-major axis" in finding.message for finding in findings)
    assert any(
        "WGS 84 reciprocal flattening" in finding.message for finding in findings
    )
    assert all('pyproj.Geod(ellps="WGS84")' in finding.message for finding in findings)


def test_wgs84_values_require_the_pair_in_a_pyproj_geod_call() -> None:
    source = (
        "from pyproj import Geod\n"
        "semi_major_only = Geod(a=6378137.0, rf=298.257222101)\n"
        "other_callable = Geod(a=6378136.0, rf=298.257223563)\n"
        "unrelated = object(a=6378137.0, rf=298.257223563)\n"
    )

    assert geodesy_literal_findings(source, _policy()) == []


def test_wgs84_builtin_can_be_disabled() -> None:
    source = "from pyproj import Geod\nearth = Geod(a=6378137.0, rf=298.257223563)\n"

    assert geodesy_literal_findings(source, _policy(wgs84_ellipsoid=False)) == []
