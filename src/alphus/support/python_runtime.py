"""Resolve the Python interpreter used by Alphus-owned child processes."""

from __future__ import annotations

import sys


def current_python_executable() -> str:
    """Return the interpreter running this Alphus process."""
    return sys.executable
