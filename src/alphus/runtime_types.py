"""Report runtime type checks without an explicit union to narrow."""

from __future__ import annotations

import ast
from collections.abc import Iterable
from pathlib import Path

from alphus.config import RuntimeTypePolicy
from alphus.inventory import matches_path
from alphus.python_style import type_name


def _union_members(node: ast.expr) -> frozenset[str]:
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        left = _union_members(node.left)
        right = _union_members(node.right)
        return left | right if left and right else frozenset()
    if isinstance(node, ast.Subscript) and type_name(node.value) == "Union":
        parts = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
        names = [type_name(part) for part in parts]
        return (
            frozenset(name for name in names if name is not None)
            if len(names) > 1 and all(names)
            else frozenset()
        )
    name = type_name(node)
    if isinstance(node, ast.Constant) and node.value is None:
        name = "None"
    return frozenset({name}) if name is not None else frozenset()


def _checked_types(node: ast.expr) -> frozenset[str]:
    parts = node.elts if isinstance(node, ast.Tuple) else [node]
    names = [type_name(part) for part in parts]
    return (
        frozenset(name for name in names if name is not None)
        if all(names)
        else frozenset()
    )


class TypeCheckVisitor(ast.NodeVisitor):
    """Track visible union annotations and report unproven runtime checks."""

    def __init__(self) -> None:
        self.scopes: list[dict[str, frozenset[str]]] = [{}]
        self.findings: list[tuple[int, str]] = []

    def _members(self, subject: ast.expr) -> frozenset[str]:
        if not isinstance(subject, ast.Name):
            return frozenset()
        for scope in reversed(self.scopes):
            if subject.id in scope:
                return scope[subject.id]
        return frozenset()

    def _check(self, subject: ast.expr, checked: ast.expr, line: int) -> None:
        declared = self._members(subject)
        classes = _checked_types(checked)
        if len(declared) < 2 or not classes or not classes <= declared:
            self.findings.append(
                (line, "runtime type check requires an explicit union annotation")
            )

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if isinstance(node.target, ast.Name):
            self.scopes[-1][node.target.id] = _union_members(node.annotation)
        self.generic_visit(node)

    def _function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        arguments = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
        if node.args.vararg is not None:
            arguments.append(node.args.vararg)
        if node.args.kwarg is not None:
            arguments.append(node.args.kwarg)
        scope = {
            arg.arg: _union_members(arg.annotation)
            for arg in arguments
            if arg.annotation is not None
        }
        self.scopes.append(scope)
        for statement in node.body:
            self.visit(statement)
        self.scopes.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._function(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.scopes.append({})
        for statement in node.body:
            self.visit(statement)
        self.scopes.pop()

    def visit_Call(self, node: ast.Call) -> None:
        if (
            isinstance(node.func, ast.Name)
            and node.func.id == "isinstance"
            and len(node.args) == 2
        ):
            self._check(node.args[0], node.args[1], node.lineno)
        self.generic_visit(node)

    def visit_Compare(self, node: ast.Compare) -> None:
        if (
            len(node.ops) == 1
            and isinstance(node.ops[0], (ast.Is, ast.IsNot, ast.Eq, ast.NotEq))
            and isinstance(node.left, ast.Call)
            and isinstance(node.left.func, ast.Name)
            and node.left.func.id == "type"
            and len(node.left.args) == 1
        ):
            self._check(node.left.args[0], node.comparators[0], node.lineno)
        self.generic_visit(node)


def type_check_findings(source: str) -> list[tuple[int, str]]:
    """Find runtime checks that cannot narrow a declared explicit union."""
    visitor = TypeCheckVisitor()
    visitor.visit(ast.parse(source))
    return sorted(set(visitor.findings))


def policy_issues(
    root: Path, paths: Iterable[Path], policy: RuntimeTypePolicy
) -> list[str]:
    """Scan selected runtime Python sources for unproven type narrowing."""
    issues: list[str] = []
    checkout = root.resolve(strict=True)
    for relative in sorted(paths):
        if relative.suffix.lower() not in policy.extensions or any(
            matches_path(relative.as_posix(), pattern) for pattern in policy.exclude
        ):
            continue
        path = checkout / relative
        if not path.is_file():
            continue
        for line, reason in type_check_findings(path.read_text(encoding="utf-8-sig")):
            issues.append(f"{relative}:{line}: {reason}")
    return issues
