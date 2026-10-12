"""Stable finding records shared by portable quality rules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple


class SourceFinding(NamedTuple):
    """One source-level location and explanation before repository context is added."""

    line: int
    message: str


@dataclass(frozen=True, slots=True)
class Finding:
    """One actionable result from a quality rule."""

    rule_id: str
    path: str
    message: str
    line: int | None = None
    severity: str = "error"
