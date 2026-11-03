from pathlib import Path

import pytest

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


def test_annotation_only_statement_preserves_rendered_binding() -> None:
    source = """\
def merge(text):
    rendered = render_latex(text)
    rendered: str
    if rendered.rstrip().endswith("!"):
        return True
"""
    assert _sites(source, ("render_latex",)) == [(2, 4, "rendered")]


@pytest.mark.parametrize(
    "assignment",
    [
        "values[(rendered := original)] = 1",
        "values[(rendered := original)]: int = 1",
        "values[(rendered := original)] += 1",
    ],
)
def test_walrus_in_evaluated_assignment_target_invalidates_rendered_binding(
    assignment: str,
) -> None:
    source = f"""\
def merge(text, original, values):
    rendered = render_latex(text)
    {assignment}
    if rendered.rstrip().endswith('!'):
        return True
"""
    assert _sites(source, ("render_latex",)) == []


def test_unrelated_walrus_in_assignment_target_preserves_rendered_binding() -> None:
    source = """\
def merge(text, original, values):
    rendered = render_latex(text)
    values[(other := original)] = 1
    if rendered.rstrip().endswith('!'):
        return True
"""
    assert _sites(source, ("render_latex",)) == [(2, 4, "rendered")]


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


def test_tracks_renderer_calls_with_keyword_only_inputs() -> None:
    assignment = """\
def merge(text):
    rendered = render_latex(text=text)
    if rendered.rstrip().endswith("!"):
        return True
"""
    annotated_assignment = """\
def merge(text):
    rendered: str = render_latex(text=text)
    if rendered.rstrip().endswith("!"):
        return True
"""
    zero_argument_call = """\
def merge(text):
    rendered = render_latex()
    if rendered.rstrip().endswith("!"):
        return True
"""
    assert _sites(assignment, ("render_latex",)) == [(2, 3, "rendered")]
    assert _sites(annotated_assignment, ("render_latex",)) == [(2, 3, "rendered")]
    assert _sites(zero_argument_call, ("render_latex",)) == []


@pytest.mark.parametrize(
    "assignment",
    [
        "preview = render_latex(rendered := source)",
        "preview: str = render_latex(text=(rendered := source))",
    ],
)
def test_renderer_call_walrus_invalidates_rebound_rendered_local(
    assignment: str,
) -> None:
    source = (
        "def f(text, source):\n"
        "    rendered = render_latex(text)\n"
        f"    {assignment}\n"
        "    if rendered.rstrip().endswith('!'):\n"
        "        return True\n"
    )

    assert _sites(source, ("render_latex",)) == []


def test_unrelated_renderer_argument_walrus_preserves_rendered_local() -> None:
    source = """\
def f(text, source):
    rendered = render_latex(text)
    preview = render_latex(other := source)
    if rendered.rstrip().endswith("!"):
        return True
"""
    assert _sites(source, ("render_latex",)) == [(2, 4, "rendered")]


def test_renderer_assignment_rebinds_target_after_argument_walrus() -> None:
    source = """\
def f(text, source):
    rendered = render_latex(rendered := source)
    if rendered.rstrip().endswith("!"):
        return True
"""
    assert _sites(source, ("render_latex",)) == [(2, 3, "rendered")]


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


def test_nested_function_default_walrus_invalidates_outer_binding() -> None:
    source = (
        "def f(text, original):\n"
        "    rendered = render(text)\n"
        "    def nested(value=(rendered := original)):\n"
        "        return value\n"
        "    if rendered.rstrip().endswith('!'):\n"
        "        return True\n"
    )
    assert _sites(source, ("render",)) == []


def test_nested_function_decorator_walrus_invalidates_outer_binding() -> None:
    source = (
        "def f(text, original):\n"
        "    rendered = render(text)\n"
        "    @decorate((rendered := original))\n"
        "    def nested():\n"
        "        return None\n"
        "    if rendered.rstrip().endswith('!'):\n"
        "        return True\n"
    )
    assert _sites(source, ("render",)) == []


