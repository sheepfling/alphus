"""Numeric warnings match explicit arithmetic patterns without guessing units."""

from pathlib import Path

from alphus.config import NumericLiteralPolicy, NumericLiteralSpec
from alphus.contracts.rule_tags import Framework, Scope
from alphus.gates.review.numeric_engine import (
    NumericCatalog,
    NumericContext,
    NumericOccurrence,
    NumericOperation,
    match_numeric_occurrences,
)
from alphus.gates.review.numeric_literals import (
    check_numeric_literals,
    numeric_literal_findings,
)


def _policy(
    *,
    math_constants: bool = True,
    constants: tuple[NumericLiteralSpec, ...] = (),
) -> NumericLiteralPolicy:
    return NumericLiteralPolicy(
        extensions=(".py",), math_constants=math_constants, constants=constants
    )


def test_math_catalog_reports_arithmetic_at_literal_source_lines() -> None:
    source = (
        "circumference = 2 * 3.14 * radius\n"
        "growth = amount * 2.718281828459045\n"
        "turn = radians / 6.283185307179586\n"
        "area = 3.141592653589793 * radius ** 2\n"
    )

    findings = numeric_literal_findings(source, _policy())

    assert [(finding.line, finding.rule_id) for finding in findings] == [
        (1, "alphus/python/none/style/inline-constant"),
        (2, "alphus/python/none/style/inline-constant"),
        (3, "alphus/python/none/style/inline-constant"),
        (4, "alphus/python/none/style/inline-constant"),
    ]
    assert all("possible inline" in finding.message for finding in findings)
    assert "math.pi" in findings[0].message
    assert "math.e" in findings[1].message
    assert "math.tau" in findings[2].message


def test_named_library_data_and_assertion_expectations_are_allowed() -> None:
    source = (
        "import math\n"
        "TAU = 6.28318\n"
        "PI: float = 3.14\n"
        "area = math.pi * radius ** 2\n"
        "samples = [3.14, 2.71828, 6.28318]\n"
        "metadata = {'measurement': 3.14}\n"
        "assert actual == 2 * 3.14\n"
        "assert actual == 1 + 2.71828\n"
        "expected = 3.14\n"
    )

    assert numeric_literal_findings(source, _policy()) == []


def test_catalog_matches_exact_values_without_nearby_value_inference() -> None:
    source = (
        "first = radius * 3.14001\n"
        "second = amount * 2.71829\n"
        "third = turns * 6.28319\n"
        "count = items * 1000\n"
        "acceleration = mass * 9.81\n"
        "temperature = value + 273.15\n"
    )

    assert numeric_literal_findings(source, _policy()) == []


def test_math_catalog_can_be_disabled_without_disabling_custom_constants() -> None:
    gravity = NumericLiteralSpec(
        name="standard gravity", values=(9.80665,), replacement="STANDARD_GRAVITY"
    )
    source = "area = 3.14 * radius\nforce = mass * 9.80665\n"

    findings = numeric_literal_findings(
        source, _policy(math_constants=False, constants=(gravity,))
    )

    assert [(finding.line, finding.rule_id) for finding in findings] == [
        (2, "alphus/python/none/style/inline-constant")
    ]
    assert "STANDARD_GRAVITY" in findings[0].message


def test_explicit_conversion_requires_multiply_or_divide_and_a_unit_token() -> None:
    conversion = NumericLiteralSpec(
        name="feet to metres",
        values=(0.3048,),
        kind="conversion",
        replacement="feet_to_metres(value)",
        name_tokens=("feet",),
    )
    source = (
        "metres = reading_feet * 0.3048\n"
        "feet = reading.metres / 0.3048\n"
        "unlabelled = reading * 0.3048\n"
        "unrelated = defeet * 0.3048\n"
        "offset_feet = reading_feet + 0.3048\n"
        "power_feet = reading_feet ** 0.3048\n"
        "floor_feet = reading_feet // 0.3048\n"
    )

    findings = numeric_literal_findings(source, _policy(constants=(conversion,)))

    assert [(finding.line, finding.rule_id) for finding in findings] == [
        (1, "alphus/python/none/style/inline-conversion")
    ]
    assert "feet_to_metres(value)" in findings[0].message


def test_conversion_unit_tokens_use_attributes_or_enclosing_function_name() -> None:
    conversion = NumericLiteralSpec(
        name="milliseconds to seconds",
        values=(1000,),
        kind="conversion",
        replacement="milliseconds_to_seconds(value)",
        name_tokens=("milliseconds",),
    )
    source = (
        "seconds = sample.milliseconds / 1000\n"
        "def milliseconds_to_seconds(value):\n"
        "    return value / 1000\n"
        "async def convertMilliseconds(value):\n"
        "    return value / 1000\n"
        "def unrelated(value):\n"
        "    return value / 1000\n"
        "def milliseconds_outer(value):\n"
        "    def unrelated_inner(value):\n"
        "        return value / 1000\n"
    )

    findings = numeric_literal_findings(source, _policy(constants=(conversion,)))

    assert [finding.line for finding in findings] == [1, 3, 5]


