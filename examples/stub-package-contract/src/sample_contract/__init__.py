"""Runtime implementation paired with an explicitly packaged PEP 561 stub."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TypeAlias

__all__ = ["NameNode", "flatten_names"]
NameNode: TypeAlias = str | list["NameNode"]


def flatten_names(values: Sequence[NameNode]) -> list[str]:
    """Flatten strings and nested lists; reject nested tuples and other values."""
    result: list[str] = []

    def append(value: object) -> None:
        if isinstance(value, str):
            result.append(value)
        elif isinstance(value, list):
            for child in value:
                append(child)
        else:
            raise TypeError(f"unsupported name node: {type(value).__name__}")

    for value in values:
        append(value)
    return result
