"""Validate configured outline destinations against an independent page contract."""

from __future__ import annotations

import argparse
import importlib
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Protocol, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator


class _SectionContract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    outline_title: Annotated[str, Field(min_length=1)]
    heading_text: Annotated[str, Field(min_length=1)]
    expected_physical_page: Annotated[int, Field(ge=1)]


class _NavigationContract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    source_evidence: Annotated[str, Field(min_length=1)]
    sections: Annotated[list[_SectionContract], Field(min_length=1)]

    @field_validator("source_evidence")
    @classmethod
    def validate_source_evidence(cls, value: str) -> str:
        if not value.strip():
            raise ValueError(
                "source_evidence must identify an independent source/build map"
            )
        return value


class _Destination(Protocol):
    title: str


class _Page(Protocol):
    def extract_text(self) -> str | None: ...


class _Reader(Protocol):
    outline: object
    pages: Sequence[_Page]

    def get_destination_page_number(self, destination: object) -> int | None: ...


class _ReaderFactory(Protocol):
    def __call__(self, pdf_path: Path, strict: bool = True) -> _Reader: ...


class _PdfApi(Protocol):
    PdfReader: _ReaderFactory


def _contracts(path: Path) -> _NavigationContract:
    return _NavigationContract.model_validate_json(path.read_text(encoding="utf-8"))


def _pdf_api() -> _PdfApi:
    try:
        return cast(_PdfApi, importlib.import_module("pypdf"))
    except ImportError as error:
        raise RuntimeError(
            "install the optional PDF extra: pip install 'alphus[pdf]'"
        ) from error


def _flatten_outline(items: object) -> list[object]:
    result: list[object] = []
    match items:
        case [*_]:
            for item in cast(list[object], items):
                result.extend(_flatten_outline(item))
        case None:
            pass
        case _:
            result.append(items)
    return result


def validate_navigation(
    pdf_path: Path, contract_path: Path
) -> tuple[list[str], list[str]]:
    """Return definite mismatches and unknown evidence separately."""
    contract = _contracts(contract_path)
    api = _pdf_api()
    try:
        reader = api.PdfReader(pdf_path, strict=True)
        outline = _flatten_outline(reader.outline)
    except Exception as error:
        raise RuntimeError(f"cannot parse PDF outline/pages: {error}") from error
    mismatches: list[str] = []
    unknown: list[str] = []
    for section in contract.sections:
        title = section.outline_title
        candidates = [
            item for item in outline if cast(_Destination, item).title == title
        ]
        if len(candidates) != 1:
            mismatches.append(
                f"outline title {title!r} resolves to {len(candidates)} entries; expected one"
            )
            continue
        try:
            actual_page_index = reader.get_destination_page_number(candidates[0])
        except (IndexError, KeyError, TypeError, ValueError):
            actual_page_index = None
        if actual_page_index is None:
            mismatches.append(
                f"outline title {title!r} has no resolvable page destination"
            )
            continue
        actual_page = actual_page_index + 1
        expected_page = section.expected_physical_page
        if actual_page != expected_page:
            mismatches.append(
                f"outline title {title!r} targets physical page {actual_page}; "
                f"independent contract expects {expected_page}"
            )
            continue
        try:
            text = reader.pages[actual_page_index].extract_text()
        except (
            IndexError,
            KeyError,
            OSError,
            TypeError,
            ValueError,
        ) as error:
            unknown.append(
                f"cannot extract text from physical page {actual_page}: {error}"
            )
            continue
        if not text or not text.strip():
            unknown.append(
                f"physical page {actual_page} has no extractable text; "
                "visual/image/vector content is unknown"
            )
            continue
        normalized_text = " ".join(text.split()).casefold()
        normalized_heading = " ".join(section.heading_text.split()).casefold()
        if normalized_heading not in normalized_text:
            mismatches.append(
                f"physical page {actual_page} does not contain configured heading "
                f"{section.heading_text!r}"
            )
    return mismatches, unknown


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("contract", type=Path)
    args = parser.parse_args(argv)
    try:
        mismatches, unknown = validate_navigation(args.pdf, args.contract)
    except (OSError, TypeError, ValueError, RuntimeError) as error:
        print(f"UNKNOWN: {error}", file=sys.stderr)
        return 2
    for issue in mismatches:
        print(f"FAIL: {issue}", file=sys.stderr)
    for note in unknown:
        print(f"UNKNOWN: {note}", file=sys.stderr)
    if mismatches:
        return 1
    if unknown:
        return 2
    print(
        "Configured outline destinations match source-declared page/heading contracts."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
