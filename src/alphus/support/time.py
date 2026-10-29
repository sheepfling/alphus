"""Shared timestamp formatting for persisted quality history."""

from __future__ import annotations

from datetime import UTC, datetime


def utc_text(value: datetime) -> str:
    """Format an instant as UTC with stable microsecond precision."""
    return (
        value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    )
