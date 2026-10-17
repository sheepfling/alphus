"""Small platform probes shared by portable rule implementations."""

from __future__ import annotations

import os


def is_windows() -> bool:
    """Return whether the current Python process is running on Windows."""
    return os.name == "nt"
