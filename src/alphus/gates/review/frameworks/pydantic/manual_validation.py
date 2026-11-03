"""Pydantic model-initializer patterns that can bypass normal validation."""

from __future__ import annotations

import ast
from collections.abc import Set as AbstractSet


def manual_model_validation_lines(
    module: ast.Module, model_names: AbstractSet[str]
) -> list[int]:
    """Return custom initializer lines on locally recognized Pydantic models.

    This is intentionally a review prompt rather than a claim that a custom
    initializer is invalid. Pydantic supports deliberate customization, but
    field/model validators and ``model_post_init`` usually express these
    behaviors while retaining the normal validation lifecycle.
    """
    return sorted(
        statement.lineno
        for node in module.body
        if isinstance(node, ast.ClassDef) and node.name in model_names
        for statement in node.body
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
        and statement.name == "__init__"
    )
