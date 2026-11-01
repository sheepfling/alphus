"""Advisory geodetic-constant review for Python pyproj calls."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from alphus.config import GeodesyConstantsPolicy, NumericLiteralSpec
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

# WGS 84 ellipsoid parameters as listed by PROJ and in PROJJSON for EPSG:4326.
# The catalog is checked in so analysis does not depend on an installed pyproj
# package or on the PROJ database version in the consumer's environment.
_WGS84_ELLIPSOID = (
    NumericLiteralSpec(
        name="WGS 84 semi-major axis",
        values=(6378137,),
        replacement='pyproj.Geod(ellps="WGS84")',
        context="call-argument",
        call_names=("pyproj.Geod",),
        argument_names=("a",),
        required_call_arguments=(("rf", 298.257223563),),
    ),
    NumericLiteralSpec(
        name="WGS 84 reciprocal flattening",
        values=(298.257223563,),
        replacement='pyproj.Geod(ellps="WGS84")',
        context="call-argument",
        call_names=("pyproj.Geod",),
        argument_names=("rf",),
        required_call_arguments=(("a", 6378137),),
    ),
)


def geodesy_literal_findings(
    source: str, policy: GeodesyConstantsPolicy
) -> list[NumericLiteralFinding]:
    """Review configured geodetic values in their declared Python contexts."""
    occurrences = scan_python_numeric_occurrences(source)
    findings: list[NumericLiteralFinding] = []
    if policy.wgs84_ellipsoid:
        findings.extend(
            match_numeric_occurrences(
                occurrences,
                NumericCatalog(
                    realm="geodesy",
                    framework=Framework.PYPROJ,
                    provenance=(
                        "https://proj.org/en/stable/usage/ellipsoids.html; "
                        "https://proj.org/en/stable/specifications/projjson.html"
                    ),
                    specs=_WGS84_ELLIPSOID,
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
                    framework=Framework.PYPROJ,
                    provenance=None,
                    specs=policy.constants,
                ),
                scope=Scope.PYTHON,
            )
        )
    return sorted(set(findings))


def check_geodesy_constants(
    root: Path, paths: Iterable[Path], policy: GeodesyConstantsPolicy
) -> list[Finding]:
    """Return advisory geodesy findings for the selected Python inventory."""
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
            for finding in geodesy_literal_findings(read_python_source(path), policy)
        )
    return findings
