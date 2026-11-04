"""Repeated numeric limit review stays scoped to declared analysis roles."""

from pathlib import Path

from alphus.config import NumericLimitRole, RepeatedNumericLimitPolicy
from alphus.gates.review.repeated_numeric_limits import check_repeated_numeric_limits


def _policy() -> RepeatedNumericLimitPolicy:
    return RepeatedNumericLimitPolicy(
        extensions=(".py",),
        source_paths=("src/analysis/**",),
        roles=(
            NumericLimitRole(
                name="AST traversal ceiling",
                identifiers=("node_count", "ast_nodes"),
            ),
        ),
    )


def test_repeated_cap_on_one_declared_analysis_boundary_reports_all_spans(
    tmp_path: Path,
) -> None:
    (tmp_path / "src/analysis").mkdir(parents=True)
    (tmp_path / "src/analysis/walk.py").write_text(
        "if node_count > 512:\n    stop()\n", encoding="utf-8"
    )
    (tmp_path / "src/analysis/visit.py").write_text(
        "if len(ast_nodes) > 512:\n    stop()\n", encoding="utf-8"
    )

    findings = check_repeated_numeric_limits(
        tmp_path,
        (Path("src/analysis/walk.py"), Path("src/analysis/visit.py")),
        _policy(),
    )

    assert [(finding.path, finding.line) for finding in findings] == [
        ("src/analysis/visit.py", 1),
        ("src/analysis/walk.py", 1),
    ]
    assert all(finding.severity == "info" for finding in findings)
    assert all("512" in finding.message for finding in findings)
    assert all("AST traversal ceiling" in finding.message for finding in findings)
    assert all("src/analysis/visit.py:1" in finding.message for finding in findings)
    assert all("src/analysis/walk.py:1" in finding.message for finding in findings)
    assert all("Uncertain:" in finding.message for finding in findings)


def test_equal_caps_with_distinct_roles_common_literals_and_loop_bounds_are_quiet(
    tmp_path: Path,
) -> None:
    (tmp_path / "src/analysis").mkdir(parents=True)
    source = (
        "if node_count > 512:\n    stop()\n"
        "if worker_count > 512:\n    stop()\n"
        "if node_count > 1:\n    stop()\n"
        "if len(ast_nodes) > 1:\n    stop()\n"
        "if node_count > 0:\n    stop()\n"
        "if len(ast_nodes) > 0:\n    stop()\n"
        "if node_count > -1:\n    stop()\n"
        "if len(ast_nodes) > -1:\n    stop()\n"
        "for index in range(512):\n    stop()\n"
    )
    (tmp_path / "src/analysis/guards.py").write_text(source, encoding="utf-8")
    policy = RepeatedNumericLimitPolicy(
        extensions=(".py",),
        source_paths=("src/analysis/**",),
        roles=(
            NumericLimitRole(name="AST traversal ceiling", identifiers=("node_count",)),
            NumericLimitRole(name="worker pool size", identifiers=("worker_count",)),
        ),
    )

    assert (
        check_repeated_numeric_limits(
            tmp_path, (Path("src/analysis/guards.py"),), policy
        )
        == []
    )


def test_named_shared_constant_is_not_a_literal_and_selection_is_required(
    tmp_path: Path,
) -> None:
    (tmp_path / "src/analysis").mkdir(parents=True)
    (tmp_path / "src/analysis/guards.py").write_text(
        "MAX_NODES = 512\n"
        "if node_count > MAX_NODES:\n    stop()\n"
        "if len(ast_nodes) > MAX_NODES:\n    stop()\n",
        encoding="utf-8",
    )
    paths = (Path("src/analysis/guards.py"),)

    assert check_repeated_numeric_limits(tmp_path, paths, _policy()) == []
    unselected = RepeatedNumericLimitPolicy(
        extensions=(".py",),
        source_paths=("src/config/**",),
        roles=_policy().roles,
    )
    assert check_repeated_numeric_limits(tmp_path, paths, unselected) == []


def test_test_and_generated_paths_are_always_skipped(tmp_path: Path) -> None:
    for directory in ("tests/analysis", "src/generated"):
        (tmp_path / directory).mkdir(parents=True)
        (tmp_path / directory / "guards.py").write_text(
            "if node_count > 512:\n    stop()\n", encoding="utf-8"
        )
        (tmp_path / directory / "visits.py").write_text(
            "if len(ast_nodes) > 512:\n    stop()\n", encoding="utf-8"
        )
    paths = tuple(
        Path(directory) / name
        for directory in ("tests/analysis", "src/generated")
        for name in ("guards.py", "visits.py")
    )

    policy = RepeatedNumericLimitPolicy(
        extensions=(".py",),
        source_paths=("**",),
        roles=_policy().roles,
    )
    assert check_repeated_numeric_limits(tmp_path, paths, policy) == []
