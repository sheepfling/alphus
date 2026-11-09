"""Find one configured explicit ZYX Euler rotation matrix formula."""

from __future__ import annotations

import ast
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from alphus.config import EulerRotationMatrixPolicy
from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import Category, Framework, Scope, rule_tag
from alphus.gates.review.numerical.common.ast_helpers import (
    configured_function_observations,
    qualified_call_name,
    redefined_function_names,
)
from alphus.support.inventory import matches_path
from alphus.support.source_text import read_python_source

_RULE_ID = rule_tag(
    Scope.PYTHON,
    Framework.NONE,
    Category.MAINTAINABILITY,
    "euler-rotation-matrix",
)


@dataclass(frozen=True, slots=True)
class _Site:
    function: str
    line: int


def _expected_matrix(symbols: tuple[str, str, str, str, str, str]) -> ast.expr:
    cy, sy, cp, sp, cr, sr = symbols
    formula = (
        f"[[{cy} * {cp}, {cy} * {sp} * {sr} - {sy} * {cr}, "
        f"{cy} * {sp} * {cr} + {sy} * {sr}], "
        f"[{sy} * {cp}, {sy} * {sp} * {sr} + {cy} * {cr}, "
        f"{sy} * {sp} * {cr} - {cy} * {sr}], "
        f"[-{sp}, {cp} * {sr}, {cp} * {cr}]]"
    )
    return ast.parse(formula, mode="eval").body


def _helpers_match(assignment: ast.Assign, policy: EulerRotationMatrixPolicy) -> bool:
    if len(assignment.targets) != 1 or not isinstance(assignment.targets[0], ast.Tuple):
        return False
    if (
        tuple(
            element.id if isinstance(element, ast.Name) else ""
            for element in assignment.targets[0].elts
        )
        != policy.trig_symbols
    ):
        return False
    value = assignment.value
    if not isinstance(value, ast.Tuple) or len(value.elts) != 6:
        return False
    expected = (
        (policy.cosine_helpers, policy.angles[0]),
        (policy.sine_helpers, policy.angles[0]),
        (policy.cosine_helpers, policy.angles[1]),
        (policy.sine_helpers, policy.angles[1]),
        (policy.cosine_helpers, policy.angles[2]),
        (policy.sine_helpers, policy.angles[2]),
    )
    for node, (helpers, angle) in zip(value.elts, expected, strict=True):
        if not isinstance(node, ast.Call) or node.keywords or len(node.args) != 1:
            return False
        if qualified_call_name(node.func) not in helpers:
            return False
        if not isinstance(node.args[0], ast.Name) or node.args[0].id != angle:
            return False
    return True


def _matches_matrix(actual: ast.expr, expected: ast.expr) -> bool:
    return ast.dump(actual, include_attributes=False) == ast.dump(
        expected, include_attributes=False
    )


def _match(
    function: ast.FunctionDef, policy: EulerRotationMatrixPolicy
) -> _Site | None:
    if function.name not in policy.function_names:
        return None
    body = function.body[1:] if ast.get_docstring(function) else function.body
    helper_bindings = [
        statement
        for statement in body
        if isinstance(statement, ast.Assign) and _helpers_match(statement, policy)
    ]
    if len(helper_bindings) != 1:
        return None
    aliases = set(policy.trig_symbols)
    if sum(
        1
        for node in ast.walk(function)
        if isinstance(node, ast.Name)
        and isinstance(node.ctx, ast.Store)
        and node.id in aliases
    ) != len(aliases):
        return None
    expected = _expected_matrix(policy.trig_symbols)
    matrix_assignments = [
        statement
        for statement in body
        if isinstance(statement, ast.Assign)
        and _matches_matrix(statement.value, expected)
    ]
    if len(matrix_assignments) != 1:
        return None
    matrix_assignment = matrix_assignments[0]
    return _Site(function.name, matrix_assignment.lineno)


def euler_rotation_matrix_sites(
    source: str, policy: EulerRotationMatrixPolicy
) -> list[_Site]:
    """Return exact configured ZYX matrix formulas with matching trig aliases."""
    shadowed = redefined_function_names(source, policy.function_names)
    return configured_function_observations(
        source,
        policy.function_names,
        lambda function: (
            None if function.name in shadowed else _match(function, policy)
        ),
        lambda site: (site.function, site.line),
    )


def check_euler_rotation_matrix(
    root: Path,
    paths: Iterable[Path],
    policy: EulerRotationMatrixPolicy,
) -> list[Finding]:
    checkout = root.resolve(strict=True)
    findings: list[Finding] = []
    for relative in sorted(paths):
        name = relative.as_posix()
        if (
            relative.suffix != ".py"
            or any(matches_path(name, pattern) for pattern in policy.exclude)
            or not any(matches_path(name, pattern) for pattern in policy.source_paths)
        ):
            continue
        path = checkout / relative
        if not path.is_file():
            continue
        for site in euler_rotation_matrix_sites(read_python_source(path), policy):
            findings.append(
                Finding(
                    rule_id=_RULE_ID,
                    path=name,
                    line=site.line,
                    message=(
                        f"Configured function {site.function!r} assigns the exact "
                        "configured ZYX Euler rotation matrix. Review whether an "
                        "existing rotation API fits; confirm angle units, frame, "
                        "composition order, handedness, and matrix use. The syntax "
                        "does not establish a defect or automatic replacement."
                    ),
                    severity=policy.severity,
                )
            )
    return findings

