from pathlib import Path

import pytest
from pydantic import ValidationError

from alphus.config import QualityGateConfig, QuaternionMatrixConversionPolicy
from alphus.execution.dispatch import run_builtin_rule
from alphus.gates.review.numerical.quaternions.manual_quaternion_matrix_conversion import (
    ALPHUS_FEATURE,
    check_manual_quaternion_matrix_conversion,
    quaternion_matrix_conversion_sites,
    resolve_manual_quaternion_matrix_conversion_policy,
    run_manual_quaternion_matrix_conversion_feature,
)
from alphus.plugins.builtin import FindingBuiltinFeature

_SOURCE = """\
def quaternion_to_matrix(w, x, y, z):
    return [
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ]
"""


def _policy(**updates: object) -> QuaternionMatrixConversionPolicy:
    return QuaternionMatrixConversionPolicy.model_validate(
        {
            "extensions": (".py",),
            "exclude": (),
            "source_paths": ("src/geometry/*.py",),
            "function_names": ("quaternion_to_matrix",),
            "components": ("w", "x", "y", "z"),
            "convention": "active-column-scalar-first",
            **updates,
        }
    )


def test_matches_configured_scalar_first_active_column_formula() -> None:
    sites = quaternion_matrix_conversion_sites(_SOURCE, _policy())
    assert [(site.function, site.line) for site in sites] == [
        ("quaternion_to_matrix", 2)
    ]


def test_transposed_convention_wrong_term_and_unrelated_matrix_are_negative() -> None:
    transposed_sign = _SOURCE.replace("x * y - z * w", "x * y + z * w", 1)
    wrong_component = _SOURCE.replace("x * z + y * w", "x * z + z * w")
    unrelated = """\
def quaternion_to_matrix(w, x, y, z):
    return [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
"""

    assert quaternion_matrix_conversion_sites(transposed_sign, _policy()) == []
    assert quaternion_matrix_conversion_sites(wrong_component, _policy()) == []
    assert quaternion_matrix_conversion_sites(unrelated, _policy()) == []


def test_rejects_local_alias_rebinding_nested_and_shadowed_definitions() -> None:
    alias = _SOURCE.replace("    return [", "    matrix = [").replace(
        "    ]\n", "    ]\n    return matrix\n"
    )
    rebound = _SOURCE.replace("    return [", "    x = 0\n    return [")
    nested = "def wrapper():\n" + "\n".join(
        f"    {line}" for line in _SOURCE.splitlines()
    )
    later = """\
def quaternion_to_matrix(w, x, y, z):
    return [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
"""

    assert quaternion_matrix_conversion_sites(alias, _policy()) == []
    assert quaternion_matrix_conversion_sites(rebound, _policy()) == []
    assert quaternion_matrix_conversion_sites(nested, _policy()) == []
    assert quaternion_matrix_conversion_sites(_SOURCE + "\n" + later, _policy()) == []


def test_rejects_later_assignment_rebinding_configured_function_name() -> None:
    rebinding = (
        _SOURCE
        + "\nquaternion_to_matrix = lambda *args: "
        + "[[1, 0, 0], [0, 1, 0], [0, 0, 1]]\n"
    )
    assert quaternion_matrix_conversion_sites(rebinding, _policy()) == []


def test_configuration_and_scope_bound_the_finding(tmp_path: Path) -> None:
    target = tmp_path / "src/geometry/matrix.py"
    target.parent.mkdir(parents=True)
    target.write_text(_SOURCE, encoding="utf-8")
    paths = (Path("src/geometry/matrix.py"),)

    findings = check_manual_quaternion_matrix_conversion(tmp_path, paths, _policy())
    assert len(findings) == 1
    assert "handedness" in findings[0].message
    assert not check_manual_quaternion_matrix_conversion(
        tmp_path, paths, _policy(exclude=("src/geometry/matrix.py",))
    )
    with pytest.raises(ValidationError, match="active-column-scalar-first"):
        _policy(convention="active-row-scalar-first")


def test_feature_registration_preserves_configured_finding_behavior(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "src/geometry/operations.py"
    source_path.parent.mkdir(parents=True)
    source = chr(10).join(
        (
            "def quaternion_to_matrix(w, x, y, z):",
            "    return [",
            "        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), "
            + "2 * (x * z + y * w)],",
            "        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), "
            + "2 * (y * z - x * w)],",
            "        [2 * (x * z - y * w), 2 * (y * z + x * w), "
            + "1 - 2 * (x * x + y * y)],",
            "    ]",
        )
    ) + chr(10)
    source_path.write_text(source, encoding="utf-8")
    relative = Path("src/geometry/operations.py")
    policy = _policy()
    config = QualityGateConfig.model_validate(
        {
            "schema_version": 1,
            "checks": {"manual_quaternion_matrix_conversion": policy},
        },
        strict=True,
    )

    assert isinstance(ALPHUS_FEATURE, FindingBuiltinFeature)
    assert ALPHUS_FEATURE.definition.policy_model is QuaternionMatrixConversionPolicy
    resolved = resolve_manual_quaternion_matrix_conversion_policy(config)
    assert type(resolved) is QuaternionMatrixConversionPolicy
    expected = check_manual_quaternion_matrix_conversion(tmp_path, [relative], policy)
    assert expected
    assert (
        run_manual_quaternion_matrix_conversion_feature(tmp_path, [relative], resolved)
        == expected
    )
    assert (
        run_builtin_rule(
            "manual-quaternion-matrix-conversion", tmp_path, [relative], config
        )
        == expected
    )
