"""Validated Python source-to-test directory layout contracts."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated, Self

from pydantic import Field, field_validator, model_validator

from alphus.policy.base import (
    StrictModel,
    require_unique,
    validate_single_path,
)


def _layout_root(value: str, description: str) -> str:
    checked = validate_single_path(value, description)
    if checked == ".":
        raise ValueError(
            f"{description} must name a directory below the repository root"
        )
    return checked


class TestLayoutPair(StrictModel):
    """Pair one import-package root with its mirrored test directory."""

    source_root: str
    test_root: str
    integration_roots: tuple[str, ...] = ("integration",)

    @field_validator("source_root")
    @classmethod
    def validate_source_root(cls, value: str) -> str:
        return _layout_root(value, "source_root")

    @field_validator("test_root")
    @classmethod
    def validate_test_root(cls, value: str) -> str:
        return _layout_root(value, "test_root")

    @field_validator("integration_roots")
    @classmethod
    def validate_integration_roots(cls, values: Sequence[str]) -> tuple[str, ...]:
        checked = tuple(_layout_root(value, "integration root") for value in values)
        require_unique(checked, "integration roots must be unique")
        return checked

    @model_validator(mode="after")
    def validate_roots_are_distinct(self) -> Self:
        if self.source_root == self.test_root:
            raise ValueError("source_root and test_root must be different directories")
        return self


class TestLayoutPolicy(StrictModel):
    """Consumer-owned source/test root pairs selected by the layout rule."""

    pairs: Annotated[tuple[TestLayoutPair, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_pairs_are_unique(self) -> Self:
        require_unique(
            tuple((pair.source_root, pair.test_root) for pair in self.pairs),
            "source/test root pairs must be unique",
        )
        require_unique(
            tuple(pair.test_root for pair in self.pairs),
            "each test root must have one source root",
        )
        return self
