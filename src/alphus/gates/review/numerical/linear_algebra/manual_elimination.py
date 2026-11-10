"""Find one configured, direct-list Gauss-Jordan elimination shape."""

from __future__ import annotations

import ast
import copy
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from alphus.config import ManualEliminationPolicy
from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import Category, Framework, Scope, rule_tag
from alphus.gates.review.numerical.common.ast_helpers import (
    configured_function_observations,
)
from alphus.support.inventory import matches_path
from alphus.support.source_text import read_python_source

_RULE_ID = rule_tag(
    Scope.PYTHON, Framework.NONE, Category.MAINTAINABILITY, "manual-elimination"
)


@dataclass(frozen=True, slots=True)
class _Site:
    function: str
    pivot_line: int
    swap_line: int
    normalize_line: int
    update_line: int


def _id(node: ast.expr) -> str | None:
    return node.id if isinstance(node, ast.Name) else None


def _cell(node: ast.expr, matrix: str) -> tuple[str, str] | None:
    if (
        isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Subscript)
        and _id(node.value.value) == matrix
    ):
        row, column = _id(node.value.slice), _id(node.slice)
        if row is not None and column is not None:
            return row, column
    return None


def _row(node: ast.expr, matrix: str) -> str | None:
    if isinstance(node, ast.Subscript) and _id(node.value) == matrix:
        return _id(node.slice)
    return None


