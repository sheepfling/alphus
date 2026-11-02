"""Small AST inventory of names bound in a module namespace."""

from __future__ import annotations

import ast
from collections import Counter
from collections.abc import Iterable


class _ModuleBindings(ast.NodeVisitor):
    def __init__(self, selected: frozenset[str]) -> None:
        self.selected = selected
        self.counts: Counter[str] = Counter()

    def _count(self, name: str) -> None:
        if name in self.selected:
            self.counts[name] += 1

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._count(node.name)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._count(node.name)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._count(node.name)

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self._count(node.id)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self._count(alias.asname or alias.name.split(".", maxsplit=1)[0])

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            if alias.name == "*":
                # The imported names are unknown, so make each selected name
                # ambiguous even if no explicit binding is visible here.
                for name in self.selected:
                    self.counts[name] += 2
            else:
                self._count(alias.asname or alias.name)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        # Defaults execute in the module scope; the lambda body does not.
        for default in (*node.args.defaults, *node.args.kw_defaults):
            if default is not None:
                self.visit(default)


def module_binding_counts(tree: ast.Module, names: Iterable[str]) -> dict[str, int]:
    """Count visible module bindings, including control-flow definitions.

    Function and class bodies introduce their own namespaces and are not
    traversed. A star import makes every selected name ambiguous.
    """
    visitor = _ModuleBindings(frozenset(names))
    visitor.visit(tree)
    return dict(visitor.counts)