def test_unrelated_nested_definition_time_walrus_preserves_outer_binding() -> None:
    source = (
        "def f(text, original):\n"
        "    rendered = render(text)\n"
        "    def nested(value=(other := original)):\n"
        "        return value\n"
        "    if rendered.rstrip().endswith('!'):\n"
        "        return True\n"
    )
    assert _sites(source, ("render",)) == [(2, 5, "rendered")]


def test_lambda_body_walrus_does_not_invalidate_outer_binding() -> None:
    source = (
        "def f(text, original):\n"
        "    rendered = render(text)\n"
        "    callback = lambda: (rendered := original)\n"
        "    if rendered.rstrip().endswith('!'):\n"
        "        return True\n"
    )
    assert _sites(source, ("render",)) == [(2, 4, "rendered")]


def test_lambda_default_walrus_invalidates_outer_binding() -> None:
    source = (
        "def f(text, original):\n"
        "    rendered = render(text)\n"
        "    callback = lambda value=(rendered := original): value\n"
        "    if rendered.rstrip().endswith('!'):\n"
        "        return True\n"
    )
    assert _sites(source, ("render",)) == []


def test_expression_statement_walrus_invalidates_rendered_binding() -> None:
    source = """\
def f(text, original):
    rendered = render(text)
    consume(rendered := original)
    if rendered.rstrip().endswith('!'):
        return True
"""
    assert _sites(source, ("render",)) == []


def test_unrelated_expression_walrus_preserves_rendered_binding() -> None:
    source = """\
def f(text, original):
    rendered = render(text)
    consume(other := original)
    if rendered.rstrip().endswith('!'):
        return True
"""
    assert _sites(source, ("render",)) == [(2, 4, "rendered")]


def test_assertion_walrus_invalidates_rendered_binding() -> None:
    source = (
        "def f(text, original):\n"
        "    rendered = render(text)\n"
        "    assert (rendered := original)\n"
        "    if rendered.rstrip().endswith('!'):\n"
        "        return True\n"
    )
    assert _sites(source, ("render",)) == []


def test_unrelated_assertion_walrus_preserves_rendered_binding() -> None:
    source = (
        "def f(text, original):\n"
        "    rendered = render(text)\n"
        "    assert (other := original)\n"
        "    if rendered.rstrip().endswith('!'):\n"
        "        return True\n"
    )
    assert _sites(source, ("render",)) == [(2, 4, "rendered")]


@pytest.mark.parametrize(
    "statement",
    [
        "other = (rendered := original)",
        "other: object = (rendered := original)",
        "other += (rendered := original)",
    ],
)
def test_assignment_value_walrus_invalidates_rendered_binding(
    statement: str,
) -> None:
    source = f"""\
def f(text, original, other):
    rendered = render(text)
    {statement}
    if rendered.rstrip().endswith('!'):
        return True
"""
    assert _sites(source, ("render",)) == []


def test_finally_predicate_requires_the_rendered_binding_on_all_entry_paths() -> None:
    source = """\
def f(text, other):
    rendered = render(text)
    try:
        rendered = other
    finally:
        if rendered.rstrip().endswith('!'):
            return True
"""
    assert _sites(source, ("render",)) == []


def test_finally_predicate_accepts_a_binding_preserved_on_all_paths() -> None:
    source = """\
def f(text):
    rendered = render(text)
    try:
        consume(rendered)
    finally:
        if rendered.rstrip().endswith('!'):
            return True
"""
    assert _sites(source, ("render",)) == [(2, 6, "rendered")]


def test_exception_group_assignment_invalidates_rendered_binding() -> None:
    source = (
        "def f(text, original):\n"
        "    rendered = render(text)\n"
        "    try:\n"
        "        rendered = original\n"
        "    except* ValueError:\n"
        "        if rendered.rstrip().endswith('!'):\n"
        "            return True\n"
        "    if rendered.rstrip().endswith('?'):\n"
        "        return True\n"
    )
    assert _sites(source, ("render",)) == []


