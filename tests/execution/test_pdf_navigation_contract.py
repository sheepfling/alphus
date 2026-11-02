from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("pypdf")

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from scripts.check_pdf_navigation import validate_navigation


def _pdf(path: Path, outline_page: int, *, include_heading: bool = True) -> None:
    writer = PdfWriter()
    for _ in range(13):
        writer.add_blank_page(width=100, height=100)
    if include_heading:
        page = writer.pages[12]
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
        content.set_data(b"BT /F1 12 Tf 20 50 Td (Overview) Tj ET")
        page[NameObject("/Contents")] = writer._add_object(content)
    writer.add_outline_item("Overview", outline_page)
    writer.write(path)


def _contract(path: Path, page: int = 13) -> None:
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
    _pdf(pdf, 1)
    _contract(contract)

    failures, unknown = validate_navigation(pdf, contract)
    assert unknown == []
    assert "targets physical page 2" in failures[0]
    assert "expects 13" in failures[0]


def test_non_text_destination_is_unknown_not_called_blank(tmp_path: Path) -> None:
    pdf = tmp_path / "report.pdf"
    contract = tmp_path / "targets.json"
    _pdf(pdf, 1, include_heading=False)
    _contract(contract, page=2)

    failures, unknown = validate_navigation(pdf, contract)
    assert failures == []
    assert "no extractable text" in unknown[0]
