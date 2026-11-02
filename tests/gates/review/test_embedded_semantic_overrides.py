from pathlib import Path

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
