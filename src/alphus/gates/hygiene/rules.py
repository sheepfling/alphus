"""Repository-independent source gates."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from alphus.policy.sources import PathLimit
from alphus.support.inventory import matches_path


@dataclass(frozen=True, order=True, slots=True)
class OverrideSpecificity:
    """Comparable precedence for one matching path-limit pattern."""

    exact_path_rank: int
    literal_segments_rank: int
    literal_characters_rank: int
    wildcard_characters: int
    pattern: str


def _override_specificity(pattern: str) -> OverrideSpecificity:
    """Return a named, sortable key matching the documented precedence order."""
    segments = pattern.split("/")
    literal_segments = sum(
        not any(character in segment for character in "*?[") for segment in segments
    )
    literal_characters = sum(character not in "*?[]" for character in pattern)
    wildcard_characters = sum(character in "*?[]" for character in pattern)
    return OverrideSpecificity(
        int(wildcard_characters != 0),
        -literal_segments,
        -literal_characters,
        wildcard_characters,
        pattern,
    )


def path_override(path: str, overrides: Sequence[PathLimit]) -> int | None:
    """Select a matching path override by documented specificity, independent of table order."""
    matching = [
        override for override in overrides if matches_path(path, override.pattern)
    ]
    if not matching:
        return None
    return min(
        matching, key=lambda override: _override_specificity(override.pattern)
    ).limit
