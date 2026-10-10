"""Stable finding records shared by portable quality rules."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Finding:
    """One actionable result from a quality rule."""

    rule_id: str
    path: str
    message: str
    line: int | None = None
    severity: str = "error"
