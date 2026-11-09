"""Find one coordinated lower-triangular factorization recurrence shape."""

from __future__ import annotations

import ast
from collections.abc import Iterable
from pathlib import Path

from alphus.config import CholeskyRecurrencePolicy
from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import Category, Framework, Scope, rule_tag
from alphus.gates.review.numerical.common.ast_helpers import qualified_call_name
from alphus.support.inventory import matches_path
from alphus.support.source_text import read_python_source

_RULE_ID = rule_tag(
    Scope.PYTHON,
    Framework.NONE,
    Category.MAINTAINABILITY,
    "manual-cholesky-recurrence",
)


def _index(node: ast.expr, base: str, first: str, second: str) -> bool:
    match node:
        case ast.Subscript(
            value=ast.Subscript(
                value=ast.Name(id=base_name), slice=ast.Name(id=first_name)
            ),
            slice=ast.Name(id=second_name),
        ):
            return (base_name, first_name, second_name) == (base, first, second)
        case _:
            return False


def _simple_range_loop(node: ast.AST) -> tuple[str, ast.For] | None:
    match node:
        case (
            ast.For(
                target=ast.Name(id=target),
                iter=ast.Call(func=ast.Name(id="range"), args=args, keywords=[]),
            ) as loop
        ) if args:
            return target, loop
        case _:
            return None


def _is_triangular_bound(node: ast.For, row: str) -> bool:
    match node.iter:
        case ast.Call(
            func=ast.Name(id="range"),
            args=[
                ast.BinOp(
                    left=ast.Name(id=bound),
                    op=ast.Add(),
                    right=ast.Constant(value=1),
                )
            ],
            keywords=[],
        ) if bound == row:
            return True
        case _:
            return False


