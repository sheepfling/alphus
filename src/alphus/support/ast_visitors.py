"""Shared AST visitor operations for common scope-bound nodes."""

from __future__ import annotations

import ast


def visit_class_definition_header(
    visitor: ast.NodeVisitor, node: ast.ClassDef
) -> set[str]:
    """Return class bindings and visit expressions evaluated in its header."""
    for expression in (*node.decorator_list, *node.bases):
        visitor.visit(expression)
    for keyword in node.keywords:
        visitor.visit(keyword.value)
    return {node.name}


def visit_exception_handler_bindings(
    visitor: ast.NodeVisitor, node: ast.ExceptHandler
) -> set[str]:
    """Return exception aliases and visit the handler's evaluated contents."""
    if node.type is not None:
        visitor.visit(node.type)
    for statement in node.body:
        visitor.visit(statement)
    return {node.name} if node.name is not None else set()
