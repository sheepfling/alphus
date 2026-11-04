"""Validate configured outline destinations against an independent page contract."""

from __future__ import annotations

import argparse
import importlib
import math
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Annotated, Protocol, TypeAlias, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator


class _SectionContract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    outline_title: Annotated[str, Field(min_length=1)]
    heading_text: Annotated[str, Field(min_length=1)]
    expected_physical_page: Annotated[int, Field(ge=1)]


class _ContentsLinkContract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    contents_physical_page: Annotated[int, Field(ge=1)]
    contents_label: Annotated[str, Field(min_length=1)]
    target_outline_title: Annotated[str, Field(min_length=1)]
    target_heading_text: Annotated[str, Field(min_length=1)]
    expected_target_physical_page: Annotated[int, Field(ge=1)]
    expected_annotation_rectangle: tuple[float, float, float, float]


class _NavigationContract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    source_evidence: Annotated[str, Field(min_length=1)]
    sections: Annotated[list[_SectionContract], Field(min_length=1)]
    contents_links: tuple[_ContentsLinkContract, ...] = ()

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

    @property
    def annotations(self) -> Sequence[object] | None: ...


class _PdfDictionary(Protocol):
    def get(self, key: str, default: object = None) -> object: ...


class _IndirectObject(Protocol):
    def get_object(self) -> _PdfDictionary: ...


_OutlineItem: TypeAlias = _Destination | Sequence["_OutlineItem"]
_PdfDestination: TypeAlias = (
    str | _Destination | _IndirectObject | list["_PdfDestination"]
)


class _Reader(Protocol):
    outline: _OutlineItem
    pages: Sequence[_Page]

    def get_destination_page_number(
        self, destination: _PdfDestination
    ) -> int | None: ...

    def get_page_number(self, page: _Page) -> int | None: ...

    @property
    def named_destinations(self) -> dict[str, _Destination]: ...


class _ReaderFactory(Protocol):
    def __call__(self, pdf_path: Path, strict: bool = True) -> _Reader: ...


class _PdfApi(Protocol):
    PdfReader: _ReaderFactory


def _contracts(path: Path) -> _NavigationContract:
    return _NavigationContract.model_validate_json(path.read_text(encoding="utf-8"))


def _text_value(value: str | None) -> str | None:
    return value if isinstance(value, str) else None


def _pdf_api() -> _PdfApi:
    try:
        return cast(_PdfApi, importlib.import_module("pypdf"))
    except ImportError as error:
        raise RuntimeError(
            "install the optional PDF extra: pip install 'alphus[pdf]'"
        ) from error


def _flatten_outline(items: _OutlineItem) -> list[_Destination]:
    result: list[_Destination] = []
    if isinstance(items, Sequence):
        for item in items:
            result.extend(_flatten_outline(item))
    else:
        result.append(items)
    return result


def _page_for_destination(reader: _Reader, destination: _PdfDestination) -> int | None:
    getter = cast(Callable[[], object] | None, getattr(destination, "get_object", None))
    if getter is not None:
        try:
            destination = cast(_PdfDestination, getter())
        except Exception:  # noqa: BLE001 - malformed references are unresolved
            return None
    normalized: _PdfDestination = destination
    named = reader.named_destinations.get(str(normalized).lstrip("/"))
    if named is not None:
        try:
            return reader.get_destination_page_number(named)
        except (AttributeError, IndexError, KeyError, TypeError, ValueError):
            return None
    if isinstance(normalized, list) and normalized:
        try:
            page = cast(_IndirectObject, normalized[0]).get_object()
            return reader.get_page_number(cast(_Page, page))
        except (AttributeError, IndexError, KeyError, TypeError, ValueError):
            return None
    try:
        return reader.get_destination_page_number(normalized)
    except (AttributeError, IndexError, KeyError, TypeError, ValueError):
        return None


