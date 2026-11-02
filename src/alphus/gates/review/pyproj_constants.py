"""Advisory pyproj WGS 84 ellipsoid review for Python source."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from alphus.config import NumericLiteralSpec, PyprojConstantsPolicy
from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import Framework
from alphus.gates.review.numeric_catalog import NumericLiteralFinding
from alphus.gates.review.numeric_engine import scan_numeric_literals
from alphus.support.inventory import matches_path
from alphus.support.source_text import read_python_source

_WGS84_ELLIPSOID = (
    NumericLiteralSpec(
        name="WGS 84 semi-major axis",
        values=(6378137,),
        replacement=("pyproj.CRS.from_epsg(4326).ellipsoid.semi_major_metre (metres)"),
        name_tokens=(
            "ellipsoid",
            "geod",
            "semi_major_axis",
            "semi_major_metre",
            "wgs",
            "wgs84",
        ),
    ),
    NumericLiteralSpec(
        name="WGS 84 inverse flattening",
        values=(298.257223563,),
        replacement=("pyproj.CRS.from_epsg(4326).ellipsoid.inverse_flattening"),
        name_tokens=(
            "ellipsoid",
            "geod",
            "inverse_flattening",
            "rf",
            "wgs",
            "wgs84",
        ),
    ),
    NumericLiteralSpec(
        name="WGS 84 semi-minor axis",
        values=(6356752.314245179,),
        replacement=("pyproj.CRS.from_epsg(4326).ellipsoid.semi_minor_metre (metres)"),
        name_tokens=(
            "ellipsoid",
            "geod",
            "semi_minor_axis",
            "semi_minor_metre",
            "wgs",
            "wgs84",
        ),
    ),
)


def pyproj_literal_findings(
    source: str, policy: PyprojConstantsPolicy
) -> list[NumericLiteralFinding]:
    """Match exact WGS 84 literals in arithmetic and call arguments."""
    specs = (
        *(_WGS84_ELLIPSOID if policy.wgs84_ellipsoid else ()),
        *policy.constants,
    )
    return scan_numeric_literals(
        source,
        specs,
        framework=Framework.PYPROJ,
        include_assignments=True,
        include_call_arguments=True,
    )


def check_pyproj_constants(
    root: Path, paths: Iterable[Path], policy: PyprojConstantsPolicy
) -> list[Finding]:
    """Return advisory pyproj findings for the selected Python inventory."""
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
            for finding in pyproj_literal_findings(read_python_source(path), policy)
        )
    return findings
