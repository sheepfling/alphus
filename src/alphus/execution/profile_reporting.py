"""Per-run human and machine output channels for quality profiles."""

from __future__ import annotations

import logging
from typing import TextIO


class ProfileReporter:
    """Send status through isolated loggers while preserving captured tool output."""

    def __init__(self, output: TextIO, errors: TextIO) -> None:
        self.output = output
        self.errors = errors
        self._info = logging.Logger("alphus.profile.output", logging.INFO)  # noqa: LOG001
        self._error = logging.Logger("alphus.profile.error", logging.ERROR)  # noqa: LOG001
        # Unregistered per-run loggers cannot retain another invocation's streams.
        self._info.addHandler(logging.StreamHandler(output))
        self._error.addHandler(logging.StreamHandler(errors))

    def info(self, message: str) -> None:
        self._info.info("%s", message)

    def error(self, message: str) -> None:
        self._error.error("%s", message)

    def captured_error(self, value: str) -> None:
        """Replay child stderr byte-for-byte, without a second log prefix."""
        if value:
            self.errors.write(value)
            self.errors.flush()
