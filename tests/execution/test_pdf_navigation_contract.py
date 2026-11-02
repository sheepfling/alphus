from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("pypdf")

from pypdf import PdfWriter
from pypdf.generic import (
    ArrayObject,
    DecodedStreamObject,
    DictionaryObject,
    FloatObject,
    NameObject,
)

from scripts.check_pdf_navigation import validate_navigation


def _add_text(writer: PdfWriter, page_index: int, text: str, y: int) -> None:
    page = writer.pages[page_index]
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    font_reference = writer._add_object(font)
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_reference})}
    )
    content = DecodedStreamObject()
    content.set_data(f"BT /F1 12 Tf 20 {y} Td ({text}) Tj ET".encode())
    page[NameObject("/Contents")] = writer._add_object(content)


def _pdf(
    path: Path,
    outline_page: int,
    *,
    include_heading: bool = True,
    contents_link_page: int = 12,
    contents_rect: tuple[int, int, int, int] = (15, 75, 80, 95),
) -> None:
    writer = PdfWriter()
    for _ in range(13):
        writer.add_blank_page(width=100, height=100)
    if include_heading:
        _add_text(writer, 12, "Overview", 50)
    _add_text(writer, 0, "Overview", 85)
    writer.add_outline_item("Overview", outline_page)
    writer.add_annotation(
        0,
        {
            "/Type": "/Annot",
            "/Subtype": "/Link",
            "/Rect": [FloatObject(value) for value in contents_rect],
            "/Border": [0, 0, 0],
            "/Dest": ArrayObject(
                [
                    writer.pages[contents_link_page].indirect_reference,
                    NameObject("/Fit"),
                ]
            ),
        },
    )
    writer.write(path)


