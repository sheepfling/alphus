"""AST patterns specific to quaternion arithmetic."""

from __future__ import annotations

import ast


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
