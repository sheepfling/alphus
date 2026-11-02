from pathlib import Path

import pytest

from alphus.config import ProseAsControlPolicy
from alphus.gates.review.prose_as_control import (
    check_prose_as_control,
    prose_control_literals,
)

_SENTENCE = (
    "Source-derived normative statement retained at clause scope; "
    "no modeled transition was asserted."
)


def _policy(**overrides: object) -> ProseAsControlPolicy:
    return ProseAsControlPolicy(
        extensions=(".py",), source_paths=("src/render/*.py",), **overrides
    )


def test_reports_long_prose_literal_used_as_branch_discriminator() -> None:
    source = f'if note == "{_SENTENCE}":\n    suppress_note()\n'
    assert prose_control_literals(source, _policy()) == [(1, _SENTENCE)]


def test_ignores_short_protocol_text_and_prose_only_in_output() -> None:
    source = f'''\
if response == "OK":
    accept()
message = "{_SENTENCE}"
'''
    assert prose_control_literals(source, _policy()) == []


def test_allowlist_preserves_known_protocol_or_compatibility_literals() -> None:
    source = f'if note == "{_SENTENCE}":\n    preserve()\n'
    assert not prose_control_literals(source, _policy(allowed_literals=(_SENTENCE,)))


@pytest.mark.parametrize("separator", ["\n", "\r"])
def test_allowlist_accepts_exact_multiline_protocol_literals(separator: str) -> None:
    literal = (
        "The remote peer reports a state transition"
        f"{separator}that this client does not handle and needs review."
    )
    source = f"if note == {literal!r}:\n    preserve()\n"

    assert prose_control_literals(source, _policy(allowed_literals=(literal,))) == []


def test_allowlist_rejects_empty_literal() -> None:
    with pytest.raises(ValueError, match="allowed prose literals must be non-empty"):
        _policy(allowed_literals=("",))


def test_only_branch_comparisons_are_reported() -> None:
    source = f'result = note == "{_SENTENCE}"\n'
    assert prose_control_literals(source, _policy()) == []


def test_scans_only_declared_paths_and_respects_exclusions(tmp_path: Path) -> None:
    source = tmp_path / "src/render/report.py"
    source.parent.mkdir(parents=True)
    source.write_text(f'if note == "{_SENTENCE}":\n    pass\n', encoding="utf-8")

    findings = check_prose_as_control(
        tmp_path, [Path("src/render/report.py")], _policy()
    )
    assert len(findings) == 1
    assert findings[0].path == "src/render/report.py"
    assert findings[0].line == 1
    assert "does not imply AI authorship" in findings[0].message

    excluded = _policy(exclude=("src/render/**",))
    assert not check_prose_as_control(
        tmp_path, [Path("src/render/report.py")], excluded
    )
