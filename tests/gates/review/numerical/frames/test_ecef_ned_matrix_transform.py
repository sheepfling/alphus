from pathlib import Path

import pytest
from pydantic import ValidationError

from alphus.config import EcefNedMatrixTransformPolicy, QualityGateConfig
from alphus.execution.dispatch import run_builtin_rule
from alphus.gates.review.numerical.frames.ecef_ned_matrix_transform import (
    ALPHUS_FEATURE,
    check_ecef_ned_matrix_transform,
    ecef_ned_matrix_transform_sites,
    resolve_ecef_ned_matrix_transform_policy,
    run_ecef_ned_matrix_transform_feature,
)
from alphus.plugins.builtin import FindingBuiltinFeature

_TITAN_SHAPE = """\
import math
import numpy as np

def ecef_to_ned_matrix(lat_rad, lon_rad):
    \"\"\"Rotation matrix from ECEF to local NED.\"\"\"
    slat, clat = math.sin(lat_rad), math.cos(lat_rad)
    slon, clon = math.sin(lon_rad), math.cos(lon_rad)
    return np.array([
        [-slat*clon, -slat*slon, clat],
        [-slon, clon, 0.0],
        [-clat*clon, -clat*slon, -slat],
    ])
"""


def _policy(**updates: object) -> EcefNedMatrixTransformPolicy:
    return EcefNedMatrixTransformPolicy.model_validate(
        {
            "extensions": (".py",),
            "exclude": (),
            "source_paths": ("src/geometry/*.py",),
            "function_names": ("ecef_to_ned_matrix",),
            "latitude_name": "lat_rad",
            "longitude_name": "lon_rad",
            "sin_latitude_name": "slat",
            "cos_latitude_name": "clat",
            "sin_longitude_name": "slon",
            "cos_longitude_name": "clon",
            "preferred_helpers": ("titan_simulation.coords.ecef_to_ned_matrix",),
            "array_constructor": "np.array",
            "math_module": "math",
            "source_frame": "ECEF",
            "destination_frame": "NED",
            "direction": "ecef-to-ned",
            "latitude_type": "geodetic",
            "origin": "anchor-point",
            "reference_ellipsoid": "WGS84",
            "angle_units": "radians",
            "length_units": "meters",
            "axis_order": "north-east-down",
            "handedness": "right-handed",
            "operation": "displacement-vector",
            "vector_orientation": "column",
            "matrix_layout": "row-major",
            "output_shape": "matrix3x3",
            **updates,
        }
    )


def test_matches_titan_style_configured_ecef_to_ned_matrix() -> None:
    sites = ecef_ned_matrix_transform_sites(_TITAN_SHAPE, _policy())
    assert [(site.function, site.line) for site in sites] == [("ecef_to_ned_matrix", 8)]


def test_supports_configured_variable_names_and_unaliased_numpy_import() -> None:
    source = (
        _TITAN_SHAPE.replace("import numpy as np", "import numpy")
        .replace("np.array", "numpy.array")
        .replace("slat", "sin_phi")
        .replace("clat", "cos_phi")
        .replace("slon", "sin_lam")
        .replace("clon", "cos_lam")
    )
    policy = _policy(
        array_constructor="numpy.array",
        sin_latitude_name="sin_phi",
        cos_latitude_name="cos_phi",
        sin_longitude_name="sin_lam",
        cos_longitude_name="cos_lam",
    )
    assert len(ecef_ned_matrix_transform_sites(source, policy)) == 1


