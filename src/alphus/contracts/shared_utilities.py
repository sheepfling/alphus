"""Typed result contract for the shared-utilities feature."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SharedUtilitiesReport:
    """Structured results from the related shared-utility checks."""

    duplicate_groups: tuple[tuple[str, ...], ...]
    file_hash_implementations: tuple[str, ...]
    direct_git_calls: tuple[str, ...]

    @property
    def failed(self) -> bool:
        """Return whether duplicate helpers or multiple file hashers were found."""
        return (
            bool(self.duplicate_groups)
            or len(self.file_hash_implementations) > 1
            or bool(self.direct_git_calls)
        )