def test_configured_factor_without_unit_tokens_is_explicitly_unrestricted() -> None:
    conversion = NumericLiteralSpec(
        name="consumer scale",
        values=(1000,),
        kind="conversion",
        replacement="SCALE_FACTOR",
    )

    findings = numeric_literal_findings(
        "scaled = value * 1000\n", _policy(constants=(conversion,))
    )

    assert [finding.rule_id for finding in findings] == [
        "alphus/python/none/style/inline-conversion"
    ]
    assert "source:" not in findings[0].message


def test_signed_literals_are_exact_and_booleans_are_not_numeric_matches() -> None:
    negative = NumericLiteralSpec(
        name="consumer signed factor", values=(-2,), replacement="SIGNED_FACTOR"
    )
    one = NumericLiteralSpec(name="consumer one", values=(1,), replacement="ONE")
    source = (
        "negative = value * -2\n"
        "positive = value * +2\n"
        "boolean = value * True\n"
        "number = value * 1\n"
    )

    findings = numeric_literal_findings(source, _policy(constants=(negative, one)))

    assert [finding.line for finding in findings] == [1, 4]


def test_binary_operations_and_duplicate_findings_are_bounded() -> None:
    source = (
        "first = value + 3.14\n"
        "second = value - 3.14\n"
        "third = value ** 3.14\n"
        "fourth = value // 3.14\n"
        "fifth = value % 3.14\n"
        "repeated = 3.14 * value * 3.14\n"
        "bitwise_or = value | 3.14\n"
        "bitwise_and = value & 3.14\n"
        "bitwise_xor = value ^ 3.14\n"
        "shift_left = value << 3.14\n"
        "shift_right = value >> 3.14\n"
        "matrix_product = value @ 3.14\n"
        "argument = consume(3.14)\n"
    )

    assert [
        finding.line for finding in numeric_literal_findings(source, _policy())
    ] == list(range(1, 13))


def test_normalized_array_division_operations_can_match_conversion_catalogs() -> None:
    conversion = NumericLiteralSpec(
        name="unit scale",
        values=(1000,),
        kind="conversion",
        replacement="named scale",
        name_tokens=("meter",),
    )
    operations = (
        NumericOperation.MULTIPLY,
        NumericOperation.DIVIDE,
        NumericOperation.MATRIX_MULTIPLY,
        NumericOperation.ELEMENTWISE_MULTIPLY,
        NumericOperation.ELEMENTWISE_DIVIDE,
        NumericOperation.ELEMENTWISE_LEFT_DIVIDE,
        NumericOperation.MATRIX_LEFT_DIVIDE,
        NumericOperation.MATRIX_RIGHT_DIVIDE,
        NumericOperation.POWER,
        NumericOperation.MATRIX_POWER,
        NumericOperation.ELEMENTWISE_POWER,
    )
    occurrences = tuple(
        NumericOccurrence(
            line=line,
            value=1000,
            context=NumericContext.BINARY_OPERATION,
            operation=operation,
            tokens=frozenset({"meter"}),
        )
        for line, operation in enumerate(operations, start=1)
    )

    findings = match_numeric_occurrences(
        occurrences,
        NumericCatalog(
            realm="test",
            framework=Framework.NONE,
            provenance=None,
            specs=(conversion,),
        ),
        scope=Scope.ANY,
    )

    assert [finding.line for finding in findings] == list(range(1, 9))


def test_scanner_preserves_scope_paths_and_warning_severity(tmp_path: Path) -> None:
    files = {
        Path("src/geometry.py"): "area = radius * 3.14\n",
        Path("tests/test_geometry.py"): "area = radius * 3.14\n",
        Path("vendor/geometry.py"): "area = radius * 3.14\n",
        Path("docs/example.md"): "area = radius * 3.14\n",
    }
    for relative, source in files.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
    policy = NumericLiteralPolicy(extensions=(".py",), exclude=("vendor/**",))

    findings = check_numeric_literals(
        tmp_path, iter((*files, Path("missing.py"))), policy
    )

    assert [(finding.path, finding.line, finding.severity) for finding in findings] == [
        ("src/geometry.py", 1, "warning"),
        ("tests/test_geometry.py", 1, "warning"),
    ]
    assert all(
        finding.rule_id == "alphus/python/none/style/inline-constant"
        for finding in findings
    )


def test_augmented_arithmetic_is_also_reviewed() -> None:
    policy = NumericLiteralPolicy(
        extensions=[".py"],
        exclude=[],
        constants=[
            NumericLiteralSpec(
                name="milliseconds",
                values=[1000],
                kind="conversion",
                replacement="named conversion",
                name_tokens=["milliseconds"],
            )
        ],
    )
    findings = numeric_literal_findings(
        "def milliseconds_to_seconds(value):\n value /= 1000\n value *= 3.14\n", policy
    )
    assert [(finding.line, finding.rule_id) for finding in findings] == [
        (2, "alphus/python/none/style/inline-conversion"),
        (3, "alphus/python/none/style/inline-constant"),
    ]


def test_named_formula_does_not_exempt_its_inline_constant() -> None:
    findings = numeric_literal_findings("AREA = 3.14 * RADIUS ** 2\n", _policy())
    assert [(finding.line, finding.rule_id) for finding in findings] == [
        (1, "alphus/python/none/style/inline-constant"),
    ]
