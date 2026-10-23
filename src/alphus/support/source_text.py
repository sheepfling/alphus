"""Read Python source with the same encoding rules as the interpreter."""

from __future__ import annotations

import tokenize
from pathlib import Path


def read_python_source(path: Path) -> str:
    """Honor a UTF-8 BOM and PEP 263 coding cookie before AST inspection."""
    with tokenize.open(path) as stream:
        return stream.read()


def read_utf8_text(path: Path, *, errors: str = "strict") -> str:
    """Read UTF-8 policy or document text with an explicit error policy."""
    return path.read_text(encoding="utf-8", errors=errors)


def read_utf8_sig_text(path: Path) -> str:
    """Read UTF-8 source while accepting a byte-order mark."""
    return path.read_text(encoding="utf-8-sig")
