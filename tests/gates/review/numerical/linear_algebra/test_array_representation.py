from __future__ import annotations

from pathlib import Path

import pytest

from alphus.config import ArrayRepresentationPolicy, QualityGateConfig
from alphus.execution.dispatch import run_builtin_rule
from alphus.gates.review.numerical.linear_algebra.array_representation import (
    ALPHUS_FEATURE,
    check_array_representation,
    loop_representation_churn_lines,
    representation_churn_lines,
    resolve_array_representation_policy,
    run_array_representation_feature,
)
from alphus.plugins.builtin import FindingBuiltinFeature


def _policy(**updates: object) -> ArrayRepresentationPolicy:
    return ArrayRepresentationPolicy.model_validate(
        {
            "extensions": (".py",),
            "exclude": (),
            "source_paths": ("src/**/*.py",),
            "array_constructors": ("np.asarray",),
            **updates,
        }
    )


def test_flags_only_the_exact_configured_direct_round_trip() -> None:
    source = """import numpy as np
result = np.asarray(values.tolist())
payload = serialize(values.tolist())
other = np.asarray(values)
"""
    assert representation_churn_lines(source, _policy()) == [(2, 2)]


def test_skips_control_flow_and_unknown_constructor_or_conversion() -> None:
    source = """if enabled:
    result = np.asarray(values.tolist())
result = np.array(values.tolist())
result = np.asarray(values.tolist(), dtype=float)
result = helper(values.tolist())
"""
    assert representation_churn_lines(source, _policy()) == []
    assert representation_churn_lines(
        "result = np.array(values.tolist())\n",
        _policy(array_constructors=("np.array",)),
    ) == [(1, 1)]


def test_scoped_inventory_and_rule_id(tmp_path: Path) -> None:
    target = tmp_path / "src" / "numeric.py"
    target.parent.mkdir()
    target.write_text("result = np.asarray(values.tolist())\n", encoding="utf-8")
    findings = check_array_representation(
        tmp_path, [Path("src/numeric.py")], _policy(source_paths=("src/*.py",))
    )
    assert len(findings) == 1
    assert (
        findings[0].rule_id
        == "alphus/python/none/maintainability/array-representation-churn"
    )


def test_reports_used_array_round_trip_inside_a_contracted_loop() -> None:
    source = """import numpy as np
def project(values, rows):
    for row in rows:
        rebuilt = np.asarray(values.tolist())
        consume(rebuilt, row)
"""
    policy = _policy(
        loop_contracts=(
            {
                "path": "src/numeric.py",
                "function": "project",
                "array_variable": "values",
            },
        )
    )

    assert loop_representation_churn_lines(source, policy, path="src/numeric.py") == [
        (3, 4, 4, "values")
    ]


def test_resolves_constructor_alias_to_the_configured_import() -> None:
    source = """from numpy import asarray as build_array
def project(values, rows):
    for row in rows:
        rebuilt = build_array(values.tolist())
        consume(rebuilt, row)
"""
    policy = _policy(
        array_constructors=("numpy.asarray",),
        loop_contracts=(
            {
                "path": "src/numeric.py",
                "function": "project",
                "array_variable": "values",
            },
        ),
    )

    assert loop_representation_churn_lines(source, policy, path="src/numeric.py") == [
        (3, 4, 4, "values")
    ]


def test_loop_advisory_requires_declared_array_and_local_use(tmp_path: Path) -> None:
    source = """import numpy as np
def project(values, rows):
    for row in rows:
        rebuilt = np.asarray(values.tolist())
        consume(rebuilt, row)
"""
    target = tmp_path / "src" / "numeric.py"
    target.parent.mkdir()
    target.write_text(source, encoding="utf-8")
    assert (
        check_array_representation(
            tmp_path,
            [Path("src/numeric.py")],
            _policy(),
        )
        == []
    )

    findings = check_array_representation(
        tmp_path,
        [Path("src/numeric.py")],
        _policy(
            loop_contracts=(
                {
                    "path": "src/numeric.py",
                    "function": "project",
                    "array_variable": "values",
                },
            )
        ),
    )
    assert len(findings) == 1
    assert findings[0].line == 4
    assert "loop line 3" in findings[0].message
    assert "per-iteration" in findings[0].message
    assert (
        check_array_representation(
            tmp_path,
            [Path("src/numeric.py")],
            _policy(
                exclude=("src/numeric.py",),
                loop_contracts=(
                    {
                        "path": "src/numeric.py",
                        "function": "project",
                        "array_variable": "values",
                    },
                ),
            ),
        )
        == []
    )


