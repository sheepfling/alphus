"""Tests for shared JSON decoding helpers."""

from collections import UserDict

import pytest
from pydantic import ValidationError

from alphus.support.data_access import (
    contains_member,
    is_nonempty_mapping,
    validate_json_value,
)


def test_validate_json_value_returns_nested_json_values() -> None:
    assert validate_json_value('{"items": [1, true, null], "name": "sample"}') == {
        "items": [1, True, None],
        "name": "sample",
    }


def test_validate_json_value_rejects_malformed_json() -> None:
    with pytest.raises(ValidationError):
        validate_json_value("{")


def test_validate_json_value_rejects_non_finite_numbers() -> None:
    with pytest.raises(ValueError, match="finite"):
        validate_json_value('{"nested": [NaN]}')


def test_collection_helpers_accept_sequence_and_mapping_interfaces() -> None:
    assert contains_member(("one", "two"), "two")
    assert contains_member(["one", "two"], "one")
    assert not contains_member("two", "two")
    assert is_nonempty_mapping(UserDict({"key": 1}))
    assert not is_nonempty_mapping(UserDict())
