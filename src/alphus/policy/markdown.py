"""Policies for opt-in Markdown checks."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated

from pydantic import Field, field_validator

from alphus.policy.base import (
    StrictModel,
    SuppressionReason,
    require_unique,
    validate_patterns,
    validate_single_path,
)


class MarkdownShellFenceSuppression(StrictModel):
    """Suppress one deliberate shell-label mismatch at a fence opener."""

    path: str
    line: Annotated[int, Field(ge=1)]
    reason: SuppressionReason

    @field_validator("path")
    @classmethod
    def validate_path(cls, path: str) -> str:
        return validate_single_path(path, "Markdown shell suppression path")


class MarkdownShellFencesPolicy(StrictModel):
    """Select Markdown files and documented exceptions for shell fence review."""

    include: Annotated[tuple[str, ...], Field(min_length=1)] = ("**/*.md",)
    exclude: Annotated[tuple[str, ...], Field(default_factory=tuple)]
    suppressions: Annotated[
        tuple[MarkdownShellFenceSuppression, ...], Field(default_factory=tuple)
    ]

    @field_validator("include", "exclude")
    @classmethod
    def validate_patterns(cls, patterns: Sequence[str]) -> tuple[str, ...]:
        return validate_patterns(patterns)

    @field_validator("suppressions")
    @classmethod
    def validate_suppressions(
        cls, suppressions: Sequence[MarkdownShellFenceSuppression]
    ) -> tuple[MarkdownShellFenceSuppression, ...]:
        entries = tuple(suppressions)
        require_unique(
            tuple((item.path, item.line) for item in entries),
            "Markdown shell suppressions must not repeat a path and line",
        )
        return entries
