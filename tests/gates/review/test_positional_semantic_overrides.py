from __future__ import annotations

from pathlib import Path

import pytest

from alphus.config import PositionalSemanticOverridePolicy
from alphus.gates.review.positional_semantic_overrides import (
    check_positional_semantic_overrides,
    positional_override_sites,
)

_EXPLANATION = (
    "A long source-derived interpretation is selected by a table row number "
    "instead of by the section's semantic identity."
)


def _policy(**updates: object) -> PositionalSemanticOverridePolicy:
    return PositionalSemanticOverridePolicy.model_validate(
        {
            "extensions": (".py",),
            "exclude": (),
            "source_paths": ("src/**/*.py",),
            "position_variables": ("row_number",),
            "semantic_fields": ("Interpretation",),
            **updates,
        }
    )


def test_flags_configured_row_number_replacing_semantic_prose() -> None:
    source = f"""\
if row_number in {{3, 5}}:
    row["Interpretation"] = {_EXPLANATION!r}
"""
    assert positional_override_sites(source, _policy()) == [
        (1, 2, "row_number", (3, 5), _EXPLANATION)
    ]


def test_ignores_unconfigured_positions_fields_and_short_values() -> None:
    source = f"""\
if byte_offset in {3, 5}:
    row["Interpretation"] = "Short value"
if row_number == 4:
    row["Display"] = {_EXPLANATION!r}
if row_number == True:
    row["Interpretation"] = {_EXPLANATION!r}
"""
    assert positional_override_sites(source, _policy()) == []


def test_scope_and_configuration_errors_are_explicit(tmp_path: Path) -> None:
    target = tmp_path / "src" / "table.py"
    target.parent.mkdir()
    target.write_text(
        f'if row_number == 3:\n    row["Interpretation"] = {_EXPLANATION!r}\n',
        encoding="utf-8",
    )
    findings = check_positional_semantic_overrides(
        tmp_path, [Path("src/table.py")], _policy(source_paths=("src/*.py",))
    )
    assert len(findings) == 1
    assert (
        findings[0].rule_id
        == "alphus/python/none/maintainability/positional-semantic-override"
    )
    with pytest.raises(ValueError, match="position variables must be identifiers"):
        _policy(position_variables=("row-number",))
