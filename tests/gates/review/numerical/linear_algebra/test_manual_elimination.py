from pathlib import Path

from alphus.config import ManualEliminationPolicy, QualityGateConfig
from alphus.execution.dispatch import run_builtin_rule
from alphus.gates.review.numerical.linear_algebra.manual_elimination import (
    ALPHUS_FEATURE,
    check_manual_elimination,
    manual_elimination_sites,
    resolve_manual_elimination_policy,
    run_manual_elimination_feature,
)
from alphus.plugins.builtin import FindingBuiltinFeature

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


def test_feature_registration_preserves_configured_finding_behavior(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "src/numerics/solver.py"
    source_path.parent.mkdir(parents=True)
    source_path.write_text(_SOURCE, encoding="utf-8")
    relative_path = Path("src/numerics/solver.py")
    policy = _policy()
    config = QualityGateConfig.model_validate(
        {"schema_version": 1, "checks": {"manual_elimination": policy}}, strict=True
    )

    assert isinstance(ALPHUS_FEATURE, FindingBuiltinFeature)
    assert ALPHUS_FEATURE.definition.policy_model is ManualEliminationPolicy
    resolved = resolve_manual_elimination_policy(config)
    assert type(resolved) is ManualEliminationPolicy
    expected = check_manual_elimination(tmp_path, [relative_path], policy)
    assert expected
    assert (
        run_manual_elimination_feature(tmp_path, [relative_path], resolved) == expected
    )
    assert (
        run_builtin_rule("manual-elimination", tmp_path, [relative_path], config)
        == expected
    )
