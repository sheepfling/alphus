"""Read Python source with the same encoding rules as the interpreter."""

from __future__ import annotations

import tokenize
from pathlib import Path


def read_python_source(path: Path) -> str:
    """Honor a UTF-8 BOM and PEP 263 coding cookie before AST inspection."""
    with tokenize.open(path) as stream:
        return stream.read()
