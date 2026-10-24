"""Stable process exit semantics shared by Alphus orchestration."""

from __future__ import annotations

from enum import IntEnum


class ExitCode(IntEnum):
    """Public CLI result codes; command child codes may also be arbitrary ints."""

    SUCCESS = 0
    QUALITY_FAILURE = 1
    CONFIG_ERROR = 2
    LAUNCH_ERROR = 127
