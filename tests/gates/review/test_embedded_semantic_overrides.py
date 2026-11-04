from pathlib import Path

import pytest

from alphus.config import EmbeddedSemanticOverridePolicy
from alphus.gates.review.embedded_semantic_overrides import (
    check_embedded_semantic_overrides,
    embedded_override_sites,
)


def _policy(*, exclude: tuple[str, ...] = ()) -> EmbeddedSemanticOverridePolicy:
    return EmbeddedSemanticOverridePolicy(
        extensions=(".py",),
        source_paths=("src/render/*.py",),
        replacement_maps=("fixed_paragraphs",),
        source_anchor_helpers=("source_anchor",),
        exclude=exclude,
    )


def test_detects_configured_replacement_returned_with_original_source_anchor() -> None:
    source = """\
def render(cell):
    replacement = fixed_paragraphs.get(cell.attribute)
    if replacement is not None:
        return source_anchor(cell.id) + replacement
"""
    assert embedded_override_sites(source, _policy()) == [
        ("render", 2, 3, "replacement")
    ]


def test_ignores_unknown_map_helpers_and_output_only_replacements() -> None:
    unknown_map = """\
def render(cell):
    replacement = other_map.get(cell.attribute)
    if replacement is not None:
        return source_anchor(cell.id) + replacement
"""
    output_only = """\
def render(cell):
    replacement = fixed_paragraphs.get(cell.attribute)
    if replacement is not None:
        return replacement
"""
    wrong_anchor = """\
def render(cell):
    replacement = fixed_paragraphs.get(cell.attribute)
    if replacement is not None:
        return other_anchor(cell.id) + replacement
"""
    assert not embedded_override_sites(unknown_map, _policy())
    assert not embedded_override_sites(output_only, _policy())
    assert not embedded_override_sites(wrong_anchor, _policy())


def test_rebound_map_value_is_not_reported_as_the_mapped_replacement() -> None:
    source = """\
def render(cell):
    replacement = fixed_paragraphs.get(cell.attribute)
    replacement = cell.text
    if replacement is not None:
        return source_anchor(cell.id) + replacement
"""
    assert embedded_override_sites(source, _policy()) == []


def test_pattern_capture_rebinding_invalidates_mapped_replacement() -> None:
    source = """\
def render(cell):
    replacement = fixed_paragraphs.get(cell.attribute)
    match cell.text:
        case str() as replacement:
            pass
    if replacement is not None:
        return source_anchor(cell.id) + replacement
"""
    assert embedded_override_sites(source, _policy()) == []


def test_annotation_only_statement_preserves_mapped_replacement() -> None:
    source = """\
def render(cell):
    replacement = fixed_paragraphs.get(cell.attribute)
    replacement: str | None
    if replacement is not None:
        return source_anchor(cell.id) + replacement
"""
    assert embedded_override_sites(source, _policy()) == [
        ("render", 2, 4, "replacement")
    ]


def test_nested_function_body_write_does_not_invalidate_replacement() -> None:
    source = """\
def render(cell):
    replacement = fixed_paragraphs.get(cell.attribute)
    def unrelated():
        replacement = "other"
    if replacement is not None:
        return source_anchor(cell.id) + replacement
"""
    assert embedded_override_sites(source, _policy()) == [
        ("render", 2, 5, "replacement")
    ]


def test_comprehension_local_target_does_not_invalidate_replacement() -> None:
    source = """\
def render(cell, callbacks):
    replacement = fixed_paragraphs.get(cell.attribute)
    previews = [replacement for replacement in callbacks]
    if replacement is not None:
        return source_anchor(cell.id) + replacement
"""
    assert embedded_override_sites(source, _policy()) == [
        ("render", 2, 4, "replacement")
    ]


def test_comprehension_walrus_invalidates_enclosing_replacement() -> None:
    source = """\
def render(cell, callbacks):
    replacement = fixed_paragraphs.get(cell.attribute)
    previews = [item for item in callbacks if (replacement := item)]
    if replacement is not None:
        return source_anchor(cell.id) + replacement
"""
    assert embedded_override_sites(source, _policy()) == []


def test_lazy_generator_body_walrus_preserves_mapped_replacement() -> None:
    source = """\
def render(cell, original):
    replacement = fixed_paragraphs.get(cell.attribute)
    updates = ((replacement := original) for _ in range(1))
    if replacement is not None:
        return source_anchor(cell.id) + replacement
    return cell.text
"""
    assert embedded_override_sites(source, _policy()) == [
        ("render", 2, 4, "replacement")
    ]


def test_generator_outer_iterable_walrus_invalidates_mapped_replacement() -> None:
    source = """\
def render(cell, originals):
    replacement = fixed_paragraphs.get(cell.attribute)
    updates = (item for item in (replacement := originals))
    if replacement is not None:
        return source_anchor(cell.id) + replacement
    return cell.text
"""
    assert embedded_override_sites(source, _policy()) == []


def test_definition_time_walrus_invalidates_replacement() -> None:
    source = """\
def render(cell):
    replacement = fixed_paragraphs.get(cell.attribute)
    def unrelated(value=(replacement := cell.text)):
        pass
    if replacement is not None:
        return source_anchor(cell.id) + replacement
"""
    assert embedded_override_sites(source, _policy()) == []


@pytest.mark.parametrize(
    "import_statement",
    [
        "from constants import ORIGINAL_TEXT as replacement",
        "import constants as replacement",
    ],
)
def test_import_rebinding_invalidates_mapped_replacement(
    import_statement: str,
) -> None:
    source = (
        "def render(cell):\n"
        "    replacement = fixed_paragraphs.get(cell.attribute)\n"
        f"    {import_statement}\n"
        "    if replacement is not None:\n"
        "        return source_anchor(cell.id) + replacement\n"
    )

    assert embedded_override_sites(source, _policy()) == []


def test_unrelated_import_does_not_invalidate_mapped_replacement() -> None:
    source = (
        "def render(cell):\n"
        "    replacement = fixed_paragraphs.get(cell.attribute)\n"
        "    from constants import RAW_TEXT as original_text\n"
        "    if replacement is not None:\n"
        "        return source_anchor(cell.id) + replacement\n"
    )
    assert embedded_override_sites(source, _policy()) == [
        ("render", 2, 4, "replacement")
    ]


def test_reports_only_configured_scope_and_honors_exclusions(tmp_path: Path) -> None:
    path = tmp_path / "src/render/replacements.py"
    path.parent.mkdir(parents=True)
    path.write_text(
        "def render(cell):\n"
        "    replacement = fixed_paragraphs.get(cell.attribute)\n"
        "    if replacement is not None:\n"
        "        return source_anchor(cell.id) + replacement\n",
        encoding="utf-8",
    )
    findings = check_embedded_semantic_overrides(
        tmp_path, (Path("src/render/replacements.py"),), _policy()
    )
    assert len(findings) == 1
    assert findings[0].rule_id == (
        "alphus/python/none/correctness/embedded-semantic-override"
    )
    assert not check_embedded_semantic_overrides(
        tmp_path,
        (Path("src/render/replacements.py"),),
        _policy(exclude=("src/render/**",)),
    )
