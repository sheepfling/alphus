"""Curated synthetic positives and boundary negatives for issue #50 rules."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import pytest

from alphus.config import (
    EmbeddedSemanticOverridePolicy,
    HeuristicTotalConsumptionPolicy,
    PositionalSemanticOverridePolicy,
    ProseAsControlPolicy,
    ProvenanceOwnershipPolicy,
    SemanticWorkPresentationPolicy,
    UnexplainedEmptyResultPolicy,
)
from alphus.gates.review.embedded_semantic_overrides import embedded_override_sites
from alphus.gates.review.heuristic_total_consumption import (
    heuristic_total_consumption_sites,
)
from alphus.gates.review.positional_semantic_overrides import positional_override_sites
from alphus.gates.review.prose_as_control import (
    lossy_rewrite_lines,
    prose_control_literals,
)
from alphus.gates.review.provenance_ownership import provenance_ownership_sites
from alphus.gates.review.rendered_value_reparsed import _sites as rendered_sites
from alphus.gates.review.semantic_work_presentation import (
    semantic_work_presentation_sites,
)
from alphus.gates.review.unexplained_empty_results import empty_result_branches


@dataclass(frozen=True, slots=True)
class _CorpusCase:
    name: str
    source: str
    should_match: bool
    detector: Callable[[str], bool]


_PROSE = ProseAsControlPolicy(
    extensions=(".py",),
    exclude=(),
    source_paths=("src/render/*.py",),
    minimum_characters=80,
    minimum_words=10,
    lossy_text_rewrite=True,
    regex_sub_helpers=("re.sub",),
)
_POSITION = PositionalSemanticOverridePolicy(
    extensions=(".py",),
    exclude=(),
    source_paths=("src/render/*.py",),
    position_variables=("row_number",),
    semantic_fields=("Interpretation",),
)
_EMPTY = UnexplainedEmptyResultPolicy(
    extensions=(".py",),
    exclude=(),
    source_paths=("src/render/*.py",),
    nonempty_inputs=("records",),
    unavailable_flags=("inferred_schema",),
)
_EMBEDDED = EmbeddedSemanticOverridePolicy(
    extensions=(".py",),
    exclude=(),
    source_paths=("src/render/*.py",),
    replacement_maps=("fixed_paragraphs",),
    source_anchor_helpers=("source_anchor",),
)
_TOTAL_CONSUMPTION = HeuristicTotalConsumptionPolicy(
    extensions=(".py",),
    exclude=(),
    source_paths=("src/render/*.py",),
    function_names=("preserve_text",),
    input_names=("text",),
    token_match_helpers=("re.findall",),
    output_contract="preserve-unmatched-spans",
)
_PROVENANCE_OWNERSHIP = ProvenanceOwnershipPolicy(
    extensions=(".py",),
    exclude=(),
    source_paths=("src/render/*.py",),
    function_names=("remaining_paragraphs",),
    owner_collection_names=("tables",),
    candidate_collection_names=("paragraphs",),
    ownership_basis="exact-source-span",
)
_PRESENTATION_BOUNDARY = SemanticWorkPresentationPolicy(
    extensions=(".py",),
    exclude=(),
    source_paths=("src/render/*.py",),
    function_names=("render_document",),
    source_layout_helpers=("reconstruct_layout",),
    content_correction_helpers=("apply_content_correction",),
    semantic_ownership_helpers=("decide_semantic_ownership",),
    serialization_helpers=("serialize_output",),
    module_role="presentation",
)


def _matches(detector: Callable[[str], object], source: str) -> bool:
    return bool(detector(source))


def _case(name: str, source: str, detector: Callable[[str], object]) -> _CorpusCase:
    return _CorpusCase(name, source, True, lambda text: _matches(detector, text))


def _negative(name: str, source: str, detector: Callable[[str], object]) -> _CorpusCase:
    return _CorpusCase(name, source, False, lambda text: _matches(detector, text))


def _rendered(text: str) -> object:
    return rendered_sites(text, ("render_latex",))


def _prose(text: str) -> object:
    return prose_control_literals(text, _PROSE)


def _lossy(text: str) -> object:
    return lossy_rewrite_lines(text, _PROSE)


def _position(text: str) -> object:
    return positional_override_sites(text, _POSITION)


def _empty(text: str) -> object:
    return empty_result_branches(text, _EMPTY)


def _embedded(text: str) -> object:
    return embedded_override_sites(text, _EMBEDDED)


def _total_consumption(text: str) -> object:
    return heuristic_total_consumption_sites(text, _TOTAL_CONSUMPTION)


def _provenance_ownership(text: str) -> object:
    return provenance_ownership_sites(text, _PROVENANCE_OWNERSHIP)


def _presentation_boundary(text: str) -> object:
    return semantic_work_presentation_sites(text, _PRESENTATION_BOUNDARY)


_CASES = (
    _case(
        "rendered feedback",
        "def merge(cell):\n"
        "    rendered = render_latex(cell.text)\n"
        "    if rendered.rstrip().endswith('-'):\n"
        "        join_next_cell()\n",
        _rendered,
    ),
    _negative(
        "output-only markup",
        "def render(cell):\n"
        "    rendered = render_latex(cell.text)\n"
        "    return f'<td>{rendered}</td>'\n",
        _rendered,
    ),
    _case(
        "sentence discriminator",
        'if note == "Source-derived normative statement retained at clause scope; '
        'no modeled transition was asserted.":\n    suppress_note()\n',
        _prose,
    ),
    _negative(
        "short protocol status",
        'if response == "OK":\n    handle_protocol_response()\n',
        _prose,
    ),
    _case(
        "numeric prose deletion",
        'import re\ncleaned = re.sub(r"(?<!\\S)\\d{1,3}\\.\\d{2}(?!\\S)", " ", prose)\n',
        _lossy,
    ),
    _negative(
        "whitespace normalization",
        'import re\ncleaned = prose.strip()\nnormalized = re.sub(r"\\s+", " ", prose)\n',
        _lossy,
    ),
    _case(
        "position selects semantic text",
        "if row_number in {3, 5}:\n"
        '    row["Interpretation"] = '
        '"A fixed explanation replaces the source-derived meaning for this row."\n',
        _position,
    ),
    _negative(
        "position selects layout slice",
        "payload = data[HEADER_SIZE:HEADER_SIZE + FIELD_SIZE]\n",
        _position,
    ),
    _case(
        "unknown schema becomes empty success",
        "if records and not inferred_schema:\n    return []\n",
        _empty,
    ),
    _negative(
        "legitimate empty input",
        "if not records:\n    return []\n",
        _empty,
    ),
    _case(
        "replacement returned with original anchor",
        "def render(cell):\n"
        "    replacement = fixed_paragraphs.get(cell.attribute)\n"
        "    if replacement is not None:\n"
        "        return source_anchor(cell.id) + replacement\n",
        _embedded,
    ),
    _negative(
        "source text preserved with anchor",
        "def render(cell):\n"
        "    replacement = fixed_paragraphs.get(cell.attribute)\n"
        "    if replacement is not None:\n"
        "        return source_anchor(cell.id) + cell.text\n",
        _embedded,
    ),
    _case(
        "configured content-preserving function returns matches only",
        "import re\n"
        "def preserve_text(text):\n"
        "    tokens = re.findall(r'[A-Za-z]+', text)\n"
        "    return tokens\n",
        _total_consumption,
    ),
    _negative(
        "explicit token extractor outside configured preserving boundary",
        "import re\n"
        "def extract_tokens(text):\n"
        "    return re.findall(r'[A-Za-z]+', text)\n",
        _total_consumption,
    ),
    _case(
        "path equality excludes records under exact-span contract",
        "def remaining_paragraphs(tables, paragraphs):\n"
        "    table_paths = {table.source.path for table in tables}\n"
        "    return [p for p in paragraphs if p.source.path not in table_paths]\n",
        _provenance_ownership,
    ),
    _negative(
        "span identity retained for same-file records",
        "def remaining_paragraphs(tables, paragraphs):\n"
        "    table_spans = {(t.source.path, t.source.start, t.source.end) "
        "for t in tables}\n"
        "    return [p for p in paragraphs if (p.source.path, p.source.start, "
        "p.source.end) not in table_spans]\n",
        _provenance_ownership,
    ),
    _case(
        "path-filter result returned directly",
        "def remaining_paragraphs(tables, paragraphs):\n"
        "    table_paths = {table.source.path for table in tables}\n"
        "    remaining = [p for p in paragraphs if p.source.path not in table_paths]\n"
        "    return remaining\n",
        _provenance_ownership,
    ),
    _negative(
        "unused path-filter result does not establish exclusion",
        "def remaining_paragraphs(tables, paragraphs):\n"
        "    table_paths = {table.source.path for table in tables}\n"
        "    discarded = [p for p in paragraphs if p.source.path not in table_paths]\n"
        "    return paragraphs\n",
        _provenance_ownership,
    ),
    _case(
        "all declared semantic roles co-located in presentation function",
        "def render_document(source):\n"
        "    layout = reconstruct_layout(source)\n"
        "    corrected = apply_content_correction(layout)\n"
        "    owned = decide_semantic_ownership(corrected)\n"
        "    return serialize_output(owned)\n",
        _presentation_boundary,
    ),
    _negative(
        "presentation-only serialization has no semantic boundary signal",
        "def render_document(source):\n    return serialize_output(source)\n",
        _presentation_boundary,
    ),
)


@pytest.mark.parametrize("case", _CASES, ids=lambda case: case.name)
def test_labeled_semantic_patchwork_corpus(case: _CorpusCase) -> None:
    """Synthetic labels exercise rule boundaries; they are not production precision data."""
    assert case.detector(case.source) is case.should_match
