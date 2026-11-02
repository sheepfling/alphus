from pathlib import Path

import pytest
from pydantic import ValidationError

from alphus.config import EcefEnuTransformPolicy
from alphus.gates.review.numerical.frames.ecef_enu_transform import (
    check_ecef_enu_transform,
    ecef_enu_transform_sites,
)

_SOURCE = """\
import math

def ecef_delta_to_enu(dx, dy, dz, latitude, longitude):
    return (
        -math.sin(longitude) * dx + math.cos(longitude) * dy,
        -math.sin(latitude) * math.cos(longitude) * dx
        - math.sin(latitude) * math.sin(longitude) * dy
        + math.cos(latitude) * dz,
        math.cos(latitude) * math.cos(longitude) * dx
        + math.cos(latitude) * math.sin(longitude) * dy
        + math.sin(latitude) * dz,
    )
"""


def _policy(**updates: object) -> EcefEnuTransformPolicy:
    return EcefEnuTransformPolicy.model_validate(
        {
            "extensions": (".py",),
            "exclude": (),
            "source_paths": ("src/geometry/*.py",),
            "function_names": ("ecef_delta_to_enu",),
            "components": ("dx", "dy", "dz"),
            "latitude_name": "latitude",
            "longitude_name": "longitude",
            "preferred_helpers": ("geometry.frames.ecef_delta_to_enu",),
            "source_frame": "ECEF",
            "destination_frame": "ENU",
            "direction": "ecef-to-enu",
            "latitude_type": "geodetic",
            "origin": "anchor-point",
            "reference_ellipsoid": "WGS84",
            "angle_units": "radians",
            "length_units": "meters",
            "axis_order": "east-north-up",
            "handedness": "right-handed",
            "operation": "displacement-vector",
            "output_shape": "tuple3",
            **updates,
        }
    )


def test_matches_exact_configured_ecef_delta_to_enu_tuple() -> None:
    sites = ecef_enu_transform_sites(_SOURCE, _policy())
    assert [(site.function, site.line) for site in sites] == [("ecef_delta_to_enu", 4)]


@pytest.mark.parametrize(
    "source",
    [
        _SOURCE.replace("-math.sin(longitude) * dx", "math.sin(longitude) * dx"),
        _SOURCE.replace("return (", "result = (").replace(
            "\n    )\n", "\n    )\n    return result\n"
        ),
        _SOURCE.replace("import math", "import math as trig"),
        _SOURCE.replace("import math", "import math\nmath = object()"),
        _SOURCE.replace("    return (", "    import math as math\n    return ("),
        _SOURCE.replace("def ecef_delta_to_enu(dx", "def ecef_delta_to_enu(math, dx"),
        _SOURCE.replace("def ecef_delta_to_enu(dx", "def another_transform(dx"),
        _SOURCE.replace("    return (", "    return [", 1).replace(
            "\n    )\n", "\n    ]\n"
        ),
        _SOURCE.replace(
            "    return (", "    if latitude > 0:\n        return ("
        ).replace("\n    )\n", "\n        )\n"),
    ],
)
def test_wrong_sign_alias_shadow_and_boundary_forms_are_negative(source: str) -> None:
    assert ecef_enu_transform_sites(source, _policy()) == []


def test_requires_module_import_and_single_definition() -> None:
    assert (
        ecef_enu_transform_sites(_SOURCE.replace("import math\n", ""), _policy()) == []
    )
    later = "\ndef ecef_delta_to_enu(dx, dy, dz, latitude, longitude):\n    return (dx, dy, dz)\n"
    assert ecef_enu_transform_sites(_SOURCE + later, _policy()) == []


def test_unparseable_source_is_abstained_from() -> None:
    assert ecef_enu_transform_sites("def broken(:\n", _policy()) == []


def test_finding_is_scoped_configured_and_explicitly_advisory(tmp_path: Path) -> None:
    target = tmp_path / "src/geometry/frames.py"
    target.parent.mkdir(parents=True)
    target.write_text(_SOURCE, encoding="utf-8")
    paths = (Path("src/geometry/frames.py"),)
    findings = check_ecef_enu_transform(tmp_path, paths, _policy())
    assert len(findings) == 1
    assert "geometry.frames.ecef_delta_to_enu" in findings[0].message
    assert "reference" in findings[0].message
    assert "no speedup is inferred" in findings[0].message
    assert not check_ecef_enu_transform(
        tmp_path, paths, _policy(exclude=("src/geometry/frames.py",))
    )


def test_unparseable_file_does_not_prevent_later_findings(tmp_path: Path) -> None:
    broken = tmp_path / "src/geometry/00_broken.py"
    valid = tmp_path / "src/geometry/frames.py"
    broken.parent.mkdir(parents=True)
    broken.write_text("def broken(:\n", encoding="utf-8")
    valid.write_text(_SOURCE, encoding="utf-8")

    findings = check_ecef_enu_transform(
        tmp_path,
        (Path("src/geometry/00_broken.py"), Path("src/geometry/frames.py")),
        _policy(),
    )

    assert len(findings) == 1
    assert findings[0].path == "src/geometry/frames.py"


@pytest.mark.parametrize(
    "field,value",
    [
        ("destination_frame", "NED"),
        ("latitude_type", "geocentric"),
        ("angle_units", "degrees"),
    ],
)
def test_contract_does_not_accept_unimplemented_conventions(
    field: str, value: str
) -> None:
    with pytest.raises(ValidationError):
        _policy(**{field: value})
