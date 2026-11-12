from collections.abc import Sequence
from typing import Protocol


class _Source(Protocol):
    """Expose the location needed by the ownership example."""

    path: str


class _Record(Protocol):
    """Expose a source location for the path-filter example."""

    source: _Source


def remaining_paragraphs(
    tables: Sequence[_Record], paragraphs: Sequence[_Record]
) -> list[_Record]:
    table_paths = {table.source.path for table in tables}
    return [p for p in paragraphs if p.source.path not in table_paths]


def render_document(source: object) -> object:
    layout = reconstruct_layout(source)
    corrected = apply_content_correction(layout)
    owned = decide_semantic_ownership(corrected)
    return serialize_output(owned)


def reconstruct_layout(value: object) -> object:
    return value


def apply_content_correction(value: object) -> object:
    return value


def decide_semantic_ownership(value: object) -> object:
    return value


def serialize_output(value: object) -> object:
    return value
