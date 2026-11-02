"""Bounded AST helpers shared by configured quaternion kernel advisories."""

from __future__ import annotations

import ast
from collections.abc import Callable, Iterable, Sequence
from typing import TypeVar

_Observation = TypeVar("_Observation")


def qualified_call_name(node: ast.expr) -> str | None:
    """Return a direct dotted name for a call target without resolving aliases."""
    match node:
        case ast.Name(id=name):
            return name
        case ast.Attribute(value=value, attr=attribute):
            parent = qualified_call_name(value)
            return f"{parent}.{attribute}" if parent else None
        case _:
            return None


def is_sum_of_four_squares(
    node: ast.expr, components: tuple[str, str, str, str]
) -> bool:
    """Match an addition tree containing each configured component squared once."""
    pending = [node]
    squares: list[str] = []
    while pending:
        current = pending.pop()
        match current:
            case ast.BinOp(left=left, op=ast.Add(), right=right):
                pending.extend((right, left))
            case ast.BinOp(
                left=ast.Name(id=left), op=ast.Mult(), right=ast.Name(id=right)
            ) if left == right:
                squares.append(left)
                if len(squares) > 4:
                    return False
            case _:
                return False
    return sorted(squares) == sorted(components)


def _functions(statements: Iterable[ast.stmt]) -> Iterable[ast.FunctionDef]:
    pending = list(reversed(tuple(statements)))
    while pending:
        statement = pending.pop()
        match statement:
            case ast.FunctionDef():
                yield statement
            case ast.ClassDef(body=body):
                pending.extend(reversed(body))
            case _:
                continue


def configured_function_observations(
    source: str,
    function_names: Sequence[str],
    observe: Callable[[ast.FunctionDef], _Observation | None],
    sort_key: Callable[[_Observation], tuple[str, int]],
) -> list[_Observation]:
    """Bound source parsing and match only configured top-level/class functions."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    if sum(1 for _ in ast.walk(tree)) > 10_000:
        return []
    selected = set(function_names)
    observations: set[_Observation] = set()
    for function in _functions(tree.body):
        if function.name not in selected:
            continue
        observation = observe(function)
        if observation is not None:
            observations.add(observation)
    return sorted(observations, key=sort_key)


def redefined_function_names(
    source: str, selected_names: Sequence[str]
) -> tuple[str, ...]:
    """Return configured names rebound by later definitions in one scope."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ()

    def shadowed_in(statements: Sequence[ast.stmt]) -> tuple[str, ...]:
        counts: dict[str, int] = {}
        shadowed: list[str] = []
        for statement in statements:
            match statement:
                case ast.FunctionDef(name=name) if name in selected_names:
                    counts[name] = counts.get(name, 0) + 1
                    if counts[name] > 1 and name not in shadowed:
                        shadowed.append(name)
                case ast.ClassDef(body=body):
                    shadowed.extend(shadowed_in(body))
                case _:
                    continue
        return tuple(shadowed)

    return shadowed_in(tree.body)
