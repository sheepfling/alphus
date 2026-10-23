"""Shared helpers for contained files and validated structured values."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from types import NoneType
from typing import Any, TypeAlias, cast

from pydantic import JsonValue as PydanticJsonValue
from pydantic import TypeAdapter

# Pydantic accepts its recursive JsonValue union at runtime, but Pyright sees
# that alias as a UnionType rather than as a TypeForm. Keep the adapter's result
# concrete and cast only the schema argument accepted by Pydantic.
JsonValue: TypeAlias = (
    NoneType
    | bool
    | int
    | float
    | str
    | Sequence["JsonValue"]
    | Mapping[str, "JsonValue"]
)

_JSON_VALUE_ADAPTER: TypeAdapter[PydanticJsonValue] = TypeAdapter[PydanticJsonValue](
    cast(Any, PydanticJsonValue)
)


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


def validate_json_value(source: str | bytes) -> JsonValue:
    """Decode JSON and expose its recursive structure through read-only types."""
    return cast(JsonValue, _JSON_VALUE_ADAPTER.validate_json(source))


def nested_json_value(payload: JsonValue, dotted: str) -> JsonValue:
    """Read a dotted key from a validated JSON value or raise KeyError."""
    current = payload
    for segment in dotted.split("."):
        match current:
            case Mapping():
                mapping = cast(Mapping[str, JsonValue], current)
                if segment not in mapping:
                    raise KeyError(dotted)
                current = mapping[segment]
            case _:
                raise KeyError(dotted)
    return current


def optional_json_integer(value: JsonValue) -> int | None:
    """Return an integer JSON value, excluding booleans, or None otherwise."""
    return value if type(value) is int else None


def _json_type_name(value: JsonValue) -> str:
    match value:
        case None:
            return "null"
        case bool():
            return "boolean"
        case int():
            return "integer"
        case float():
            return "number"
        case str():
            return "string"
        case Sequence():
            return "array"
        case Mapping():
            return "object"


def json_values_same_type(left: JsonValue, right: JsonValue) -> bool:
    """Return whether two JSON values have the same JSON value category."""
    return _json_type_name(left) == _json_type_name(right)


def require_json_object(value: JsonValue, context: str) -> Mapping[str, JsonValue]:
    """Require a parsed JSON object and preserve its recursively typed values."""
    if not isinstance(value, Mapping):
        raise TypeError(context)
    return value


def require_json_array(value: JsonValue, context: str) -> Sequence[JsonValue]:
    """Require a parsed JSON array while exposing a covariant read-only view."""
    if not isinstance(value, Sequence) or isinstance(value, str):
        raise TypeError(context)
    return value


def require_json_string(value: JsonValue, context: str) -> str:
    """Require a JSON string with a caller-specific error message."""
    if not isinstance(value, str):
        raise TypeError(context)
    return value


def require_json_integer(value: JsonValue, context: str) -> int:
    """Require an integer JSON value, excluding booleans."""
    if type(value) is not int:
        raise TypeError(context)
    return value


def require_json_boolean(value: JsonValue, context: str) -> bool:
    """Require a JSON boolean rather than a truthy scalar."""
    if not isinstance(value, bool):
        raise TypeError(context)
    return value
