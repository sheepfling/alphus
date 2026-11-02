"""Find one explicit nested-comprehension matrix-product fingerprint."""

from __future__ import annotations

import ast
from collections.abc import Iterable
from pathlib import Path

from alphus.config import ManualMatrixKernelPolicy
from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import Category, Framework, Scope, rule_tag
from alphus.support.inventory import matches_path
from alphus.support.source_text import read_python_source

_RULE_ID = rule_tag(
    Scope.PYTHON, Framework.NONE, Category.MAINTAINABILITY, "manual-matrix-kernel"
)


def _call_name(node: ast.expr, name: str) -> ast.Call | None:
    match node:
        case ast.Call(func=ast.Name(id=call_name), args=[_], keywords=[]):
            return node if call_name == name else None
        case _:
            return None


def _indexed_pair(node: ast.expr, first: str, second: str) -> bool:
    """Match ``container[first][second]`` with a simple named container."""
    match node:
        case ast.Subscript(
            slice=ast.Name(id=second_index),
            value=ast.Subscript(slice=ast.Name(id=first_index), value=ast.Name()),
        ):
            return second_index == second and first_index == first
        case _:
            return False


def _target_name(node: ast.expr) -> str | None:
    match node:
        case ast.Name(id=name):
            return name
        case _:
            return None


def _list_comp(node: ast.AST) -> ast.ListComp | None:
    match node:
        case ast.ListComp():
            return node
        case _:
            return None


def _generator_exp(node: ast.expr) -> ast.GeneratorExp | None:
    match node:
        case ast.GeneratorExp():
            return node
        case _:
            return None


def _binop(node: ast.expr) -> ast.BinOp | None:
    match node:
        case ast.BinOp():
            return node
        case _:
            return None


def _is_mult(operator: ast.operator) -> bool:
    match operator:
        case ast.Mult():
            return True
        case _:
            return False


def _has_builtin_shadow(tree: ast.AST) -> bool:
    """Avoid interpreting locally rebound sum/range calls as builtins."""
    for node in ast.walk(tree):
        match node:
            case ast.Name(id=name, ctx=ast.Store()) if name in {"sum", "range"}:
                return True
            case ast.arg(arg=name) if name in {"sum", "range"}:
                return True
            case (
                ast.FunctionDef(name=name)
                | ast.AsyncFunctionDef(name=name)
                | ast.ClassDef(name=name)
            ) if name in {"sum", "range"}:
                return True
            case ast.alias(name=name, asname=asname) if name in {
                "sum",
                "range",
            } or asname in {"sum", "range"}:
                return True
            case _:
                continue
    return False


def _is_matrix_product(node: ast.ListComp) -> bool:
    if len(node.generators) != 1 or node.generators[0].ifs:
        return False
    outer = node.generators[0]
    row = _target_name(outer.target)
    if row is None or _call_name(outer.iter, "range") is None:
        return False
    inner = _list_comp(node.elt)
    if inner is None or len(inner.generators) != 1:
        return False
    column_generator = inner.generators[0]
    column = _target_name(column_generator.target)
    if column is None or column == row or column_generator.ifs:
        return False
    if _call_name(column_generator.iter, "range") is None:
        return False
    summation = _call_name(inner.elt, "sum")
    products = _generator_exp(summation.args[0]) if summation is not None else None
    if products is None:
        return False
    if len(products.generators) != 1 or products.generators[0].ifs:
        return False
    inner_generator = products.generators[0]
    inner_index = _target_name(inner_generator.target)
    product = _binop(products.elt)
    if (
        inner_index is None
        or inner_index in {row, column}
        or _call_name(inner_generator.iter, "range") is None
        or product is None
        or not _is_mult(product.op)
    ):
        return False
    return _indexed_pair(product.left, row, inner_index) and _indexed_pair(
        product.right, inner_index, column
    )


def matrix_kernel_lines(source: str) -> list[tuple[int, int, int]]:
    """Return outer, inner-sum, and product-expression lines for exact matches."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    if _has_builtin_shadow(tree):
        return []
    findings: list[tuple[int, int, int]] = []
    for node in ast.walk(tree):
        if (
            (outer := _list_comp(node)) is None
            or not _is_matrix_product(outer)
            or (inner := _list_comp(outer.elt)) is None
        ):
            continue
        summation = _call_name(inner.elt, "sum")
        if summation is None or not summation.args:
            continue
        product = _generator_exp(summation.args[0])
        if product is None:
            continue
        findings.append((outer.lineno, inner.lineno, product.elt.lineno))
    return findings


def check_manual_matrix_kernels(
    root: Path, paths: Iterable[Path], policy: ManualMatrixKernelPolicy
) -> list[Finding]:
    """Return advisory findings only within explicitly declared numeric paths."""
    checkout = root.resolve(strict=True)
    findings: list[Finding] = []
    for relative in sorted(paths):
        name = relative.as_posix()
        if (
            relative.suffix != ".py"
            or not any(matches_path(name, pattern) for pattern in policy.source_paths)
            or any(matches_path(name, pattern) for pattern in policy.exclude)
        ):
            continue
        path = checkout / relative
        if not path.is_file():
            continue
        for outer_line, inner_line, product_line in matrix_kernel_lines(
            read_python_source(path)
        ):
            findings.append(
                Finding(
                    rule_id=_RULE_ID,
                    path=name,
                    line=outer_line,
                    message=(
                        "Recognized nested list comprehensions with indexed product "
                        f"accumulation (inner comprehension at line {inner_line}, "
                        f"product at line "
                        f"{product_line}). If this implements matrix multiplication, "
                        "review whether an established kernel fits while preserving "
                        "element types, shapes, summation order, and failure behavior; "
                        "this syntax alone does not establish a defect or speedup."
                    ),
                    severity=policy.severity,
                )
            )
    return findings
