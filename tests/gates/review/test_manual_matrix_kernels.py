from pathlib import Path

import pytest
from pydantic import ValidationError

from alphus.config import ManualMatrixKernelPolicy
from alphus.gates.review.manual_matrix_kernels import (
    check_manual_matrix_kernels,
    matrix_kernel_lines,
)

_PRODUCT = """result = [
    [
        sum(left[i][k] * right[k][j] for k in range(inner))
        for j in range(columns)
    ]
    for i in range(rows)
]
"""


def _policy(**overrides: object) -> ManualMatrixKernelPolicy:
    return ManualMatrixKernelPolicy(
        extensions=(".py",), source_paths=("src/numerics/*.py",), **overrides
    )


def test_recognizes_nested_indexed_sum_product_and_related_lines() -> None:
    assert matrix_kernel_lines(_PRODUCT) == [(1, 2, 3)]


def test_ignores_other_nested_comprehensions_and_matrix_api_calls() -> None:
    source = """\
result = [[left[i] + right[j] for j in range(width)] for i in range(height)]
result = left @ right
result = numpy.matmul(left, right)
"""
    assert matrix_kernel_lines(source) == []


def test_ignores_rebound_sum_or_range_names() -> None:
    assert matrix_kernel_lines("sum = custom_sum\n" + _PRODUCT) == []
    assert matrix_kernel_lines("range = coordinates\n" + _PRODUCT) == []
    assert (
        matrix_kernel_lines(
            "def calculate(sum):\n" + "    " + _PRODUCT.replace("\n", "\n    ")
        )
        == []
    )


def test_scans_only_declared_paths_and_respects_exclusions(tmp_path: Path) -> None:
    source = tmp_path / "src/numerics/kernel.py"
    source.parent.mkdir(parents=True)
    source.write_text(_PRODUCT, encoding="utf-8")
    outside = tmp_path / "src/other.py"
    outside.write_text(_PRODUCT, encoding="utf-8")

    findings = check_manual_matrix_kernels(
        tmp_path,
        [Path("src/numerics/kernel.py"), Path("src/other.py")],
        _policy(),
    )
    assert len(findings) == 1
    assert findings[0].path == "src/numerics/kernel.py"
    assert findings[0].line == 1
    assert "inner comprehension at line 2" in findings[0].message

    excluded = _policy(exclude=("src/numerics/**",))
    assert not check_manual_matrix_kernels(
        tmp_path, [Path("src/numerics/kernel.py")], excluded
    )


def test_policy_requires_an_explicit_numeric_scope() -> None:
    with pytest.raises(ValidationError, match="source_paths"):
        ManualMatrixKernelPolicy(extensions=(".py",))