def test_exception_group_handler_scans_preserved_rendered_binding() -> None:
    source = (
        "def f(text):\n"
        "    rendered = render(text)\n"
        "    try:\n"
        "        consume()\n"
        "    except* ValueError:\n"
        "        if rendered.rstrip().endswith('!'):\n"
        "            return True\n"
    )
    assert _sites(source, ("render",)) == [(2, 6, "rendered")]


def test_match_capture_invalidates_prior_rendered_binding_within_case() -> None:
    source = """\
def f(text):
    rendered = render(text)
    match text:
        case {"text": rendered}:
            if rendered.rstrip().endswith("!"):
                return True
    return False
"""
    assert _sites(source, ("render",)) == []


def test_unrelated_match_capture_preserves_rendered_binding() -> None:
    source = """\
def f(text):
    rendered = render(text)
    match text:
        case {"text": other}:
            if rendered.rstrip().endswith("!"):
                return True
    return False
"""
    assert _sites(source, ("render",)) == [(2, 5, "rendered")]


def test_try_handler_requires_rendered_binding_to_survive_possible_exception() -> None:
    source = """\
def f(text, original):
    rendered = render(text)
    try:
        rendered = original
        raise ValueError()
    except ValueError:
        if rendered.rstrip().endswith("!"):
            return True
    return False
"""
    assert _sites(source, ("render",)) == []


def test_if_walrus_invalidates_rendered_binding_in_branches_and_afterward() -> None:
    source = """\
def f(text, original):
    rendered = render(text)
    if (rendered := original):
        if rendered.rstrip().endswith("!"):
            return True
    if rendered.rstrip().endswith("?"):
        return True
    return False
"""
    assert _sites(source, ("render",)) == []


def test_while_walrus_invalidates_rendered_binding_in_body_and_afterward() -> None:
    source = """\
def f(text, chunks):
    rendered = render(text)
    while (rendered := next(chunks, "")):
        if rendered.rstrip().endswith("!"):
            return True
    if rendered.rstrip().endswith("?"):
        return True
    return False
"""
    assert _sites(source, ("render",)) == []


def test_for_target_invalidation_reaches_else_suite() -> None:
    source = """\
def f(text):
    rendered = render(text)
    for rendered in ["unrendered!"]:
        pass
    else:
        if rendered.rstrip().endswith("!"):
            return True
    return False
"""
    assert _sites(source, ("render",)) == []


def test_for_iterable_walrus_invalidates_rendered_binding_everywhere() -> None:
    source = """\
def f(text, original):
    rendered = render(text)
    for char in (rendered := original):
        if rendered.rstrip().endswith("!"):
            return True
    else:
        if rendered.rstrip().endswith("?"):
            return True
    if rendered.rstrip().endswith("."):
        return True
    return False
"""
    assert _sites(source, ("render",)) == []


def test_unrelated_for_iterable_walrus_preserves_rendered_binding() -> None:
    source = """\
def f(text, original):
    rendered = render(text)
    for char in (other := original):
        if rendered.rstrip().endswith("!"):
            return True
    return False
"""
    assert _sites(source, ("render",)) == [(2, 4, "rendered")]


def test_with_context_walrus_invalidates_rendered_binding_in_body_and_after() -> None:
    source = """\
def f(text, original):
    rendered = render(text)
    with manager(rendered := original):
        if rendered.rstrip().endswith("!"):
            return True
    if rendered.rstrip().endswith("?"):
        return True
    return False

async def async_f(text, original):
    rendered = render(text)
    async with manager(rendered := original):
        if rendered.rstrip().endswith("!"):
            return True
    return False
"""
    assert _sites(source, ("render",)) == []


