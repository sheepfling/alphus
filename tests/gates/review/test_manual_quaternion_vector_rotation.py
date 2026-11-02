from pathlib import Path

from alphus.config import QuaternionVectorRotationPolicy
from alphus.gates.review.manual_quaternion_vector_rotation import (
    check_manual_quaternion_vector_rotation,
    quaternion_vector_rotation_sites,
)

_SOURCE = """\
def rotate_vector(w, x, y, z, vx, vy, vz):
    return multiply(multiply((w, x, y, z), (0, vx, vy, vz)), conjugate((w, x, y, z)))
"""


def _policy(**updates: object) -> QuaternionVectorRotationPolicy:
    return QuaternionVectorRotationPolicy.model_validate(
        {
            "extensions": (".py",),
            "exclude": (),
            "source_paths": ("src/geometry/*.py",),
            "function_names": ("rotate_vector",),
            "components": ("w", "x", "y", "z"),
            "vector_components": ("vx", "vy", "vz"),
            "multiplication_helpers": ("multiply",),
            "conjugation_helpers": ("conjugate",),
            **updates,
        }
    )


def test_matches_configured_pure_vector_quaternion_sandwich() -> None:
    sites = quaternion_vector_rotation_sites(_SOURCE, _policy())
    assert [(site.function, site.line) for site in sites] == [("rotate_vector", 2)]


def test_rejects_wrong_conjugate_order_vector_scalar_and_helper() -> None:
    wrong_order = _SOURCE.replace(
        "multiply((w, x, y, z), (0, vx, vy, vz)), conjugate((w, x, y, z))",
        "multiply((w, x, y, z), conjugate((w, x, y, z))), (0, vx, vy, vz)",
    )
    non_pure = _SOURCE.replace("(0, vx, vy, vz)", "(1, vx, vy, vz)")
    other_helper = _SOURCE.replace("multiply(multiply", "combine(combine")

    assert quaternion_vector_rotation_sites(wrong_order, _policy()) == []
    assert quaternion_vector_rotation_sites(non_pure, _policy()) == []
    assert quaternion_vector_rotation_sites(other_helper, _policy()) == []


def test_rejects_alias_rebinding_nested_shadowing_and_different_components() -> None:
    alias = _SOURCE.replace(
        "    return multiply(", "    operation = multiply\n    return operation("
    )
    rebound = _SOURCE.replace("    return multiply(", "    w = 0\n    return multiply(")
    nested = "def wrapper():\n" + "\n".join(
        f"    {line}" for line in _SOURCE.splitlines()
    )

    assert quaternion_vector_rotation_sites(alias, _policy()) == []
    assert quaternion_vector_rotation_sites(rebound, _policy()) == []
    assert quaternion_vector_rotation_sites(nested, _policy()) == []
    assert (
        quaternion_vector_rotation_sites(
            _SOURCE, _policy(vector_components=("a", "b", "c"))
        )
        == []
    )


def test_configured_path_exclusion_and_message_are_respected(tmp_path: Path) -> None:
    target = tmp_path / "src/geometry/rotation.py"
    target.parent.mkdir(parents=True)
    target.write_text(_SOURCE, encoding="utf-8")
    paths = (Path("src/geometry/rotation.py"),)

    findings = check_manual_quaternion_vector_rotation(tmp_path, paths, _policy())
    assert len(findings) == 1
    assert (
        "conjugation matches inverse only for unit quaternions" in findings[0].message
    )
    assert not check_manual_quaternion_vector_rotation(
        tmp_path, paths, _policy(exclude=("src/geometry/rotation.py",))
    )