def _match(function: ast.FunctionDef, policy: ManualEliminationPolicy) -> _Site | None:
    if function.name not in policy.function_names:
        return None
    args = (*function.args.posonlyargs, *function.args.args)
    if (
        policy.matrix_name not in {argument.arg for argument in args}
        or len(args) != 2
        or function.args.defaults
        or function.args.kwonlyargs
        or function.args.vararg
        or function.args.kwarg
    ):
        return None
    body = function.body[1:] if ast.get_docstring(function) else function.body
    if len(body) != 1 or not isinstance(body[0], ast.For):
        return None
    outer = body[0]
    pivot = _id(outer.target)
    if (
        pivot is None
        or not isinstance(outer.iter, ast.Call)
        or _id(outer.iter.func) != "range"
    ):
        return None
    if len(outer.iter.args) != 1 or (size := _id(outer.iter.args[0])) is None:
        return None
    if size == policy.matrix_name or {argument.arg for argument in args} != {
        policy.matrix_name,
        size,
    }:
        return None
    if len(outer.body) != 5:
        return None

    choose, swap, diagonal_assign, normalize, eliminate = outer.body
    if not isinstance(choose, ast.Assign) or len(choose.targets) != 1:
        return None
    pivot_row = _id(choose.targets[0])
    if (
        pivot_row is None
        or not isinstance(choose.value, ast.Call)
        or _id(choose.value.func) != "max"
    ):
        return None
    if len(choose.value.args) != 1 or len(choose.value.keywords) != 1:
        return None
    candidates = choose.value.args[0]
    if (
        not isinstance(candidates, ast.Call)
        or _id(candidates.func) != "range"
        or len(candidates.args) != 2
    ):
        return None
    if tuple(map(_id, candidates.args)) != (pivot, size):
        return None
    key = choose.value.keywords[0]
    if key.arg != "key" or not isinstance(key.value, ast.Lambda):
        return None
    if len(key.value.args.args) != 1:
        return None
    candidate = key.value.args.args[0].arg
    score = key.value.body
    if (
        not isinstance(score, ast.Call)
        or _id(score.func) != "abs"
        or len(score.args) != 1
        or score.keywords
        or _cell(score.args[0], policy.matrix_name) != (candidate, pivot)
    ):
        return None

    if not isinstance(swap, ast.Assign) or len(swap.targets) != 1:
        return None
    target, value = swap.targets[0], swap.value
    if not isinstance(target, ast.Tuple) or not isinstance(value, ast.Tuple):
        return None
    if len(target.elts) != 2 or len(value.elts) != 2:
        return None
    if tuple(_row(part, policy.matrix_name) for part in target.elts) != (
        pivot,
        pivot_row,
    ) or tuple(_row(part, policy.matrix_name) for part in value.elts) != (
        pivot_row,
        pivot,
    ):
        return None

    if not isinstance(diagonal_assign, ast.Assign) or len(diagonal_assign.targets) != 1:
        return None
    diagonal = _id(diagonal_assign.targets[0])
    if diagonal is None or _cell(diagonal_assign.value, policy.matrix_name) != (
        pivot,
        pivot,
    ):
        return None

    if not isinstance(normalize, ast.Assign) or len(normalize.targets) != 1:
        return None
    normalized_row = _row(normalize.targets[0], policy.matrix_name)
    comp = normalize.value
    if (
        normalized_row != pivot
        or not isinstance(comp, ast.ListComp)
        or len(comp.generators) != 1
        or not isinstance(comp.elt, ast.BinOp)
        or not isinstance(comp.elt.op, ast.Div)
        or (value_name := _id(comp.elt.left)) is None
        or _id(comp.elt.right) != diagonal
    ):
        return None
    generator = comp.generators[0]
    if generator.ifs or generator.is_async or _id(generator.target) != value_name:
        return None
    if _row(generator.iter, policy.matrix_name) != pivot:
        return None

    if not isinstance(eliminate, ast.For) or (row := _id(eliminate.target)) is None:
        return None
    if (
        not isinstance(eliminate.iter, ast.Call)
        or _id(eliminate.iter.func) != "range"
        or len(eliminate.iter.args) != 1
        or _id(eliminate.iter.args[0]) != size
        or eliminate.iter.keywords
    ):
        return None
    if len(eliminate.body) != 1 or not isinstance(eliminate.body[0], ast.If):
        return None
    conditional = eliminate.body[0]
    if conditional.orelse or len(conditional.body) != 2:
        return None
    if not (
        isinstance(conditional.test, ast.Compare)
        and _id(conditional.test.left) == row
        and len(conditional.test.ops) == 1
        and isinstance(conditional.test.ops[0], ast.NotEq)
        and len(conditional.test.comparators) == 1
        and _id(conditional.test.comparators[0]) == pivot
    ):
        return None
    factor_assign, update = conditional.body
    if not isinstance(factor_assign, ast.Assign) or len(factor_assign.targets) != 1:
        return None
    factor = _id(factor_assign.targets[0])
    if factor is None or _cell(factor_assign.value, policy.matrix_name) != (row, pivot):
        return None
    if not isinstance(update, ast.Assign) or len(update.targets) != 1:
        return None
    if _row(update.targets[0], policy.matrix_name) != row or not isinstance(
        update.value, ast.ListComp
    ):
        return None
    update_comp = update.value
    expression = update_comp.elt
    if not (
        len(update_comp.generators) == 1
        and isinstance(expression, ast.BinOp)
        and isinstance(expression.op, ast.Sub)
        and (current := _id(expression.left)) is not None
        and isinstance(expression.right, ast.BinOp)
        and isinstance(expression.right.op, ast.Mult)
        and _id(expression.right.left) == factor
        and (pivot_value := _id(expression.right.right)) is not None
    ):
        return None
    pair = update_comp.generators[0]
    if (
        pair.ifs
        or pair.is_async
        or not isinstance(pair.target, ast.Tuple)
        or len(pair.target.elts) != 2
    ):
        return None
    if tuple(_id(item) for item in pair.target.elts) != (current, pivot_value):
        return None
    if (
        not isinstance(pair.iter, ast.Call)
        or _id(pair.iter.func) != "zip"
        or len(pair.iter.args) != 2
        or any(
            keyword.arg != "strict"
            or not isinstance(keyword.value, ast.Constant)
            or keyword.value.value is not True
            for keyword in pair.iter.keywords
        )
    ):
        return None
    if (
        _row(pair.iter.args[0], policy.matrix_name),
        _row(pair.iter.args[1], policy.matrix_name),
    ) != (row, pivot):
        return None

    # Require distinct local roles, keeping simple rebinding/shadowing cases
    # outside this exact single-body grammar.
    roles = (
        pivot,
        pivot_row,
        candidate,
        row,
        size,
        diagonal,
        factor,
        current,
        pivot_value,
        policy.matrix_name,
    )
    if len(set(roles)) != len(roles) or set(roles) & {"max", "range", "abs", "zip"}:
        return None
    return _Site(
        function.name, choose.lineno, swap.lineno, normalize.lineno, update.lineno
    )


