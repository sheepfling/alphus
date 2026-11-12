from pathlib import Path

import pytest
from pydantic import ValidationError

from alphus.config import NedBasisVectorsPolicy, QualityGateConfig
from alphus.execution.dispatch import run_builtin_rule
from alphus.gates.review.numerical.frames.ned_basis_vectors import (
    ALPHUS_FEATURE,
    check_ned_basis_vectors,
    ned_basis_vector_sites,
    resolve_ned_basis_vectors_policy,
    run_ned_basis_vectors_feature,
)
from alphus.plugins.builtin import FindingBuiltinFeature

_GEOCENTRIC = """\
import math

class CartesianVector3:
    pass

def geocentric_unit_vectors(longitude_radians, latitude_radians):
    cos_latitude = math.cos(latitude_radians)
    sin_latitude = math.sin(latitude_radians)
    cos_longitude = math.cos(longitude_radians)
    sin_longitude = math.sin(longitude_radians)
    north = CartesianVector3(
        -sin_latitude * cos_longitude,
        -sin_latitude * sin_longitude,
        cos_latitude,
    )
    east = CartesianVector3(-sin_longitude, cos_longitude, 0.0)
    down = CartesianVector3(
        -cos_latitude * cos_longitude,
        -cos_latitude * sin_longitude,
        -sin_latitude,
    )
    return north, east, down
"""

_GEODETIC = """\
import math
from contracts import Basis3, Frame, Vector3

def geodetic_unit_vectors(longitude, latitude):
    cosine_latitude = math.cos(latitude.radians)
    sine_latitude = math.sin(latitude.radians)
    cosine_longitude = math.cos(longitude.radians)
    sine_longitude = math.sin(longitude.radians)
    first = Vector3(
        -sine_latitude * cosine_longitude,
        -sine_latitude * sine_longitude,
        cosine_latitude,
    )
    second = Vector3(-sine_longitude, cosine_longitude, 0.0)
    return Basis3(
        first,
        second,
        first.cross(second),
        parent_frame=Frame.ECFC,
        child_frame=Frame.GEODETIC_HORIZON,
    )
"""


def _policy(convention: str, **updates: object) -> NedBasisVectorsPolicy:
    geocentric = convention == "geocentric"
    return NedBasisVectorsPolicy.model_validate(
        {
            "extensions": (".py",),
            "exclude": (),
            "source_paths": ("src/geometry/*.py",),
            "function_names": (
                "geocentric_unit_vectors" if geocentric else "geodetic_unit_vectors",
            ),
            "preferred_helpers": ("taoryx.coordinates.local_ned_basis",),
            "latitude_type": convention,
            "output_representation": "tuple3" if geocentric else "basis3",
            "longitude_name": "longitude_radians" if geocentric else "longitude",
            "latitude_name": "latitude_radians" if geocentric else "latitude",
            "sine_latitude_name": "sin_latitude" if geocentric else "sine_latitude",
            "cosine_latitude_name": "cos_latitude" if geocentric else "cosine_latitude",
            "sine_longitude_name": "sin_longitude" if geocentric else "sine_longitude",
            "cosine_longitude_name": "cos_longitude"
            if geocentric
            else "cosine_longitude",
            "north_name": "north" if geocentric else "first",
            "east_name": "east" if geocentric else "second",
            "vector_constructor": "CartesianVector3" if geocentric else "Vector3",
            "basis_constructor": "Basis3",
            "frame_type": "Frame",
            "source_frame": "ECFC",
            "destination_frame": "GEOCENTRIC_HORIZON"
            if geocentric
            else "GEODETIC_HORIZON",
            "direction": "ecfc-to-local-ned",
            "angle_units": "radians",
            "axis_order": "north-east-down",
            "handedness": "right-handed",
            "operation": "basis-vectors",
            **updates,
        }
    )


@pytest.mark.parametrize(
    ("source", "convention", "expected_line"),
    [(_GEOCENTRIC, "geocentric", 22), (_GEODETIC, "geodetic", 15)],
)
def test_matches_distinct_pinned_style_ned_basis_forms(
    source: str, convention: str, expected_line: int
) -> None:
    sites = ned_basis_vector_sites(source, _policy(convention))
    assert [(site.function, site.line) for site in sites] == [
        (
            "geocentric_unit_vectors"
            if convention == "geocentric"
            else "geodetic_unit_vectors",
            expected_line,
        )
    ]