def _shadows_builtins(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        match node:
            case ast.Name(id=name, ctx=ast.Store()) if name in {"sum", "range"}:
                return True
            case ast.arg(arg=name) if name in {"sum", "range"}:
                return True
            case ast.FunctionDef(name=name) | ast.AsyncFunctionDef(name=name) if (
                name
                in {
                    "sum",
                    "range",
                }
            ):
                return True
            case ast.Import(names=names) if any(
                alias.asname == "sum"
                or alias.asname == "range"
                or alias.name.split(".", maxsplit=1)[0] in {"sum", "range"}
                for alias in names
            ):
                return True
            case ast.ImportFrom(names=names) if any(
                (alias.asname or alias.name) in {"sum", "range"} for alias in names
            ):
                return True
            case _:
                continue
    return False


def _assignment_target(node: ast.AST) -> ast.expr | None:
    match node:
        case ast.Assign(targets=[target]):
            return target
        case _:
            return None


def _assignment_value(node: ast.AST) -> ast.expr | None:
    match node:
        case ast.Assign(value=value):
            return value
        case _:
            return None


def _index_parts(node: ast.expr) -> tuple[str, str, str] | None:
    match node:
        case ast.Subscript(
            value=ast.Subscript(value=ast.Name(id=base), slice=ast.Name(id=first)),
            slice=ast.Name(id=second),
        ):
            return base, first, second
        case _:
            return None


def _sum_product_name(
    statements: Iterable[ast.stmt], row: str, column: str
) -> tuple[str | None, int, str, ast.Call] | None:
    for statement in statements:
        for node in ast.walk(statement):
            match node:
                case (
                    ast.Call(
                        func=ast.Name(id="sum"),
                        args=[
                            ast.GeneratorExp(
                                elt=ast.BinOp(
                                    left=left,
                                    op=ast.Mult(),
                                    right=right,
                                ),
                                generators=[
                                    ast.comprehension(
                                        target=ast.Name(id=index),
                                        iter=ast.Call(
                                            func=ast.Name(id="range"),
                                            args=[ast.Name(id=bound)],
                                            keywords=[],
                                        ),
                                        ifs=[],
                                        is_async=0,
                                    )
                                ],
                            )
                        ],
                        keywords=[],
                    ) as call
                ) if (
                    bound == column
                    and (left_parts := _index_parts(left)) is not None
                    and (right_parts := _index_parts(right)) is not None
                    and left_parts[0] == right_parts[0]
                    and left_parts[1:] == (row, index)
                    and right_parts[1:] == (column, index)
                ):
                    assignment = (
                        statement if _assignment_value(statement) is call else None
                    )
                    target = (
                        _assignment_target(assignment)
                        if assignment is not None
                        else None
                    )
                    return (
                        target.id if isinstance(target, ast.Name) else None,
                        call.lineno,
                        left_parts[0],
                        call,
                    )
                case _:
                    continue
    return None


def _diagonal_if(node: ast.AST, row: str, column: str) -> ast.If | None:
    match node:
        case (
            ast.If(
                test=ast.Compare(
                    left=ast.Name(id=left),
                    ops=[ast.Eq()],
                    comparators=[ast.Name(id=right)],
                )
            ) as conditional
        ) if (left, right) == (row, column):
            return conditional
        case _:
            return None


def _contains_source_index(node: ast.AST, first: str, second: str) -> bool:
    for candidate in ast.walk(node):
        match candidate:
            case ast.Subscript(
                value=ast.Subscript(value=ast.Name(), slice=ast.Name(id=a)),
                slice=ast.Name(id=b),
            ) if (a, b) == (first, second):
                return True
            case _:
                continue
    return False


def _match_function(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    sqrt_helpers: tuple[str, ...],
) -> tuple[int, int, int, int] | None:
    loops = [item for item in ast.walk(function) if _simple_range_loop(item)]
    for outer_node in loops:
        outer_match = _simple_range_loop(outer_node)
        if outer_match is None:
            continue
        row, outer = outer_match
        for inner_node in ast.walk(outer):
            inner_match = _simple_range_loop(inner_node)
            if inner_match is None or inner_node is outer:
                continue
            column, inner = inner_match
            if column == row or not _is_triangular_bound(inner, row):
                continue
            statements = inner.body
            for node in ast.walk(inner):
                diagonal = _diagonal_if(node, row, column)
                if diagonal is None:
                    continue
                sum_result = _sum_product_name(statements, row, column)
                if sum_result is None:
                    continue
                sum_name, sum_line, sum_factor, sum_call = sum_result
                factor: str | None = None
                sqrt_line: int | None = None
                diagonal_assignment: ast.Assign | None = None
                # Only a direct assignment in the equality arm is diagonal
                # evidence; walking the full If also visits its non-diagonal else.
                for candidate in ast.walk(
                    ast.Module(body=diagonal.body, type_ignores=[])
                ):
                    target = _assignment_target(candidate)
                    target_factor = (
                        _target_factor(target, row, column)
                        if target is not None
                        else None
                    )
                    if target_factor is None:
                        continue
                    match candidate:
                        case (
                            ast.Assign(
                                value=ast.Call(func=func, args=[_], keywords=[])
                            ) as assignment
                        ) if qualified_call_name(func) in sqrt_helpers:
                            sqrt_line = assignment.lineno
                            factor = target_factor
                            diagonal_assignment = assignment
                        case _:
                            continue
                if sqrt_line is None:
                    continue
                if (
                    factor is None
                    or factor != sum_factor
                    or diagonal_assignment is None
                ):
                    continue
                # Check the declared summation result is the subtractand and the
                # lower-triangle recurrence divides by the earlier diagonal.
                diagonal_value = _assignment_value(diagonal_assignment)
                if diagonal_value is None or not _uses_sum_reduction(
                    diagonal_value, sum_name, sum_call, row, column, statements
                ):
                    continue
                for candidate in ast.walk(
                    ast.Module(body=diagonal.orelse, type_ignores=[])
                ):
                    target = _assignment_target(candidate)
                    if target is None or _target_factor(target, row, column) != factor:
                        continue
                    match candidate:
                        case (
                            ast.Assign(
                                value=ast.BinOp(
                                    left=difference,
                                    op=ast.Div(),
                                    right=denominator,
                                )
                            ) as assignment
                        ) if _sum_difference(
                            difference, sum_name, sum_call, row, column, statements
                        ) and _index(denominator, factor, column, column):
                            return (
                                outer.lineno,
                                inner.lineno,
                                sum_line,
                                assignment.lineno,
                            )
                        case _:
                            continue
    return None


def _target_factor(node: ast.expr, first: str, second: str) -> str | None:
    match node:
        case ast.Subscript(
            value=ast.Subscript(value=ast.Name(id=base), slice=ast.Name(id=a)),
            slice=ast.Name(id=b),
        ) if (a, b) == (first, second):
            return base
        case _:
            return None


def _sum_difference(
    expression: ast.expr,
    sum_name: str | None,
    sum_call: ast.Call,
    row: str,
    column: str,
    statements: Iterable[ast.stmt],
) -> bool:
    """Recognize the matrix diagonal minus the lower-factor product sum."""
    match expression:
        case ast.BinOp(left=source, op=ast.Sub(), right=ast.Name(id=rhs)) if (
            sum_name is not None and rhs == sum_name
        ):
            return _contains_source_index(source, row, column)
        case ast.BinOp(left=source, op=ast.Sub(), right=ast.Call() as call) if (
            call is sum_call
        ):
            return _contains_source_index(source, row, column)
        case ast.Name(id=alias):
            assignments = [
                statement
                for statement in statements
                if isinstance(statement, ast.Assign)
                and len(statement.targets) == 1
                and isinstance(statement.targets[0], ast.Name)
                and statement.targets[0].id == alias
            ]
            return len(assignments) == 1 and _sum_difference(
                assignments[0].value, sum_name, sum_call, row, column, ()
            )
        case _:
            return False


def _uses_sum_reduction(
    node: ast.expr,
    name: str | None,
    sum_call: ast.Call,
    row: str,
    column: str,
    statements: Iterable[ast.stmt],
) -> bool:
    match node:
        case ast.Call(args=[argument]):
            return any(
                _sum_difference(
                    argument, name, sum_call, row, source_column, statements
                )
                for source_column in (row, column)
            )
        case _:
            return False


def cholesky_recurrence_lines(
    source: str, policy: CholeskyRecurrencePolicy
) -> list[tuple[int, int, int, int]]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    if _shadows_builtins(tree):
        return []
    findings: list[tuple[int, int, int, int]] = []
    for node in ast.walk(tree):
        match node:
            case ast.FunctionDef() | ast.AsyncFunctionDef():
                result = _match_function(node, policy.square_root_helpers)
                if result is not None:
                    findings.append(result)
            case _:
                continue
    return sorted(set(findings))


def check_cholesky_recurrence(
    root: Path, paths: Iterable[Path], policy: CholeskyRecurrencePolicy
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
        for outer, inner, reduction, division in cholesky_recurrence_lines(
            read_python_source(path), policy
        ):
            findings.append(
                Finding(
                    _RULE_ID,
                    name,
                    "coordinated lower-triangular recurrence uses prior-factor "
                    f"products, a configured square root, and diagonal division "
                    f"(lines {outer}, {inner}, {reduction}, {division}); review its "
                    "numerical contract and existing factorization helpers. This "
                    "does not establish invalid covariance or an incorrect result.",
                    outer,
                    policy.severity,
                )
            )
    return findings