def manual_elimination_sites(
    source: str, policy: ManualEliminationPolicy
) -> list[_Site]:
    """Return only complete, configured direct-list pivot/swap/eliminate shapes."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    if _module_shadows_elimination_builtins(tree):
        return []
    direct = configured_function_observations(
        source,
        policy.function_names,
        lambda function: _match(function, policy),
        lambda site: (site.function, site.pivot_line),
    )
    augmented = configured_function_observations(
        source,
        policy.function_names,
        lambda function: _match_augmented_inverse(function, policy),
        lambda site: (site.function, site.pivot_line),
    )
    return sorted(
        {*direct, *augmented}, key=lambda site: (site.function, site.pivot_line)
    )


def _match_augmented_inverse(
    function: ast.FunctionDef, policy: ManualEliminationPolicy
) -> _Site | None:
    """Recognize the configured augmented-list inverse and its exact result slice."""
    args = (*function.args.posonlyargs, *function.args.args)
    if (
        function.name not in policy.function_names
        or len(args) != 1
        or args[0].arg != policy.matrix_name
        or function.args.defaults
        or function.args.kwonlyargs
        or function.args.vararg
        or function.args.kwarg
    ):
        return None
    body = function.body[1:] if ast.get_docstring(function) else function.body
    if len(body) != 4:
        return None
    size_assign, augmented_assign, outer, returned = body
    if not isinstance(size_assign, ast.Assign) or len(size_assign.targets) != 1:
        return None
    size = _id(size_assign.targets[0])
    if (
        size is None
        or not isinstance(size_assign.value, ast.Call)
        or _id(size_assign.value.func) != "len"
        or len(size_assign.value.args) != 1
        or _id(size_assign.value.args[0]) != policy.matrix_name
    ):
        return None
    if (
        not isinstance(augmented_assign, ast.Assign)
        or len(augmented_assign.targets) != 1
    ):
        return None
    rows = _id(augmented_assign.targets[0])
    comp = augmented_assign.value
    if (
        rows is None
        or not isinstance(comp, ast.ListComp)
        or len(comp.generators) != 1
        or not isinstance(comp.elt, ast.BinOp)
        or not isinstance(comp.elt.op, ast.Add)
        or not isinstance(comp.elt.left, ast.Call)
        or _id(comp.elt.left.func) != "list"
        or len(comp.elt.left.args) != 1
        or not isinstance(comp.elt.right, ast.ListComp)
        or len(comp.elt.right.generators) != 1
    ):
        return None
    row_comp = comp.generators[0]
    row_index: str | None = None
    row_name: str | None = None
    if isinstance(row_comp.target, ast.Tuple) and len(row_comp.target.elts) == 2:
        row_index, row_name = map(_id, row_comp.target.elts)
    row_source = row_comp.iter
    identity = comp.elt.right
    identity_gen = identity.generators[0]
    col_index = _id(identity_gen.target)
    if (
        row_comp.ifs
        or row_comp.is_async
        or row_index is None
        or row_name is None
        or not isinstance(row_source, ast.Call)
        or _id(row_source.func) != "enumerate"
        or len(row_source.args) != 1
        or _id(row_source.args[0]) != policy.matrix_name
        or not isinstance(comp.elt.left.args[0], ast.Name)
        or comp.elt.left.args[0].id != row_name
        or identity_gen.ifs
        or identity_gen.is_async
        or col_index is None
        or not isinstance(identity_gen.iter, ast.Call)
        or _id(identity_gen.iter.func) != "range"
        or len(identity_gen.iter.args) != 1
        or _id(identity_gen.iter.args[0]) != size
        or not isinstance(identity.elt, ast.Call)
        or _id(identity.elt.func) != "float"
        or len(identity.elt.args) != 1
        or not isinstance(identity.elt.args[0], ast.Compare)
    ):
        return None
    equality = identity.elt.args[0]
    if not (
        _id(equality.left) == row_index
        and len(equality.ops) == 1
        and isinstance(equality.ops[0], ast.Eq)
        and len(equality.comparators) == 1
        and _id(equality.comparators[0]) == col_index
    ):
        return None
    if not isinstance(returned, ast.Return) or not isinstance(
        returned.value, ast.ListComp
    ):
        return None
    output = returned.value
    if (
        len(output.generators) != 1
        or not isinstance(output.elt, ast.Subscript)
        or _id(output.elt.value) != row_name
        or not isinstance(output.elt.slice, ast.Slice)
        or output.elt.slice.lower is None
        or _id(output.elt.slice.lower) != size
        or output.elt.slice.upper is not None
        or output.elt.slice.step is not None
        or _id(output.generators[0].target) != row_name
        or _id(output.generators[0].iter) != rows
        or output.generators[0].ifs
        or output.generators[0].is_async
        or not isinstance(outer, ast.For)
        or len(outer.body) != 6
    ):
        return None
    pivot = _id(outer.target)
    divisor_assign, zero_guard = outer.body[2:4]
    if (
        pivot is None
        or not isinstance(divisor_assign, ast.Assign)
        or len(divisor_assign.targets) != 1
        or (divisor := _id(divisor_assign.targets[0])) is None
        or _cell(divisor_assign.value, rows) != (pivot, pivot)
        or not isinstance(zero_guard, ast.If)
        or not isinstance(zero_guard.test, ast.Compare)
        or _id(zero_guard.test.left) != divisor
        or len(zero_guard.test.ops) != 1
        or not isinstance(zero_guard.test.ops[0], ast.Eq)
        or len(zero_guard.test.comparators) != 1
        or not isinstance(zero_guard.test.comparators[0], ast.Constant)
        or zero_guard.test.comparators[0].value != 0
        or zero_guard.orelse
        or len(zero_guard.body) != 1
        or not isinstance(zero_guard.body[0], ast.Raise)
    ):
        return None

    class _RenameRows(ast.NodeTransformer):
        def visit_Name(self, node: ast.Name) -> ast.Name:
            if node.id == rows:
                node.id = policy.matrix_name
            return node

    loop = _RenameRows().visit(copy.deepcopy(outer))
    del loop.body[3]
    normalized = ast.FunctionDef(
        name=function.name,
        args=ast.arguments(
            posonlyargs=[],
            args=[ast.arg(arg=policy.matrix_name), ast.arg(arg=size)],
            kwonlyargs=[],
            kw_defaults=[],
            defaults=[],
        ),
        body=[loop],
        decorator_list=[],
    )
    return _match(normalized, policy)


def _module_shadows_elimination_builtins(tree: ast.Module) -> bool:
    """Abstain when module-scope bindings can replace required builtin calls."""
    builtins = {"range", "max", "abs", "zip"}
    pending: list[ast.AST] = list(reversed(tree.body))
    while pending:
        node = pending.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name in builtins:
                return True
            continue
        if isinstance(node, ast.Import):
            bound = {alias.asname or alias.name.split(".")[0] for alias in node.names}
            if bound & builtins:
                return True
        elif isinstance(node, ast.ImportFrom):
            bound = {alias.asname or alias.name for alias in node.names}
            if bound & builtins:
                return True
        elif (
            isinstance(node, ast.Name)
            and isinstance(node.ctx, ast.Store)
            and node.id in builtins
        ):
            return True
        if isinstance(
            node,
            ast.Lambda | ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp,
        ):
            continue
        pending.extend(reversed(tuple(ast.iter_child_nodes(node))))
    return False


def check_manual_elimination(
    root: Path, paths: Iterable[Path], policy: ManualEliminationPolicy
) -> list[Finding]:
    """Report one complete configured elimination candidate per function."""
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
        for site in manual_elimination_sites(read_python_source(path), policy):
            findings.append(
                Finding(
                    rule_id=_RULE_ID,
                    path=name,
                    line=site.pivot_line,
                    message=(
                        f"Configured function {site.function!r} selects a pivot, swaps rows "
                        f"(line {site.swap_line}), normalizes a pivot row "
                        f"(line {site.normalize_line}), "
                        f"and eliminates other rows using that pivot (line {site.update_line}). "
                        "Review as a handwritten elimination candidate; this does not establish "
                        "that an inverse is needed or that a library call preserves the matrix "
                        "representation, pivoting, numerical stability, dtype, or failure behavior."
                    ),
                    severity=policy.severity,
                )
            )
    return findings
