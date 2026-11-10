from pathlib import Path

from alphus.config import ManualEliminationPolicy
from alphus.gates.review.numerical.linear_algebra.manual_elimination import (
    check_manual_elimination,
    manual_elimination_sites,
)

_SOURCE = """\
def invert_matrix(matrix, size):
    for column in range(size):
        pivot_row = max(range(column, size), key=lambda candidate: abs(matrix[candidate][column]))
        matrix[column], matrix[pivot_row] = matrix[pivot_row], matrix[column]
        diagonal = matrix[column][column]
        matrix[column] = [value / diagonal for value in matrix[column]]
        for row in range(size):
            if row != column:
                factor = matrix[row][column]
                matrix[row] = [
                    current - factor * pivot_value
                    for current, pivot_value in zip(matrix[row], matrix[column])
                ]
"""

_AUGMENTED = """\
def _inverse(matrix):
    size = len(matrix)
    rows = [
        list(row) + [float(i == j) for j in range(size)] for i, row in enumerate(matrix)
    ]
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(rows[row][column]))
        rows[column], rows[pivot] = rows[pivot], rows[column]
        divisor = rows[column][column]
        if divisor == 0:
            raise ValueError("singular")
        rows[column] = [value / divisor for value in rows[column]]
        for i in range(size):
            if i != column:
                factor = rows[i][column]
                rows[i] = [
                    value - factor * other
                    for value, other in zip(rows[i], rows[column], strict=True)
                ]
    return [row[size:] for row in rows]
"""


def _policy(**updates: object) -> ManualEliminationPolicy:
    return ManualEliminationPolicy.model_validate(
        {
            "extensions": (".py",),
            "exclude": (),
            "source_paths": ("src/numerics/*.py",),
            "function_names": ("invert_matrix",),
            "matrix_name": "matrix",
            **updates,
        }
    )


def test_matches_complete_pivot_swap_normalize_and_eliminate_kernel() -> None:
    sites = manual_elimination_sites(_SOURCE, _policy())
    assert [
        (site.pivot_line, site.swap_line, site.normalize_line, site.update_line)
        for site in sites
    ] == [(3, 4, 6, 10)]


def test_matches_augmented_inverse_with_zero_guard_and_right_half_return() -> None:
    sites = manual_elimination_sites(_AUGMENTED, _policy(function_names=("_inverse",)))

    assert len(sites) == 1
    assert (sites[0].pivot_line, sites[0].swap_line, sites[0].normalize_line) == (
        7,
        8,
        12,
    )


def test_augmented_inverse_respects_configured_function_scope() -> None:
    nested = "def wrapper():\\n" + "\\n".join(
        "    " + line for line in _AUGMENTED.splitlines()
    )

    assert manual_elimination_sites(
        nested, _policy(function_names=("_inverse",))
    ) == []


def test_augmented_inverse_requires_identity_initialization_and_right_half() -> None:
    wrong_identity = _AUGMENTED.replace("float(i == j)", "float(i != j)")
    wrong_result = _AUGMENTED.replace("row[size:]", "row[:size]")
    no_singularity_guard = _AUGMENTED.replace(
        '        if divisor == 0:\n            raise ValueError("singular")\n', ""
    )

    assert (
        manual_elimination_sites(wrong_identity, _policy(function_names=("_inverse",)))
        == []
    )
    assert (
        manual_elimination_sites(wrong_result, _policy(function_names=("_inverse",)))
        == []
    )
    assert (
        manual_elimination_sites(
            no_singularity_guard, _policy(function_names=("_inverse",))
        )
        == []
    )


def test_requires_each_coordinated_operation_and_same_pivot() -> None:
    no_swap = _SOURCE.replace(
        "        matrix[column], matrix[pivot_row] = matrix[pivot_row], matrix[column]\n",
        "",
    )
    mismatched_elimination = _SOURCE.replace(
        "factor = matrix[row][column]", "factor = matrix[row][pivot_row]"
    )
    unpivoted = _SOURCE.replace(
        "pivot_row = max(range(column, size), key=lambda candidate: "
        "abs(matrix[candidate][column]))",
        "pivot_row = column",
    )

    assert manual_elimination_sites(no_swap, _policy()) == []
    assert manual_elimination_sites(mismatched_elimination, _policy()) == []
    assert manual_elimination_sites(unpivoted, _policy()) == []


def test_configured_scope_function_and_nested_definition_are_respected(
    tmp_path: Path,
) -> None:
    target = tmp_path / "src/numerics/solver.py"
    target.parent.mkdir(parents=True)
    target.write_text(_SOURCE, encoding="utf-8")
    paths = (Path("src/numerics/solver.py"),)

    findings = check_manual_elimination(tmp_path, paths, _policy())
    assert len(findings) == 1
    assert "does not establish that an inverse is needed" in findings[0].message
    assert not check_manual_elimination(
        tmp_path, paths, _policy(exclude=("src/numerics/solver.py",))
    )
    assert not check_manual_elimination(
        tmp_path, paths, _policy(function_names=("other",))
    )
    assert (
        manual_elimination_sites(
            "def wrapper():\n"
            + "\n".join("    " + line for line in _SOURCE.splitlines()),
            _policy(),
        )
        == []
    )


def test_matrix_alias_and_wrong_matrix_name_are_unknown() -> None:
    alias = _SOURCE.replace(
        "    for column in range(size):",
        "    a = matrix\n    for column in range(size):",
    ).replace("matrix[", "a[")
    other_matrix = _SOURCE.replace("matrix[", "other[")

    assert manual_elimination_sites(alias, _policy()) == []
    assert manual_elimination_sites(other_matrix, _policy()) == []


def test_module_level_range_shadowing_makes_loop_semantics_unknown() -> None:
    shadowed = "range = lambda count: ()\n\n" + _SOURCE

    assert manual_elimination_sites(shadowed, _policy()) == []