def _contract(path: Path, page: int = 13, target_page: int = 13) -> None:
    path.write_text(
        json.dumps(
            {
                "source_evidence": "build/independent-source-map.json",
                "sections": [
                    {
                        "outline_title": "Overview",
                        "heading_text": "Overview",
                        "expected_physical_page": page,
                    }
                ],
                "contents_links": [
                    {
                        "contents_physical_page": 1,
                        "contents_label": "Overview",
                        "target_outline_title": "Overview",
                        "target_heading_text": "Overview",
                        "expected_target_physical_page": target_page,
                        "expected_annotation_rectangle": [15.0, 75.0, 80.0, 95.0],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def _destination_contract(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "source_evidence": "build/independent-source-map.json",
                "sections": [
                    {
                        "outline_title": "Overview",
                        "heading_text": "Overview",
                        "expected_physical_page": 2,
                    }
                ],
                "contents_links": [],
            }
        ),
        encoding="utf-8",
    )


def _pdf_with_unconfigured_links(
    path: Path,
    destination_name: str,
    *,
    include_named_destination: bool = False,
    link_count: int = 1,
    action_kind: str = "/GoTo",
    direct_destination: bool = False,
) -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.add_blank_page(width=100, height=100)
    _add_text(writer, 1, "Overview", 50)
    writer.add_outline_item("Overview", 1)
    if include_named_destination:
        writer.add_named_destination(destination_name, 1)
    for _ in range(link_count):
        if direct_destination:
            writer.add_annotation(
                0,
                {
                    "/Type": "/Annot",
                    "/Subtype": "/Link",
                    "/Rect": [10, 10, 20, 20],
                    "/Dest": NameObject(f"/{destination_name}"),
                },
            )
        elif action_kind == "/GoTo":
            writer.add_annotation(
                0,
                {
                    "/Type": "/Annot",
                    "/Subtype": "/Link",
                    "/Rect": [10, 10, 20, 20],
                    "/A": {
                        "/S": "/GoTo",
                        "/D": NameObject(f"/{destination_name}"),
                    },
                },
            )
        else:
            action = {"/S": action_kind}
            if action_kind == "/URI":
                action["/URI"] = "https://example.org/section"
            writer.add_annotation(
                0,
                {
                    "/Type": "/Annot",
                    "/Subtype": "/Link",
                    "/Rect": [10, 10, 20, 20],
                    "/A": action,
                },
            )
    writer.write(path)


def test_correct_outline_destination_and_heading_match_independent_contract(
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "report.pdf"
    contract = tmp_path / "targets.json"
    _pdf(pdf, 12)
    _contract(contract)

    assert validate_navigation(pdf, contract) == ([], [])


def test_wrong_outline_page_fails_even_when_expected_manifest_is_consistent(
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "report.pdf"
    contract = tmp_path / "targets.json"
    _pdf(pdf, 1, contents_link_page=1)
    _contract(contract)

    failures, unknown = validate_navigation(pdf, contract)
    assert unknown == []
    assert "targets physical page 2" in failures[0]
    assert "expects 13" in failures[0]


def test_non_text_destination_is_unknown_not_called_blank(tmp_path: Path) -> None:
    pdf = tmp_path / "report.pdf"
    contract = tmp_path / "targets.json"
    _pdf(pdf, 1, include_heading=False, contents_link_page=1)
    _contract(contract, page=2, target_page=2)

    failures, unknown = validate_navigation(pdf, contract)
    assert failures == []
    assert "no extractable text" in unknown[0]


def test_contents_link_annotation_must_match_independent_page_and_rectangle(
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "report.pdf"
    contract = tmp_path / "targets.json"
    _pdf(pdf, 12)
    _contract(contract)

    assert validate_navigation(pdf, contract) == ([], [])

    _pdf(pdf, 12, contents_link_page=1)
    failures, unknown = validate_navigation(pdf, contract)
    assert unknown == []
    assert any(
        "Contents link 'Overview' targets physical page 2" in item for item in failures
    )

    _pdf(pdf, 12, contents_rect=(15, 75, 70, 95))
    failures, unknown = validate_navigation(pdf, contract)
    assert unknown == []
    assert any("rectangle resolves to 0 link annotations" in item for item in failures)


@pytest.mark.parametrize("direct_destination", [True, False])
def test_unconfigured_named_goto_links_resolve_direct_and_action_forms(
    tmp_path: Path, direct_destination: bool
) -> None:
    pdf = tmp_path / "report.pdf"
    contract = tmp_path / "targets.json"
    _pdf_with_unconfigured_links(
        pdf,
        "OverviewTarget",
        include_named_destination=True,
        link_count=2,
        direct_destination=direct_destination,
    )
    _destination_contract(contract)

    assert validate_navigation(pdf, contract) == ([], [])


def test_unresolved_named_goto_is_reported_once_with_all_references(
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "report.pdf"
    contract = tmp_path / "targets.json"
    _pdf_with_unconfigured_links(
        pdf, "MissingTarget", link_count=2, direct_destination=True
    )
    _destination_contract(contract)

    failures, unknown = validate_navigation(pdf, contract)
    assert unknown == []
    assert len(failures) == 1
    assert "unresolvable or out of range" in failures[0]
    assert "physical page 1 link 1" in failures[0]
    assert "physical page 1 link 2" in failures[0]


def test_unsupported_link_action_is_unknown_and_not_executed(
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "report.pdf"
    contract = tmp_path / "targets.json"
    _pdf_with_unconfigured_links(
        pdf,
        "unused",
        action_kind="/Launch",
    )
    _destination_contract(contract)

    failures, unknown = validate_navigation(pdf, contract)
    assert failures == []
    assert any("unsupported /Launch" in item for item in unknown)
    assert any("not executed" in item for item in unknown)


def test_external_uri_is_classified_separately_from_internal_goto(
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "report.pdf"
    contract = tmp_path / "targets.json"
    _pdf_with_unconfigured_links(pdf, "unused", action_kind="/URI")
    _destination_contract(contract)

    assert validate_navigation(pdf, contract) == ([], [])
