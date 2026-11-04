"""Validated consumer-owned source-to-test coverage contracts."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Self

from pydantic import field_validator, model_validator

from alphus.policy.base import (
    StrictModel,
    require_unique,
    validate_single_path,
    validate_suppression_reason,
)


def _repository_file_path(value: str, description: str) -> str:
    checked = validate_single_path(value, description)
    if any(ord(character) < 32 or ord(character) == 127 for character in checked):
        raise ValueError(f"{description} cannot contain control characters")
    if checked == ".":
        raise ValueError(f"{description} must name a file, not the repository root")
    return checked


class SourceTestRelationship(StrictModel):
    """One explicit source obligation and the test files declared for it."""

    source: str
    tests: tuple[str, ...] = ()
    generated: bool = False
    exclusion_reason: str | None = None

    @field_validator("source")
    @classmethod
    def validate_source(cls, value: str) -> str:
        return _repository_file_path(value, "source paths")

    @field_validator("tests")
    @classmethod
    def validate_tests(cls, values: Sequence[str]) -> tuple[str, ...]:
        checked = tuple(_repository_file_path(value, "test paths") for value in values)
        require_unique(checked, "declared test paths must be unique per source")
        return checked

    @field_validator("exclusion_reason")
    @classmethod
    def validate_exclusion_reason(cls, value: str | None) -> str | None:
        return validate_suppression_reason(value) if value is not None else None

    @model_validator(mode="after")
    def validate_exclusion(self) -> Self:
        if self.generated and self.exclusion_reason is not None:
            raise ValueError("generated sources do not also need an exclusion reason")
        if (self.generated or self.exclusion_reason is not None) and self.tests:
            raise ValueError("excluded sources cannot declare test relationships")
        return self


class SourceTestCoveragePolicy(StrictModel):
    """Opt-in source-to-test relationships and an optional execution artifact."""

    relationships: tuple[SourceTestRelationship, ...] = ()
    evidence_file: str | None = None

    @field_validator("evidence_file")
    @classmethod
    def validate_evidence_file(cls, value: str | None) -> str | None:
        return (
            _repository_file_path(value, "evidence_file") if value is not None else None
        )

    @model_validator(mode="after")
    def validate_relationships(self) -> Self:
        require_unique(
            tuple(item.source for item in self.relationships),
            "source-to-test relationships must have unique sources",
        )
        return self
