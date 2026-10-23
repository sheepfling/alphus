"""Focused checks for explicit-union runtime narrowing."""

from __future__ import annotations

from pathlib import Path

from alphus.config import RuntimeTypePolicy
from alphus.gates.source.runtime_types import policy_issues, type_check_findings

POLICY = RuntimeTypePolicy(
    extensions=(".py",),
    exclude=("**/tests/**", "tests/**", "**/test_*", "test_*"),
)


def test_explicit_unions_allow_narrowing() -> None:
    source = """
from typing import Union
def typed(value: int | str, other: Union[int, str]) -> None:
    if isinstance(value, int):
        pass
    if isinstance(other, (int, str)):
        pass
    if type(value) is str:
        pass
"""
    assert type_check_findings(source) == []


def test_raw_data_and_type_identity_are_reported() -> None:
    source = """
def raw(payload: object, number: int | str) -> None:
    ranges = payload
    if not isinstance(ranges, list):
        pass
    if isinstance(number, list):
        pass
    if type(payload) is dict:
        pass
"""
    assert [line for line, _ in type_check_findings(source)] == [4, 6, 8]


def test_tests_are_outside_runtime_policy(tmp_path: Path) -> None:
    runtime = tmp_path / "backend" / "module.py"
    test = tmp_path / "backend" / "tests" / "test_module.py"
    test.parent.mkdir(parents=True)
    runtime.write_text("isinstance(value, list)\n", encoding="utf-8")
    test.write_text("isinstance(value, list)\n", encoding="utf-8")
    assert (
        len(
            policy_issues(
                tmp_path,
                [Path("backend/module.py"), Path("backend/tests/test_module.py")],
                POLICY,
            )
        )
        == 1
    )


def test_pydantic_json_value_allows_its_declared_union_members() -> None:
    source = """
from pydantic import JsonValue
def typed(value: JsonValue) -> None:
    if isinstance(value, (str, int, float, bool, list, dict)):
        pass
"""
    assert type_check_findings(source) == []


def test_alphus_json_value_alias_allows_its_declared_union_members() -> None:
    source = """
from alphus.support.data_access import JsonValue
def typed(value: JsonValue) -> None:
    if isinstance(value, (str, int, float, bool, list, dict)):
        pass
"""
    assert type_check_findings(source) == []