def _link_action_target(
    annotation: _PdfDictionary,
) -> tuple[str, _PdfDestination | None]:
    destination = annotation.get("/Dest")
    action_value = annotation.get("/A")
    if destination is not None:
        if action_value is not None:
            return "malformed conflicting destination and action", None
        return "goto", cast(_PdfDestination, destination)
    if action_value is None:
        return "missing", None
    try:
        getter = getattr(action_value, "get_object", None)
        action = cast(
            _PdfDictionary,
            getter() if callable(getter) else action_value,
        )
        kind = str(action.get("/S"))
    except Exception as error:  # noqa: BLE001 - malformed action is unknown evidence
        return f"malformed ({error})", None
    if kind == "/GoTo":
        return "goto", cast(_PdfDestination, action.get("/D"))
    if kind == "/URI":
        uri = _text_value(cast(str | None, action.get("/URI")))
        if uri is None or not uri:
            return "malformed /URI", None
        return "external URI", None
    return f"unsupported {kind}", None


def _link_rect(annotation: _PdfDictionary) -> tuple[float, ...] | None:
    rectangle = annotation.get("/Rect")
    if rectangle is None:
        return None
    try:
        values = cast(Sequence[int | float], rectangle)
        coordinates_list: list[float] = []
        for value in values:
            coordinates_list.append(float(value))
        coordinates = tuple(coordinates_list)
        return (
            coordinates if all(math.isfinite(value) for value in coordinates) else None
        )
    except (TypeError, ValueError, OverflowError):
        return None


def _link_target(annotation: _PdfDictionary) -> _PdfDestination | None:
    kind, target = _link_action_target(annotation)
    return target if kind == "goto" else None


def _destination_key(destination: _PdfDestination | None) -> str:
    if destination is None:
        return "missing"
    if isinstance(destination, str):
        return f"named:{str(destination).lstrip('/')}"
    return str(destination)


def _verify_all_destinations(
    reader: _Reader, outline: Sequence[_Destination]
) -> tuple[list[str], list[str]]:
    """Resolve every supported outline/internal-link destination without semantics."""
    unresolved: dict[str, tuple[str, list[str]]] = {}
    unknown: list[str] = []

    def record(key: str, description: str, reference: str) -> None:
        if key not in unresolved:
            unresolved[key] = (description, [])
        unresolved[key][1].append(reference)

    page_count = len(reader.pages)
    for item in outline:
        reference = f"outline {item.title!r}"
        try:
            page_index = _page_for_destination(reader, item)
        except Exception as error:  # noqa: BLE001 - parser failures remain visible
            unknown.append(f"cannot resolve {reference}: {error}")
            continue
        if page_index is None or not 0 <= page_index < page_count:
            record(
                f"outline:{item.title}",
                f"outline destination {item.title!r}",
                reference,
            )

    try:
        named_destinations = reader.named_destinations
    except Exception as error:  # noqa: BLE001 - parser failures remain visible
        named_destinations = {}
        unknown.append(f"cannot enumerate named destinations: {error}")
    for name, destination in named_destinations.items():
        reference = f"named destination {name!r}"
        try:
            page_index = _page_for_destination(reader, destination)
        except Exception as error:  # noqa: BLE001 - parser failures remain visible
            unknown.append(f"cannot resolve {reference}: {error}")
            continue
        if page_index is None or not 0 <= page_index < page_count:
            record(_destination_key(name), f"named destination {name!r}", reference)

    for page_number, page in enumerate(reader.pages, start=1):
        try:
            annotations = page.annotations
        except Exception as error:  # noqa: BLE001 - malformed page remains unknown
            unknown.append(
                f"cannot inspect annotations on physical page {page_number}: {error}"
            )
            continue
        if annotations is None:
            continue
        for link_number, item in enumerate(annotations, start=1):
            try:
                annotation = cast(_IndirectObject, item).get_object()
                if str(annotation.get("/Subtype")) != "/Link":
                    continue
                kind, destination = _link_action_target(annotation)
            except Exception as error:  # noqa: BLE001 - malformed annotation is unknown
                unknown.append(
                    f"cannot inspect physical page {page_number} link {link_number}: {error}"
                )
                continue
            reference = f"physical page {page_number} link {link_number}"
            if kind == "external URI":
                continue
            if kind != "goto":
                unknown.append(
                    f"{reference} has {kind} action; destination was not executed"
                )
                continue
            if destination is None:
                record("link:missing", "internal GoTo without a destination", reference)
                continue
            key = _destination_key(destination)
            try:
                page_index = _page_for_destination(reader, destination)
            except Exception as error:  # noqa: BLE001 - parser failures remain visible
                unknown.append(f"cannot resolve {reference} destination: {error}")
                continue
            if page_index is None or not 0 <= page_index < page_count:
                record(
                    key,
                    f"internal GoTo destination {_destination_key(destination)!r}",
                    reference,
                )

    mismatches = [
        f"{description} is unresolvable or out of range (referenced by {', '.join(references)})"
        for description, references in unresolved.values()
    ]
    return mismatches, unknown


