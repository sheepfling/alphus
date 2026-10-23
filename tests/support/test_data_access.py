"""Tests for shared JSON decoding helpers."""

import pytest
from pydantic import ValidationError

from alphus.support.data_access import validate_json_value


def test_validate_json_value_returns_nested_json_values() -> None:
    assert validate_json_value('{"items": [1, true, null], "name": "sample"}') == {
        "items": [1, True, None],
        "name": "sample",
    }


def test_validate_json_value_rejects_malformed_json() -> None:
    with pytest.raises(ValidationError):
        validate_json_value("{")