def test_unrelated_with_context_walrus_preserves_rendered_binding() -> None:
    source = """\
def f(text, original):
    rendered = render(text)
    with manager(other := original):
        if rendered.rstrip().endswith("!"):
            return True
    return False
"""
    assert _sites(source, ("render",)) == [(2, 4, "rendered")]


def test_import_alias_invalidates_rendered_binding() -> None:
    source = """\
def f(text):
    rendered = render(text)
    from constants import RAW_TEXT as rendered
    if rendered.rstrip().endswith("!"):
        return True
    return False
"""
    assert _sites(source, ("render",)) == []


def test_unrelated_import_alias_preserves_rendered_binding() -> None:
    source = """\
def f(text):
    rendered = render(text)
    from constants import RAW_TEXT as original
    if rendered.rstrip().endswith("!"):
        return True
    return False
"""
    assert _sites(source, ("render",)) == [(2, 4, "rendered")]


def test_match_subject_and_guard_walruses_invalidate_rendered_binding() -> None:
    source = """\
def f(text, original):
    rendered = render(text)
    match (rendered := original):
        case str():
            if rendered.rstrip().endswith("!"):
                return True
    if rendered.rstrip().endswith("?"):
        return True
    rendered = render(text)
    match original:
        case str() if (rendered := original):
            if rendered.rstrip().endswith("!"):
                return True
    return False
"""
    assert _sites(source, ("render",)) == []


def test_match_guard_walrus_invalidates_later_case_after_guard_fallthrough() -> None:
    source = """\
def f(text, original):
    rendered = render(text)
    match original:
        case str() if (rendered := original) and False:
            pass
        case str():
            if rendered.rstrip().endswith("!"):
                return True
    return False
"""
    assert _sites(source, ("render",)) == []


def test_match_capture_invalidates_later_case_after_guard_fallthrough() -> None:
    source = (
        "def f(text, original):\n"
        "    rendered = render(text)\n"
        "    match original:\n"
        "        case str() as rendered if len(rendered) > 100:\n"
        "            pass\n"
        "        case _:\n"
        "            if rendered.rstrip().endswith('!'):\n"
        "                return True\n"
    )
    assert _sites(source, ("render",)) == []


def test_unrelated_match_capture_preserves_later_case_binding() -> None:
    source = (
        "def f(text, original):\n"
        "    rendered = render(text)\n"
        "    match original:\n"
        "        case str() as other if len(other) > 100:\n"
        "            pass\n"
        "        case _:\n"
        "            if rendered.rstrip().endswith('!'):\n"
        "                return True\n"
    )
    assert _sites(source, ("render",)) == [(2, 7, "rendered")]


def test_unrelated_match_subject_and_guard_walruses_preserve_rendered_binding() -> None:
    source = """\
def f(text, original):
    rendered = render(text)
    match (other := original):
        case str() if (also_other := original):
            if rendered.rstrip().endswith("!"):
                return True
    return False
"""
    assert _sites(source, ("render",)) == [(2, 5, "rendered")]


def test_for_else_preserves_unmodified_rendered_binding() -> None:
    source = """\
def f(text):
    rendered = render(text)
    for _item in ():
        pass
    else:
        if rendered.rstrip().endswith("!"):
            return True
    return False
"""
    assert _sites(source, ("render",)) == [(2, 6, "rendered")]


def test_while_body_overwrite_is_applied_before_else_suite() -> None:
    source = """\
def f(text, original, enabled):
    rendered = render(text)
    while enabled:
        rendered = original
        enabled = False
    else:
        if rendered.rstrip().endswith("!"):
            return True
    return False
"""
    assert _sites(source, ("render",)) == []


def test_while_else_preserves_unmodified_rendered_binding() -> None:
    source = """\
def f(text, enabled):
    rendered = render(text)
    while enabled:
        consume()
        enabled = False
    else:
        if rendered.rstrip().endswith("!"):
            return True
    return False
"""
    assert _sites(source, ("render",)) == [(2, 7, "rendered")]


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
