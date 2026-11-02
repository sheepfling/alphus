from __future__ import annotations

from pathlib import Path

from alphus.config import ArrayRepresentationPolicy
from alphus.gates.review.array_representation import (
    check_array_representation,
    representation_churn_lines,
)


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


def test_invalid_helper_configuration_is_rejected() -> None:
    try:
        _policy(array_constructors=("np.asarray; malicious()",))
    except ValueError as error:
        assert "dotted identifiers" in str(error)
    else:
        raise AssertionError("invalid constructor helper must be rejected")
