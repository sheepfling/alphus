"""Small AST inventory of names bound in a module namespace."""

from __future__ import annotations

import ast
from collections import Counter
from collections.abc import Iterable


class _ModuleBindings(ast.NodeVisitor):
    def __init__(self, selected: frozenset[str]) -> None:
        self.selected = selected
        self.counts: Counter[str] = Counter()

    def _count(self, name: str | None) -> None:
        if name is not None and name in self.selected:
            self.counts[name] += 1

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._count(node.name)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._count(node.name)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._count(node.name)

    def visit_Name(self, node: ast.Name) -> None:
        match node.ctx:
            case ast.Store() | ast.Del():
                self._count(node.id)
            case _:
                return

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

    def visit_MatchAs(self, node: ast.MatchAs) -> None:
        # Capture names are stored as strings in pattern AST nodes, not as
        # ast.Name(Store) nodes, so count them explicitly.
        self._count(node.name)
        self.generic_visit(node)

    def visit_MatchStar(self, node: ast.MatchStar) -> None:
        self._count(node.name)
        self.generic_visit(node)

    def visit_MatchMapping(self, node: ast.MatchMapping) -> None:
        self._count(node.rest)
        self.generic_visit(node)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        # Defaults execute in the module scope; the lambda body does not.
        for default in (*node.args.defaults, *node.args.kw_defaults):
            if default is not None:
                self.visit(default)

    def _visit_comprehension(
        self, generators: Iterable[ast.comprehension], values: Iterable[ast.expr]
    ) -> None:
        # Iteration targets are local to the implicit comprehension scope.
        # Visit evaluated expressions so assignment-expression targets, which
        # bind in the containing scope, are still counted.
        for generator in generators:
            self.visit(generator.iter)
            for condition in generator.ifs:
                self.visit(condition)
        for value in values:
            self.visit(value)

    def visit_ListComp(self, node: ast.ListComp) -> None:
        self._visit_comprehension(node.generators, (node.elt,))

    def visit_SetComp(self, node: ast.SetComp) -> None:
        self._visit_comprehension(node.generators, (node.elt,))

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        self._visit_comprehension(node.generators, (node.elt,))

    def visit_DictComp(self, node: ast.DictComp) -> None:
        self._visit_comprehension(node.generators, (node.key, node.value))


def module_binding_counts(tree: ast.Module, names: Iterable[str]) -> dict[str, int]:
    """Count visible module bindings, including control-flow definitions.

    Function and class bodies introduce their own namespaces and are not
    traversed. A star import makes every selected name ambiguous.
    """
    visitor = _ModuleBindings(frozenset(names))
    visitor.visit(tree)
    return dict(visitor.counts)
