"""Shared helpers for contained files and validated structured values."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import NoneType
from typing import Any, TypeAlias, cast

from pydantic import JsonValue as PydanticJsonValue
from pydantic import TypeAdapter

from alphus.support.source_text import read_utf8_text

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


def contains_member(value: object, expected: object) -> bool:
    """Check a sequence's contents, accepting both lists and tuples."""
    match value:
        case str() | bytes():
            return False
        case Sequence():
            return expected in cast(Sequence[object], value)
        case _:
            return False


def is_nonempty_mapping(value: object) -> bool:
    """Recognize a nonempty mapping by interface, not concrete type."""
    match value:
        case Mapping():
            return bool(cast(Mapping[object, object], value))
        case _:
            return False


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
    value = cast(JsonValue, _JSON_VALUE_ADAPTER.validate_json(source))
    _validate_standard_json_numbers(value)
    return value


def _validate_standard_json_numbers(value: JsonValue) -> None:
    """Reject non-finite values that Pydantic's permissive JSON parser accepts."""
    match value:
        case str():
            return
        case float() as number if not math.isfinite(number):
            raise ValueError("JSON numbers must be finite")
        case Mapping():
            mapping = cast(Mapping[str, JsonValue], value)
            for nested in mapping.values():
                _validate_standard_json_numbers(nested)
        case Sequence():
            sequence = cast(Sequence[JsonValue], value)
            for nested in sequence:
                _validate_standard_json_numbers(nested)
        case _:
            return


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


def optional_json_number(value: JsonValue) -> float | None:
    """Return a JSON number as float, excluding booleans."""
    if type(value) is int or type(value) is float:
        return float(value)
    return None


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


def load_json_object(path: Path) -> Mapping[str, JsonValue]:
    """Read and validate a JSON object using the repository text policy."""
    return require_json_object(
        validate_json_value(read_utf8_text(path)), f"expected a JSON object: {path}"
    )


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