@pytest.mark.parametrize(
    "source",
    [
        _TITAN_SHAPE.replace("-slat*clon", "slat*clon", 1),
        _TITAN_SHAPE.replace("[-slon, clon, 0.0]", "[clon, -slon, 0.0]"),
        _TITAN_SHAPE.replace(
            "[-clat*clon, -clat*slon, -slat]", "[-clat*clon, -slat, -clat*slon]"
        ),
        _TITAN_SHAPE.replace("0.0", "0"),
        _TITAN_SHAPE.replace(
            "slat, clat = math.sin(lat_rad), math.cos(lat_rad)",
            "slat, clat = math.sin(math.radians(lat_rad)), math.cos(math.radians(lat_rad))",
        ),
        _TITAN_SHAPE.replace("np.array([", "np.asarray(["),
        _TITAN_SHAPE.replace("return np.array([", "return [").replace(
            "\n    ])", "\n    ]"
        ),
        _TITAN_SHAPE.replace("import numpy as np", "import numpy as n"),
        _TITAN_SHAPE.replace(
            "import numpy as np", "import numpy as np\nnp = custom_array"
        ),
        _TITAN_SHAPE.replace(
            "    return np.array([", "    np = custom_array\n    return np.array(["
        ),
        _TITAN_SHAPE.replace(
            "    return np.array([", "    if lat_rad > 0:\n        return np.array(["
        ).replace("    ])\n", "        ])\n"),
        _TITAN_SHAPE + "\necef_to_ned_matrix = lambda *args: np.eye(3)\n",
    ],
)
def test_wrong_sign_axis_shape_alias_shadow_and_flow_forms_abstain(
    source: str,
) -> None:
    assert ecef_ned_matrix_transform_sites(source, _policy()) == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("destination_frame", "ENU"),
        ("latitude_type", "geocentric"),
        ("angle_units", "degrees"),
        ("axis_order", "east-north-up"),
        ("vector_orientation", "row"),
        ("matrix_layout", "column-major"),
        ("output_shape", "tuple3"),
    ],
)
def test_policy_rejects_unimplemented_frame_and_representation_contracts(
    field: str, value: str
) -> None:
    with pytest.raises(ValidationError):
        _policy(**{field: value})


def test_module_imports_and_unique_function_definition_are_required() -> None:
    assert (
        ecef_ned_matrix_transform_sites(
            _TITAN_SHAPE.replace("import math\n", ""), _policy()
        )
        == []
    )
    duplicate = _TITAN_SHAPE + "\n" + _TITAN_SHAPE.split("import math\n", 1)[1]
    assert ecef_ned_matrix_transform_sites(duplicate, _policy()) == []


@pytest.mark.parametrize(
    "rebind",
    [
        "np.array = fake_array",
        "math.sin = fake_sin",
        "if True:\n    np.array = fake_array",
        "if True:\n    math.cos = fake_cos",
        "if True:\n    ecef_to_ned_matrix = fake_transform",
    ],
)
def test_module_and_control_flow_rebindings_abstain(rebind: str) -> None:
    assert (
        ecef_ned_matrix_transform_sites(_TITAN_SHAPE + "\n" + rebind, _policy()) == []
    )


def test_unrelated_function_local_alias_does_not_hide_candidate() -> None:
    source = _TITAN_SHAPE + "\ndef unrelated():\n    np = object()\n"
    assert len(ecef_ned_matrix_transform_sites(source, _policy())) == 1


def test_finding_is_scoped_and_names_configured_contract(tmp_path: Path) -> None:
    target = tmp_path / "src/geometry/coordinates.py"
    target.parent.mkdir(parents=True)
    target.write_text(_TITAN_SHAPE, encoding="utf-8")
    paths = (Path("src/geometry/coordinates.py"),)
    findings = check_ecef_ned_matrix_transform(tmp_path, paths, _policy())
    assert len(findings) == 1
    assert "north-east-down" in findings[0].message
    assert "column vectors" in findings[0].message
    assert "titan_simulation.coords.ecef_to_ned_matrix" in findings[0].message
    assert "no speedup is inferred" in findings[0].message
    assert not check_ecef_ned_matrix_transform(
        tmp_path, paths, _policy(exclude=("src/geometry/coordinates.py",))
    )


def test_feature_registration_preserves_configured_finding_behavior(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "src/geometry/operations.py"
    source_path.parent.mkdir(parents=True)
    source_path.write_text(_TITAN_SHAPE, encoding="utf-8")
    relative = Path("src/geometry/operations.py")
    policy = _policy()
    config = QualityGateConfig.model_validate(
        {"schema_version": 1, "checks": {"ecef_ned_matrix_transform": policy}},
        strict=True,
    )

    assert isinstance(ALPHUS_FEATURE, FindingBuiltinFeature)
    assert ALPHUS_FEATURE.definition.policy_model is EcefNedMatrixTransformPolicy
    resolved = resolve_ecef_ned_matrix_transform_policy(config)
    assert type(resolved) is EcefNedMatrixTransformPolicy
    expected = check_ecef_ned_matrix_transform(tmp_path, [relative], policy)
    assert expected
    assert (
        run_ecef_ned_matrix_transform_feature(tmp_path, [relative], resolved)
        == expected
    )
    assert (
        run_builtin_rule("ecef-ned-matrix-transform", tmp_path, [relative], config)
        == expected
    )
