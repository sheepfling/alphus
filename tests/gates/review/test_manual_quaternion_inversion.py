from pathlib import Path

import pytest

from alphus.config import QuaternionInversionPolicy
from alphus.gates.review.manual_quaternion_inversion import (
    check_manual_quaternion_inversion,
    quaternion_inversion_sites,
)

_SOURCE = """\
def inverse_quaternion(w, x, y, z):
    norm_squared = w * w + x * x + y * y + z * z
    return (w / norm_squared, -x / norm_squared, -y / norm_squared, -z / norm_squared)
"""


def _policy(**updates: object) -> QuaternionInversionPolicy:
    return QuaternionInversionPolicy.model_validate(
        {
            "extensions": (".py",),
            "exclude": (),
            "source_paths": ("src/geometry/*.py",),
            "function_names": ("inverse_quaternion",),
            "components": ("w", "x", "y", "z"),
            **updates,
        }
    )


def test_matches_configured_nonunit_inverse_formula() -> None:
    sites = quaternion_inversion_sites(_SOURCE, _policy())

    assert [(site.function, site.norm_line, site.return_line) for site in sites] == [
        ("inverse_quaternion", 2, 3)
    ]


def test_conjugation_and_library_inverse_are_boundary_negatives() -> None:
    conjugation = """\
def inverse_quaternion(w, x, y, z):
    return (w, -x, -y, -z)
"""
    library = """\
def inverse_quaternion(q):
    return Rotation.from_quat(q).inv()
"""

    assert quaternion_inversion_sites(conjugation, _policy()) == []
    assert quaternion_inversion_sites(library, _policy()) == []


def test_requires_all_four_squares_and_matching_conjugate_components() -> None:
    missing_square = _SOURCE.replace("z * z", "y * y")
    wrong_sign = _SOURCE.replace("-z / norm_squared", "z / norm_squared")
    wrong_denominator = _SOURCE.replace("-z / norm_squared", "-z / x")
    square_root_norm = _SOURCE.replace(
        "w * w + x * x + y * y + z * z", "math.sqrt(w * w + x * x + y * y + z * z)"
    )

    assert quaternion_inversion_sites(missing_square, _policy()) == []
    assert quaternion_inversion_sites(wrong_sign, _policy()) == []
    assert quaternion_inversion_sites(wrong_denominator, _policy()) == []
    assert quaternion_inversion_sites(square_root_norm, _policy()) == []


def test_rejects_local_rebinding_and_nested_function_shadowing() -> None:
    rebound = _SOURCE.replace(
        "    return (w / norm_squared",
        "    norm_squared = 1\n    return (w / norm_squared",
    )
    nested = """\
def wrapper():
    def inverse_quaternion(w, x, y, z):
        norm_squared = w * w + x * x + y * y + z * z
        return (w / norm_squared, -x / norm_squared, -y / norm_squared, -z / norm_squared)
"""

    assert quaternion_inversion_sites(rebound, _policy()) == []
    assert quaternion_inversion_sites(nested, _policy()) == []


def test_configuration_names_and_scope_bound_the_match(tmp_path: Path) -> None:
    target = tmp_path / "src/geometry/quaternion.py"
    target.parent.mkdir(parents=True)
    target.write_text(_SOURCE, encoding="utf-8")
    paths = (Path("src/geometry/quaternion.py"),)

    findings = check_manual_quaternion_inversion(tmp_path, paths, _policy())
    assert len(findings) == 1
    assert findings[0].rule_id == (
        "alphus/python/none/maintainability/manual-quaternion-inversion"
    )
    assert findings[0].line == 2
    assert "non-unit inverse semantics" in findings[0].message
    assert not check_manual_quaternion_inversion(
        tmp_path,
        paths,
        _policy(exclude=("src/geometry/quaternion.py",)),
    )
    assert not check_manual_quaternion_inversion(
        tmp_path,
        paths,
        _policy(function_names=("different_name",)),
    )


def test_invalid_component_names_are_rejected() -> None:
    with pytest.raises(ValueError, match="quaternion components must be unique"):
        _policy(components=("w", "x", "x", "z"))