@pytest.mark.parametrize(
    ("source", "convention"),
    [
        (
            _GEOCENTRIC.replace("return north, east, down", "return east, north, down"),
            "geocentric",
        ),
        (
            _GEOCENTRIC.replace(
                "-sin_latitude * cos_longitude",
                "sin_latitude * cos_longitude",
                1,
            ),
            "geocentric",
        ),
        (
            _GEOCENTRIC.replace(
                "latitude_radians)", "math.radians(latitude_radians))", 2
            ),
            "geocentric",
        ),
        (
            _GEODETIC.replace("Frame.GEODETIC_HORIZON", "Frame.GEOCENTRIC_HORIZON"),
            "geodetic",
        ),
        (_GEODETIC.replace("first.cross(second)", "second.cross(first)"), "geodetic"),
        (
            _GEODETIC.replace("latitude.radians", "math.radians(latitude.radians)"),
            "geodetic",
        ),
        (_GEOCENTRIC + "\ngeocentric_unit_vectors = lambda *args: ()\n", "geocentric"),
        (_GEODETIC + "\ngeodetic_unit_vectors = lambda *args: None\n", "geodetic"),
        (
            _GEOCENTRIC
            + "\nif True:\n    def geocentric_unit_vectors("
            + "longitude_radians, latitude_radians):\n        return ()\n",
            "geocentric",
        ),
        (
            _GEODETIC
            + "\nif True:\n    def geodetic_unit_vectors(longitude, "
            + "latitude):\n        return None\n",
            "geodetic",
        ),
        (_GEOCENTRIC + "\nmath.sin = lambda _x: 99\n", "geocentric"),
        (_GEODETIC + "\nmath.sin = lambda _x: 99\n", "geodetic"),
        (_GEOCENTRIC + "\nmath.cos = lambda _x: 99\n", "geocentric"),
        (_GEODETIC + "\nmath.cos = lambda _x: 99\n", "geodetic"),
        (
            _GEOCENTRIC.replace("import math", "import math\nmath = custom_math"),
            "geocentric",
        ),
        (
            _GEOCENTRIC + "\nif True:\n    CartesianVector3 = replacement\n",
            "geocentric",
        ),
    ],
)
def test_wrong_convention_formula_units_or_rebinding_abstains(
    source: str, convention: str
) -> None:
    assert ned_basis_vector_sites(source, _policy(convention)) == []


@pytest.mark.parametrize(
    ("convention", "field", "value"),
    [
        ("geodetic", "latitude_type", "geocentric"),
        ("geocentric", "destination_frame", "GEODETIC_HORIZON"),
        ("geocentric", "output_representation", "basis3"),
        ("geodetic", "handedness", "left-handed"),
    ],
)
def test_contract_cannot_mix_geodetic_and_geocentric_representations(
    convention: str, field: str, value: str
) -> None:
    with pytest.raises(ValidationError):
        _policy(convention, **{field: value})


def test_finding_names_declared_latitude_contract(tmp_path: Path) -> None:
    target = tmp_path / "src/geometry/basis.py"
    target.parent.mkdir(parents=True)
    target.write_text(_GEODETIC, encoding="utf-8")
    findings = check_ned_basis_vectors(
        tmp_path, (Path("src/geometry/basis.py"),), _policy("geodetic")
    )
    assert len(findings) == 1
    assert "geodetic" in findings[0].message
    assert (
        "latitude semantics come from policy, not syntax" in findings[0].message.lower()
    )
    assert (
        "no equivalence or performance gain is inferred" in findings[0].message.lower()
    )


def test_unrelated_function_local_alias_does_not_hide_candidate() -> None:
    source = (
        _GEOCENTRIC
        + "\ndef unrelated():\n    math = object()\n    CartesianVector3 = object\n"
    )
    assert len(ned_basis_vector_sites(source, _policy("geocentric"))) == 1


def test_feature_registration_preserves_configured_finding_behavior(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "src/geometry/operations.py"
    source_path.parent.mkdir(parents=True)
    source_path.write_text(_GEOCENTRIC, encoding="utf-8")
    relative = Path("src/geometry/operations.py")
    policy = _policy("geocentric")
    config = QualityGateConfig.model_validate(
        {"schema_version": 1, "checks": {"ned_basis_vectors": policy}}, strict=True
    )

    assert isinstance(ALPHUS_FEATURE, FindingBuiltinFeature)
    assert ALPHUS_FEATURE.definition.policy_model is NedBasisVectorsPolicy
    resolved = resolve_ned_basis_vectors_policy(config)
    assert type(resolved) is NedBasisVectorsPolicy
    expected = check_ned_basis_vectors(tmp_path, [relative], policy)
    assert expected
    assert run_ned_basis_vectors_feature(tmp_path, [relative], resolved) == expected
    assert (
        run_builtin_rule("ned-basis-vectors", tmp_path, [relative], config) == expected
    )
