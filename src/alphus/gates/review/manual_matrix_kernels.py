"""Find one explicit nested-comprehension matrix-product fingerprint."""

from __future__ import annotations

import ast
from collections.abc import Iterable
from pathlib import Path

from alphus.config import ManualMatrixKernelPolicy
from alphus.contracts.findings import Finding
from alphus.support.inventory import matches_path
from alphus.support.source_text import read_python_source

_RULE_ID = "alphus/python/none/maintainability/manual-matrix-kernel"


def _call_name(node: ast.expr, name: str) -> ast.Call | None:
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == name
        and len(node.args) == 1
        and not node.keywords
    ):
        return node
    return None


def _indexed_pair(node: ast.expr, first: str, second: str) -> bool:
    """Match ``container[first][second]`` with a simple named container."""
    return (
        isinstance(node, ast.Subscript)
        and isinstance(node.slice, ast.Name)
        and node.slice.id == second
        and isinstance(node.value, ast.Subscript)
        and isinstance(node.value.slice, ast.Name)
        and node.value.slice.id == first
        and isinstance(node.value.value, ast.Name)
    )


def _target_name(node: ast.expr) -> str | None:
    return node.id if isinstance(node, ast.Name) else None


def _has_builtin_shadow(tree: ast.AST) -> bool:
    """Avoid interpreting locally rebound sum/range calls as builtins."""
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Name)
            and isinstance(node.ctx, ast.Store)
            and node.id in {"sum", "range"}
        ):
            return True
        if isinstance(node, ast.arg) and node.arg in {"sum", "range"}:
            return True
        if isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ) and node.name in {"sum", "range"}:
            return True
        if isinstance(node, ast.alias) and (
            node.name in {"sum", "range"} or node.asname in {"sum", "range"}
        ):
            return True
    return False


def _is_matrix_product(node: ast.ListComp) -> bool:
    if len(node.generators) != 1 or node.generators[0].ifs:
        return False
    outer = node.generators[0]
    row = _target_name(outer.target)
    if row is None or _call_name(outer.iter, "range") is None:
        return False
    if not isinstance(node.elt, ast.ListComp) or len(node.elt.generators) != 1:
        return False
    inner = node.elt
    column_generator = inner.generators[0]
    column = _target_name(column_generator.target)
    if column is None or column == row or column_generator.ifs:
        return False
    if _call_name(column_generator.iter, "range") is None:
        return False
    summation = _call_name(inner.elt, "sum")
    if summation is None or not isinstance(summation.args[0], ast.GeneratorExp):
        return False
    products = summation.args[0]
    if len(products.generators) != 1 or products.generators[0].ifs:
        return False
    inner_generator = products.generators[0]
    inner_index = _target_name(inner_generator.target)
    if (
        inner_index is None
        or inner_index in {row, column}
        or _call_name(inner_generator.iter, "range") is None
        or not isinstance(products.elt, ast.BinOp)
        or not isinstance(products.elt.op, ast.Mult)
    ):
        return False
    return _indexed_pair(products.elt.left, row, inner_index) and _indexed_pair(
        products.elt.right, inner_index, column
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
            not isinstance(node, ast.ListComp)
            or not _is_matrix_product(node)
            or not isinstance(node.elt, ast.ListComp)
        ):
            continue
        summation = node.elt.elt
        if (
            not isinstance(summation, ast.Call)
            or not summation.args
            or not isinstance(summation.args[0], ast.GeneratorExp)
        ):
            continue
        findings.append((node.lineno, node.elt.lineno, summation.args[0].elt.lineno))
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
