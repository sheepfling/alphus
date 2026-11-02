from pathlib import Path

import pytest
from pydantic import ValidationError

from alphus.config import UnexplainedEmptyResultPolicy
from alphus.gates.review.unexplained_empty_results import (
    check_unexplained_empty_results,
    empty_result_branches,
)


def _policy(**updates: object) -> UnexplainedEmptyResultPolicy:
    data: dict[str, object] = {
        "extensions": (".py",),
        "source_paths": ("src/parser/*.py",),
        "nonempty_inputs": ("records",),
        "unavailable_flags": ("inferred_schema",),
    }
    data.update(updates)
    return UnexplainedEmptyResultPolicy.model_validate(data)


def test_detects_nonempty_input_with_unknown_inference_returning_empty() -> None:
    source = """\
def parse(records):
    if records and not inferred_schema:
        return []
    return parse_rows(records)
"""
    assert empty_result_branches(source, _policy()) == [
        (3, "records", "inferred_schema")
    ]


def test_ignores_valid_empty_input_and_nonempty_result_branches() -> None:
    valid_empty = """\
def parse(records):
    if not records:
        return []
"""
    nonempty_result = """\
def parse(records):
    if records and not inferred_schema:
        raise UnknownFormatError()
"""
    assert empty_result_branches(valid_empty, _policy()) == []
    assert empty_result_branches(nonempty_result, _policy()) == []


def test_configuration_is_explicit_and_names_are_validated() -> None:
    with pytest.raises(
        ValidationError, match="input and inference names must be identifiers"
    ):
        _policy(nonempty_inputs=("records[0]",))


def test_reports_configured_source_scope_and_exclusions(tmp_path: Path) -> None:
    path = tmp_path / "src/parser/table.py"
    path.parent.mkdir(parents=True)
    path.write_text(
        "def parse(records):\n"
        "    if records and not inferred_schema:\n"
        "        return []\n",
        encoding="utf-8",
    )
    findings = check_unexplained_empty_results(
        tmp_path, (Path("src/parser/table.py"),), _policy()
    )
    assert len(findings) == 1
    assert findings[0].rule_id == (
        "alphus/python/none/validation/unexplained-empty-result"
    )
    assert not check_unexplained_empty_results(
        tmp_path,
        (Path("src/parser/table.py"),),
        _policy(exclude=("src/parser/**",)),
    )