def _verify_contents_link(
    reader: _Reader,
    outline: Sequence[_Destination],
    link: _ContentsLinkContract,
) -> tuple[list[str], list[str]]:
    label = link.contents_label
    source_page = link.contents_physical_page
    try:
        page = reader.pages[source_page - 1]
        text = page.extract_text()
    except (IndexError, KeyError, OSError, TypeError, ValueError) as error:
        return [], [f"cannot inspect Contents page {source_page}: {error}"]
    if not text or not text.strip():
        return [], [f"Contents page {source_page} has no extractable text"]
    if " ".join(label.split()).casefold() not in " ".join(text.split()).casefold():
        return [
            f"Contents label {label!r} is absent from physical page {source_page}"
        ], []
    annotations = page.annotations
    if annotations is None:
        return [f"Contents page {source_page} has no link annotations"], []
    expected_rect = link.expected_annotation_rectangle
    matching: list[_PdfDictionary] = []
    for item in annotations:
        annotation = cast(_IndirectObject, item).get_object()
        if str(annotation.get("/Subtype")) != "/Link":
            continue
        actual_rect = _link_rect(annotation)
        if (
            actual_rect is not None
            and len(actual_rect) == 4
            and all(
                math.isclose(actual, expected, rel_tol=0.0, abs_tol=0.1)
                for actual, expected in zip(actual_rect, expected_rect, strict=True)
            )
        ):
            matching.append(annotation)
    if len(matching) != 1:
        return [
            (
                "Contents label "
                f"{label!r} rectangle resolves to {len(matching)} link annotations; "
                "expected one"
            )
        ], []
    target = _link_target(matching[0])
    if target is None:
        return [f"Contents link {label!r} has no supported GoTo destination"], []
    page_index = _page_for_destination(reader, target)
    expected_page = link.expected_target_physical_page
    if page_index is None:
        return [f"Contents link {label!r} has an unresolvable destination"], []
    if page_index + 1 != expected_page:
        return [
            (
                f"Contents link {label!r} targets physical page {page_index + 1}; "
                f"expected {expected_page}"
            )
        ], []
    title = link.target_outline_title
    destinations = [item for item in outline if item.title == title]
    if len(destinations) != 1:
        return [
            f"outline title {title!r} resolves to {len(destinations)} entries; expected one"
        ], []
    outline_page = _page_for_destination(reader, destinations[0])
    if outline_page != page_index:
        return [
            f"Contents link {label!r} and outline title {title!r} resolve to different pages"
        ], []
    try:
        target_text = reader.pages[page_index].extract_text()
    except (IndexError, KeyError, OSError, TypeError, ValueError) as error:
        return [], [f"cannot extract target page {page_index + 1} text: {error}"]
    if not target_text or not target_text.strip():
        return [], [f"target page {page_index + 1} has no extractable heading text"]
    normalized_target_text = " ".join(target_text.split()).casefold()
    normalized_heading = " ".join(link.target_heading_text.split()).casefold()
    if normalized_heading not in normalized_target_text:
        return [
            (
                f"Contents destination page {page_index + 1} does not contain configured heading "
                f"{link.target_heading_text!r}"
            )
        ], []
    return [], []


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
    destination_mismatches, destination_unknown = _verify_all_destinations(
        reader, outline
    )
    mismatches.extend(destination_mismatches)
    unknown.extend(destination_unknown)
    for section in contract.sections:
        title = section.outline_title
        candidates = [item for item in outline if item.title == title]
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
    for link in contract.contents_links:
        link_mismatches, link_unknown = _verify_contents_link(reader, outline, link)
        mismatches.extend(link_mismatches)
        unknown.extend(link_unknown)
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
        "Supported internal destinations resolve; configured outline and Contents "
        "targets match their page/heading contracts."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
