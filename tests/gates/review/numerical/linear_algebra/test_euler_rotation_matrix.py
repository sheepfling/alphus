from alphus.config import EulerRotationMatrixPolicy
from alphus.gates.review.numerical.linear_algebra.euler_rotation_matrix import (
    euler_rotation_matrix_sites,
)

_WOLF_SOURCE = """\
import math

def _source_covariance(angles):
    yaw, pitch, roll = angles
    cy, sy, cp, sp, cr, sr = (
        math.cos(yaw), math.sin(yaw), math.cos(pitch), math.sin(pitch),
        math.cos(roll), math.sin(roll),
    )
    rotation = [
        [cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
        [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
        [-sp, cp * sr, cp * cr],
    ]
    return rotation
"""


def _policy(**updates: object) -> EulerRotationMatrixPolicy:
    return EulerRotationMatrixPolicy.model_validate(
        {
            "extensions": (".py",),
            "exclude": (),
            "source_paths": ("src/**/*.py",),
            "function_names": ("_source_covariance",),
            "angles": ("yaw", "pitch", "roll"),
            "trig_symbols": ("cy", "sy", "cp", "sp", "cr", "sr"),
            "sine_helpers": ("math.sin",),
            "cosine_helpers": ("math.cos",),
            "convention": "zyx",
            **updates,
        }
    )


def test_recognizes_removed_wolf_zyx_euler_matrix() -> None:
    sites = euler_rotation_matrix_sites(_WOLF_SOURCE, _policy())

    assert [(site.function, site.line) for site in sites] == [("_source_covariance", 9)]


def test_recognizes_nested_tuple_matrix_containers() -> None:
    tuple_matrix = (
        _WOLF_SOURCE.replace("rotation = [\n", "rotation = (\n")
        .replace("    ]\n", "    )\n")
        .replace("        [", "        (")
        .replace("],\n", "),\n")
    )

    assert len(euler_rotation_matrix_sites(tuple_matrix, _policy())) == 1


def test_rejects_altered_signs_and_library_rotation_calls() -> None:
    changed_sign = _WOLF_SOURCE.replace(
        "cy * sp * sr - sy * cr", "cy * sp * sr + sy * cr"
    )
    library_call = """\
from scipy.spatial.transform import Rotation

def _source_covariance(angles):
    return Rotation.from_euler("ZYX", angles, degrees=True).as_matrix()
"""

    assert euler_rotation_matrix_sites(changed_sign, _policy()) == []
    assert euler_rotation_matrix_sites(library_call, _policy()) == []


def test_configured_function_and_trigonometric_bindings_are_required() -> None:
    wrong_angle = _WOLF_SOURCE.replace("math.cos(pitch)", "math.cos(yaw)")

    assert (
        euler_rotation_matrix_sites(
            _WOLF_SOURCE, _policy(function_names=("another_function",))
        )
        == []
    )
    assert euler_rotation_matrix_sites(wrong_angle, _policy()) == []
