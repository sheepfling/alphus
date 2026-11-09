from __future__ import annotations

from pathlib import Path

from alphus.config import CholeskyRecurrencePolicy
from alphus.gates.review.numerical.linear_algebra.cholesky_recurrence import (
    check_cholesky_recurrence,
    cholesky_recurrence_lines,
)

_RECURRENCE = """\
import math

def factorize(matrix, n):
    lower = [[0.0 for _ in range(n)] for _ in range(n)]
    for i in range(n):
        for j in range(i + 1):
            partial = sum(lower[i][k] * lower[j][k] for k in range(j))
            if i == j:
                lower[i][j] = math.sqrt(matrix[i][i] - partial)
            else:
                lower[i][j] = (matrix[i][j] - partial) / lower[j][j]
    return lower
"""

_WOLF_COVARIANCE = """\
import math

def _covariance(matrix, label):
    matrix_values = [_vector(row, 6, label) for row in matrix]
    lower = [[0.0] * 6 for _ in range(6)]
    for i in range(6):
        for j in range(i + 1):
            value = matrix_values[i][j] - sum(
                lower[i][k] * lower[j][k] for k in range(j)
            )
            if i == j:
                if value <= 0:
                    raise ValueError(f"{label} must be positive definite")
                lower[i][j] = math.sqrt(value)
            else:
                lower[i][j] = value / lower[j][j]
    return matrix_values
"""


def _policy(**updates: object) -> CholeskyRecurrencePolicy:
    return CholeskyRecurrencePolicy.model_validate(
        {
            "extensions": (".py",),
            "exclude": (),
            "source_paths": ("src/**/*.py",),
            "square_root_helpers": ("math.sqrt",),
            **updates,
        }
    )


def test_recognizes_coordinated_lower_factorization_recurrence() -> None:
    lines = cholesky_recurrence_lines(_RECURRENCE, _policy())
    assert len(lines) == 1
    assert lines[0] == (5, 6, 7, 11)


def test_recognizes_wolf_covariance_recurrence_with_shared_intermediate() -> None:
    lines = cholesky_recurrence_lines(_WOLF_COVARIANCE, _policy())

    assert len(lines) == 1


def test_requires_product_sum_sqrt_and_previous_diagonal_divisor() -> None:
    no_product_sum = _RECURRENCE.replace(
        "lower[i][k] * lower[j][k]", "matrix[i][k] + matrix[j][k]"
    )
    no_sqrt = _RECURRENCE.replace("math.sqrt(", "abs(")
    wrong_diagonal = _RECURRENCE.replace("lower[j][j]", "lower[i][i]")
    assert cholesky_recurrence_lines(no_product_sum, _policy()) == []
    assert cholesky_recurrence_lines(no_sqrt, _policy()) == []
    assert cholesky_recurrence_lines(wrong_diagonal, _policy()) == []


def test_import_from_aliases_shadow_sum_and_range() -> None:
    for binding in (
        "from custom import range",
        "from custom import sum",
        "from custom import iterator as range",
        "from custom import reducer as sum",
    ):
        source = _RECURRENCE.replace("import math", f"import math\n{binding}")
        assert cholesky_recurrence_lines(source, _policy()) == []


def test_sqrt_in_nested_else_branch_is_not_diagonal_evidence() -> None:
    source = _RECURRENCE.replace(
        """            if i == j:
                lower[i][j] = math.sqrt(matrix[i][i] - partial)
            else:
                lower[i][j] = (matrix[i][j] - partial) / lower[j][j]
""",
        """            if i == j:
                lower[i][j] = matrix[i][j]
            else:
                if i < j:
                    lower[i][j] = math.sqrt(matrix[i][i] - partial)
                else:
                    lower[i][j] = (matrix[i][j] - partial) / lower[j][j]
""",
    )
    assert cholesky_recurrence_lines(source, _policy()) == []


def test_scope_and_configured_sqrt_helper_are_respected(tmp_path: Path) -> None:
    target = tmp_path / "src" / "covariance.py"
    target.parent.mkdir()
    target.write_text(_RECURRENCE, encoding="utf-8")
    findings = check_cholesky_recurrence(
        tmp_path,
        [Path("src/covariance.py")],
        _policy(source_paths=("src/*.py",)),
    )
    assert len(findings) == 1
    assert (
        findings[0].rule_id
        == "alphus/python/none/maintainability/manual-cholesky-recurrence"
    )
    assert (
        check_cholesky_recurrence(
            tmp_path,
            [Path("src/covariance.py")],
            _policy(source_paths=("src/*.py",), square_root_helpers=("numpy.sqrt",)),
        )
        == []
    )

