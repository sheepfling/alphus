from pathlib import Path

import pytest
from pydantic import ValidationError

from alphus.config import QualityGateConfig, QuaternionConjugationPolicy
from alphus.execution.dispatch import run_builtin_rule
from alphus.gates.review.numerical.quaternions.manual_quaternion_conjugation import (
    ALPHUS_FEATURE,
    check_manual_quaternion_conjugation,
    quaternion_conjugation_lines,
    resolve_manual_quaternion_conjugation_policy,
    run_manual_quaternion_conjugation_feature,
)
from alphus.plugins.builtin import FindingBuiltinFeature

_COMPONENTS = ("w", "x", "y", "z")


def _policy(
    *, function_names: tuple[str, ...] = ("conjugate",)
) -> QuaternionConjugationPolicy:
    return QuaternionConjugationPolicy(
        extensions=(".py",),
        source_paths=("src/geometry/*.py",),
        function_names=function_names,
        components=_COMPONENTS,
    )


def test_detects_exact_configured_scalar_first_conjugation() -> None:
    source = """\
def conjugate(w, x, y, z):
    return w, -x, -y, -z
"""
    assert quaternion_conjugation_lines(source, _policy()) == [("conjugate", 1)]


def test_ignores_generic_vector_wrong_sign_and_unconfigured_function() -> None:
    generic = """\
def reflect(w, x, y, z):
    return w, -x, -y, -z
"""
    wrong_sign = """\
def conjugate(w, x, y, z):
    return -w, x, y, z
"""
    assert not quaternion_conjugation_lines(generic, _policy())
    assert not quaternion_conjugation_lines(wrong_sign, _policy())
    assert not quaternion_conjugation_lines(
        "def conjugate(w, x, y, z):\n    return w, -x, -y, -z\n",
        _policy(function_names=("quaternion_conjugate",)),
    )


def test_ignores_branching_or_locally_reassigned_components() -> None:
    source = """\
def conjugate(w, x, y, z):
    x = abs(x)
    if w:
        return w, -x, -y, -z
    return w, x, y, z
"""
    assert not quaternion_conjugation_lines(source, _policy())


def test_validates_component_names() -> None:
    with pytest.raises(ValidationError, match="components must be four identifiers"):
        QuaternionConjugationPolicy(
            extensions=(".py",),
            source_paths=("src/geometry/*.py",),
            function_names=("conjugate",),
            components=("w", "x", "y", "z[0]"),
        )


def test_reports_only_configured_paths_and_honors_exclusions(tmp_path: Path) -> None:
    source = tmp_path / "src/geometry/quaternion.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "def conjugate(w, x, y, z):\n    return w, -x, -y, -z\n",
        encoding="utf-8",
    )
    paths = (Path("src/geometry/quaternion.py"),)
    findings = check_manual_quaternion_conjugation(tmp_path, paths, _policy())
    assert len(findings) == 1
    assert findings[0].rule_id == (
        "alphus/python/none/maintainability/manual-quaternion-conjugation"
    )
    excluded = QuaternionConjugationPolicy(
        extensions=(".py",),
        source_paths=("src/geometry/*.py",),
        function_names=("conjugate",),
        components=_COMPONENTS,
        exclude=("src/geometry/**",),
    )
    assert not check_manual_quaternion_conjugation(tmp_path, paths, excluded)


def test_feature_registration_preserves_configured_finding_behavior(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "src/geometry/operations.py"
    source_path.parent.mkdir(parents=True)
    source_path.write_text(
        "def conjugate(w, x, y, z):\n    return w, -x, -y, -z\n", encoding="utf-8"
    )
    relative = Path("src/geometry/operations.py")
    policy = _policy()
    config = QualityGateConfig.model_validate(
        {"schema_version": 1, "checks": {"manual_quaternion_conjugation": policy}},
        strict=True,
    )

    assert isinstance(ALPHUS_FEATURE, FindingBuiltinFeature)
    assert ALPHUS_FEATURE.definition.policy_model is QuaternionConjugationPolicy
    resolved = resolve_manual_quaternion_conjugation_policy(config)
    assert type(resolved) is QuaternionConjugationPolicy
    expected = check_manual_quaternion_conjugation(tmp_path, [relative], policy)
    assert expected
    assert (
        run_manual_quaternion_conjugation_feature(tmp_path, [relative], resolved)
        == expected
    )
    assert (
        run_builtin_rule("manual-quaternion-conjugation", tmp_path, [relative], config)
        == expected
    )
