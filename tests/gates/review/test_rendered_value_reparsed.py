from pathlib import Path

from alphus.config import ProseAsControlPolicy
from alphus.gates.review.rendered_value_reparsed import (
    _sites,
    check_rendered_value_reparsed,
)


def _policy() -> ProseAsControlPolicy:
    return ProseAsControlPolicy(
        extensions=(".py",),
        source_paths=("src/render/*.py",),
        rendered_value_helpers=("render_latex",),
    )


def test_detects_rendered_output_reparsed_for_suffix() -> None:
    source = """
def merge(cell):
    rendered = render_latex(cell.text)
    if rendered.rstrip().endswith("-"):
        join_next_cell()
"""
    assert _sites(source, ("render_latex",)) == [(3, 4, "rendered")]


def test_ignores_output_only_and_unconfigured_renderers() -> None:
    output_only = """
def render(cell):
    rendered = render_latex(cell.text)
    return f"<td>{rendered}</td>"
"""
    other_renderer = """
def merge(cell):
    rendered = escape_html(cell.text)
    if rendered.rstrip().endswith("-"):
        join_next_cell()
"""
    assert not _sites(output_only, ("render_latex",))
    assert not _sites(other_renderer, ("render_latex",))


def test_rendered_binding_must_precede_predicate_in_same_scope() -> None:
    predicate_first = """\
def f(text):
    if text.rstrip().endswith('!'):
        return True
    text = render(text)
"""
    rebound_before_predicate = """\
def f(text):
    rendered = render(text)
    rendered = normalize(rendered)
    if rendered.rstrip().endswith('!'):
        return True
"""
    rendered_only_in_one_branch = """\
def f(text, enabled):
    if enabled:
        rendered = render(text)
    if rendered.rstrip().endswith('!'):
        return True
"""
    assert _sites(predicate_first, ("render",)) == []
    assert _sites(rebound_before_predicate, ("render",)) == []
    assert _sites(rendered_only_in_one_branch, ("render",)) == []


def test_nested_scope_assignment_does_not_reorder_outer_binding() -> None:
    source = """\
def f(text):
    rendered = render(text)
    def nested():
        rendered = text
    if rendered.rstrip().endswith('!'):
        return True
"""
    assert _sites(source, ("render",)) == [(2, 5, "rendered")]


def test_advisory_reports_configured_source_path(tmp_path: Path) -> None:
    source = tmp_path / "src/render/table.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "def merge(cell):\n"
        "    rendered = render_latex(cell.text)\n"
        "    if rendered.rstrip().endswith('-'):\n"
        "        join_next_cell()\n",
        encoding="utf-8",
    )
    findings = check_rendered_value_reparsed(
        tmp_path, (Path("src/render/table.py"),), _policy()
    )
    assert len(findings) == 1
    assert findings[0].rule_id == (
        "alphus/python/none/correctness/rendered-value-reparsed"
    )


def test_unconfigured_helpers_produce_no_findings() -> None:
    assert not _sites(
        'def f(x):\n y = render_latex(x)\n if y.rstrip().endswith("-"): pass', ()
    )
