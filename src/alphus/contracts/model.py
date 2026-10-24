"""Shared immutable validation model for policy and wire contracts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from pydantic import BaseModel, ConfigDict, model_validator


def _freeze_config(value: object) -> object:
    """Freeze nested JSON-style containers before model validation."""
    match value:
        case list():
            items = cast(list[object], value)
            return tuple(_freeze_config(item) for item in items)
        case tuple():
            items = cast(tuple[object, ...], value)
            return tuple(_freeze_config(item) for item in items)
        case Mapping():
            items = cast(Mapping[object, object], value)
            return {key: _freeze_config(item) for key, item in items.items()}
        case _:
            return value


class StrictModel(BaseModel):
    """Forbid unknown fields and freeze validated collections."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    @model_validator(mode="before")
    @classmethod
    def freeze_collections(cls, value: object) -> object:
        return _freeze_config(value)
