from collections.abc import Sequence
from typing import TypeAlias, overload

__all__ = ["NameNode", "flatten_names", "format_value"]
NameNode: TypeAlias = str | list["NameNode"]

def flatten_names(values: Sequence[NameNode]) -> list[str]: ...

@overload
def format_value(value: int) -> str: ...
@overload
def format_value(value: str) -> int: ...
