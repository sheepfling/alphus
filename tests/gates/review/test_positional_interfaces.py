"""Conservative tests for same-type Python positional parameter advice."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest
from pydantic import ValidationError

from alphus.config import PositionalInterfacePolicy
from alphus.contracts.findings import Finding
from alphus.gates.review.positional_interfaces import (
    check_positional_interfaces,
    positional_interface_findings,
)

_POLICY = PositionalInterfacePolicy(extensions=(".py",))
_RULE_ID = "alphus/python/none/correctness/confusable-positional-parameters"


def analyze(source: str, policy: PositionalInterfacePolicy = _POLICY) -> list[Finding]:
    return positional_interface_findings(dedent(source).strip(), policy)


def test_reports_a_run_of_directly_annotated_same_type_parameters() -> None:
    findings = analyze(
        """
        def interpolate(start: float, end: float, amount: float) -> float:
            return start + (end - start) * amount
        """
    )

    assert len(findings) == 1
    assert findings[0].rule_id == _RULE_ID
    assert findings[0].line == 1
    assert findings[0].severity == "info"
    assert "start, end, amount" in findings[0].message
    assert "no incorrect call is inferred" in findings[0].message


def test_default_and_positional_only_parameters_count_but_keyword_only_do_not() -> None:
    findings = analyze(
        """
        def project(x: float, y: float = 0.0, /, scale: float = 1.0, *, precision: float = 2.0):
            return x, y, scale, precision
        """
    )

    assert len(findings) == 1
    assert "x, y, scale" in findings[0].message
    assert "precision" not in findings[0].message


def test_variadic_parameters_do_not_join_or_extend_positional_runs() -> None:
    findings = analyze(
        """
        def compare(lower: int, upper: int, *rest: int, mode: int = 0):
            return lower, upper, rest, mode
        """
    )

    assert len(findings) == 1
    assert "lower, upper" in findings[0].message
    assert "rest" not in findings[0].message
    assert "mode" not in findings[0].message


def test_short_heterogeneous_signatures_named_options_and_distinct_types_pass() -> None:
    findings = analyze(
        """
        from dataclasses import dataclass

        @dataclass(frozen=True)
        class Latitude:
            degrees: float

        @dataclass(frozen=True)
        class Longitude:
            degrees: float

        def locate(latitude: Latitude, longitude: Longitude):
            return latitude, longitude

        def configure(*, minimum: float, maximum: float):
            return minimum, maximum

        def describe(count: int, threshold: float, label: str):
            return count, threshold, label
        """
    )

    assert findings == []


def test_aliases_and_forward_reference_strings_are_not_type_evidence() -> None:
    findings = analyze(
        """
        from builtins import float as Scalar

        Distance = float

        def aliases(start: Distance, end: Distance):
            return start, end

        def imported_alias(start: Scalar, end: Scalar):
            return start, end

        def forward_refs(start: "float", end: "float"):
            return start, end
        """
    )

    assert findings == []


def test_builtin_shadowing_in_module_and_class_namespaces_suppresses_advice() -> None:
    findings = analyze(
        """
        int = type("int", (), {})

        def module_scope(left: int, right: int):
            return left, right

        class LocalTypes:
            float = object()

            def class_scope(self, left: float, right: float):
                return left, right
        """
    )

    assert findings == []


def test_unknown_decorators_overrides_inherited_methods_and_generated_init_are_skipped() -> (
    None
):
    findings = analyze(
        """
        from dataclasses import dataclass
        from typing import override

        @dataclass
        class Record:
            first: float
            second: float

        class Base:
            def update(self, left: float, right: float):
                return left, right

        class Child(Base):
            @override
            def update(self, left: float, right: float):
                return left, right

        @wraps_signature
        def decorated(left: float, right: float):
            return left, right
        """
    )

    # Only the undecorated, locally declared Base method is in scope. The
    # dataclass's synthesized __init__, decorated callable, and inherited
    # implementation are deliberately not inferred.
    assert len(findings) == 1
    assert findings[0].line == 10


def test_nested_and_conditionally_defined_functions_are_ambiguous() -> None:
    findings = analyze(
        """
        if enabled:
            def conditional(left: float, right: float):
                return left, right

        def outer():
            def nested(left: float, right: float):
                return left, right
            return nested
        """
    )

    assert findings == []


def test_configuration_controls_severity_and_rule_enablement() -> None:
    source = "def transform(left: float, right: float):\n return left, right\n"
    policy = PositionalInterfacePolicy(extensions=(".py",), severity="warning")
    assert positional_interface_findings(source, policy)[0].severity == "warning"

    disabled = policy.model_copy(update={"report_same_type_primitives": False})
    assert positional_interface_findings(source, disabled) == []

    with pytest.raises(ValidationError):
        PositionalInterfacePolicy(extensions=(".py",), severity="fatal")

    with pytest.raises(ValidationError, match="only .py"):
        PositionalInterfacePolicy(extensions=(".js",))


def test_symmetric_and_compatibility_paths_can_be_excluded_with_reasons_in_policy(
    tmp_path: Path,
) -> None:
    (tmp_path / "symmetric_operations.py").write_text(
        "def distance_squared(x: float, y: float):\n return x * x + y * y\n",
        encoding="utf-8",
    )
    (tmp_path / "legacy.py").write_text(
        "def legacy_scale(width: float, height: float):\n return width, height\n",
        encoding="utf-8",
    )
    (tmp_path / "coordinates.py").write_text(
        "def point(x: float, y: float):\n return x, y\n", encoding="utf-8"
    )
    policy = PositionalInterfacePolicy(
        extensions=(".py",), exclude=("symmetric_operations.py", "legacy.py")
    )

    findings = check_positional_interfaces(
        tmp_path,
        [
            Path("symmetric_operations.py"),
            Path("legacy.py"),
            Path("coordinates.py"),
        ],
        policy,
    )

    assert len(findings) == 1
    assert findings[0].path == "coordinates.py"


def test_non_python_inventory_is_ignored() -> None:
    assert check_positional_interfaces(Path.cwd(), [Path("source.cpp")], _POLICY) == []
