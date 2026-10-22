"""Small platform probes shared by portable rule implementations."""

from __future__ import annotations

import sys


def is_windows() -> bool:
    """Return whether the current Python process is running on Windows."""
    return sys.platform == "win32"


def is_linux() -> bool:
    """Return whether the current Python process is running on Linux."""
    return sys.platform == "linux"


def is_macos() -> bool:
    """Return whether the current Python process is running on macOS."""
    return sys.platform == "darwin"
