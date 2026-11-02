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
