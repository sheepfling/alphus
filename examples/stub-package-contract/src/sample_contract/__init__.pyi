from collections.abc import Sequence
from typing import TypeAlias

__all__ = ["NameNode", "flatten_names"]
NameNode: TypeAlias = str | list["NameNode"]

def flatten_names(values: Sequence[NameNode]) -> list[str]: ...
