"""Shared helpers for contained files and validated structured values."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import cast

from pydantic import JsonValue, TypeAdapter

_JSON_VALUE_ADAPTER: TypeAdapter[JsonValue] = TypeAdapter(JsonValue)


def contained_file(root: Path, relative: str) -> Path | None:
    """Return an existing regular file contained by the explicit repository root."""
    checkout = root.resolve(strict=True)
    path = checkout / relative
    try:
        path.resolve(strict=True).relative_to(checkout)
    except (OSError, ValueError):
        return None
    return path if path.is_file() else None


def nested_value(value: object, key: str) -> object:
    """Read a dotted key from a validated or decoded mapping without coercion."""
    current = value
    for segment in key.split("."):
        match current:
            case Mapping():
                current = cast(Mapping[str, object], current).get(segment)
            case _:
                return None
    return current


def validate_json_value(source: str) -> JsonValue:
    """Decode untrusted JSON through Pydantic's recursive JSON contract."""
    return _JSON_VALUE_ADAPTER.validate_json(source)