def test_loop_advisory_skips_unknown_flow_and_shadowing() -> None:
    policy = _policy(
        loop_contracts=(
            {
                "path": "src/numeric.py",
                "function": "project",
                "array_variable": "values",
            },
        )
    )
    cases = (
        """import numpy as np
def project(values, rows):
    for row in rows:
        rebuilt = np.asarray(values.tolist())
        if row:
            consume(rebuilt)
""",
        """import numpy as np
def project(values, rows):
    for row in rows:
        rebuilt = np.asarray(values.tolist())
""",
        """import numpy as np
def project(values, rows):
    np = custom_constructor
    for row in rows:
        rebuilt = np.asarray(values.tolist())
        consume(rebuilt)
""",
        """import numpy as np
def project(values, rows):
    import custom as np
    for row in rows:
        rebuilt = np.asarray(values.tolist())
        consume(rebuilt)
""",
        """import numpy as np
def project(values, rows):
    for row in rows:
        alias = values
        rebuilt = np.asarray(alias.tolist())
        consume(rebuilt)
""",
        """def project(values, rows):
    for row in rows:
        rebuilt = np.asarray(values.tolist())
        consume(rebuilt)
""",
    )
    for source in cases:
        assert (
            loop_representation_churn_lines(source, policy, path="src/numeric.py") == []
        )


def test_nested_function_parameter_is_not_a_loop_value_use() -> None:
    source = """import numpy as np
def project(values, rows):
    for row in rows:
        rebuilt = np.asarray(values.tolist())
        def later(rebuilt):
            return rebuilt
"""
    policy = _policy(
        array_constructors=("numpy.asarray",),
        loop_contracts=(
            {
                "path": "src/numeric.py",
                "function": "project",
                "array_variable": "values",
            },
        ),
    )

    assert loop_representation_churn_lines(source, policy, path="src/numeric.py") == []


def test_loop_contract_validates_exact_selectors() -> None:
    with pytest.raises(ValueError, match="selectors must be unique"):
        _policy(
            loop_contracts=(
                {
                    "path": "src/numeric.py",
                    "function": "project",
                    "array_variable": "values",
                },
                {
                    "path": "src/numeric.py",
                    "function": "project",
                    "array_variable": "values",
                },
            )
        )
    with pytest.raises(ValueError, match="relative POSIX path"):
        _policy(
            loop_contracts=(
                {
                    "path": "../outside.py",
                    "function": "project",
                    "array_variable": "values",
                },
            )
        )
    with pytest.raises(ValueError, match="dotted identifiers"):
        _policy(
            loop_contracts=(
                {
                    "path": "src/numeric.py",
                    "function": "project()",
                    "array_variable": "values",
                },
            )
        )


def test_invalid_helper_configuration_is_rejected() -> None:
    with pytest.raises(ValueError, match="dotted identifiers"):
        _policy(array_constructors=("np.asarray; malicious()",))


def test_feature_registration_preserves_configured_finding_behavior(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "src/numerics/operations.py"
    source_path.parent.mkdir(parents=True)
    source_path.write_text("result = np.asarray(values.tolist())\n", encoding="utf-8")
    relative_path = Path("src/numerics/operations.py")
    policy = _policy(source_paths=("src/numerics/*.py",))
    config = QualityGateConfig.model_validate(
        {"schema_version": 1, "checks": {"array_representation_churn": policy}},
        strict=True,
    )

    assert isinstance(ALPHUS_FEATURE, FindingBuiltinFeature)
    assert ALPHUS_FEATURE.definition.policy_model is ArrayRepresentationPolicy
    resolved = resolve_array_representation_policy(config)
    assert type(resolved) is ArrayRepresentationPolicy
    expected = check_array_representation(tmp_path, [relative_path], policy)
    assert expected
    assert (
        run_array_representation_feature(tmp_path, [relative_path], resolved)
        == expected
    )
    assert (
        run_builtin_rule(
            "array-representation-churn", tmp_path, [relative_path], config
        )
        == expected
    )
