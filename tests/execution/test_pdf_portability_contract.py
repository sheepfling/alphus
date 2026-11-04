from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest

pytest.importorskip("pypdf")

from pypdf import PdfWriter
from pypdf.generic import ArrayObject, DictionaryObject, NameObject, TextStringObject

from scripts.check_pdf_portability import validate_portability


def _pdf(path: Path, actions: Sequence[tuple[str, str | None]]) -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    for kind, target in actions:
        action = DictionaryObject({NameObject("/S"): NameObject(kind)})
        if target is not None:
            key = "/URI" if kind == "/URI" else "/F"
            action[NameObject(key)] = TextStringObject(target)
        writer.add_annotation(
            0,
            {
                "/Type": "/Annot",
                "/Subtype": "/Link",
                "/Rect": [0, 0, 10, 10],
                "/A": action,
            },
        )
    writer.write(path)


def _pdf_with_remote_file_spec(path: Path, key: str, target: str) -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    file_spec = DictionaryObject({NameObject(key): TextStringObject(target)})
    action = DictionaryObject(
        {
            NameObject("/S"): NameObject("/GoToR"),
            NameObject("/F"): writer._add_object(file_spec),
        }
    )
    writer.add_annotation(
        0,
        {
            "/Type": "/Annot",
            "/Subtype": "/Link",
            "/Rect": [0, 0, 10, 10],
            "/A": action,
        },
    )
    writer.write(path)


def _contract(path: Path, **fields: object) -> None:
    path.write_text(json.dumps(fields), encoding="utf-8")


def test_self_contained_contract_allows_web_and_mailto_but_rejects_local_actions(
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "report.pdf"
    contract = tmp_path / "delivery.json"
    _pdf(
        pdf,
        [
            ("/URI", "https://example.org/report"),
            ("/URI", "mailto:editor@example.org"),
            ("/URI", "#overview"),
            ("/URI", "?download=1#overview"),
            ("/URI", "?download=1"),
            ("/URI", "javascript:#payload"),
            ("/URI", "ftp:#external"),
            ("/URI", "file:///Users/example/source.tex"),
            ("/GoToR", "appendix.pdf"),
            ("/Launch", "open-me.sh"),
        ],
    )
    _contract(contract, mode="self_contained")

    failures, unknown = validate_portability(pdf, contract)
    assert unknown == []
    assert len(failures) == 7
    assert any("local filesystem" in item for item in failures)
    assert sum("relative companion is unavailable" in item for item in failures) == 2
    assert any("URI scheme 'javascript'" in item for item in failures)
    assert any("URI scheme 'ftp'" in item for item in failures)
    assert any("remote-document GoTo" in item for item in failures)
    assert any("launch/file actions" in item for item in failures)


def test_bundle_allows_existing_relative_companion_and_rejects_escape_or_missing(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "appendix.pdf").write_bytes(b"companion")
    pdf = tmp_path / "report.pdf"
    contract = tmp_path / "delivery.json"
    _pdf(
        pdf,
        [
            ("/URI", "appendix.pdf"),
            ("/URI", "../outside.pdf"),
            ("/URI", "missing.pdf"),
        ],
    )
    _contract(contract, mode="bundle", bundle_root=str(bundle))

    failures, unknown = validate_portability(pdf, contract)
    assert unknown == []
    assert len(failures) == 2
    assert any("escapes the declared bundle root" in item for item in failures)
    assert any("companion is missing" in item for item in failures)


def test_bundle_accepts_dictionary_remote_file_spec_with_unicode_filename(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "appendix-Δ.pdf").write_bytes(b"companion")
    pdf = tmp_path / "report.pdf"
    contract = tmp_path / "delivery.json"
    _pdf_with_remote_file_spec(pdf, "/UF", "appendix-Δ.pdf")
    _contract(contract, mode="bundle", bundle_root=str(bundle))

    assert validate_portability(pdf, contract) == ([], [])


@pytest.mark.parametrize(
    ("key", "target", "expected"),
    [
        ("/F", "../outside.pdf", "escapes the declared bundle root"),
        ("/UF", "/private/secret.pdf", "absolute local target"),
    ],
)
def test_bundle_rejects_dictionary_remote_file_spec_escape_and_absolute_targets(
    tmp_path: Path, key: str, target: str, expected: str
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    pdf = tmp_path / "report.pdf"
    contract = tmp_path / "delivery.json"
    _pdf_with_remote_file_spec(pdf, key, target)
    _contract(contract, mode="bundle", bundle_root=str(bundle))

    failures, unknown = validate_portability(pdf, contract)
    assert unknown == []
    assert len(failures) == 1
    assert expected in failures[0]


def test_unknown_action_is_reported_without_execution(tmp_path: Path) -> None:
    pdf = tmp_path / "report.pdf"
    contract = tmp_path / "delivery.json"
    _pdf(pdf, [("/JavaScript", "app.alert('not run')")])
    _contract(contract, mode="self_contained")

    failures, unknown = validate_portability(pdf, contract)
    assert failures == []
    assert len(unknown) == 1
    assert "not executed or fetched" in unknown[0]


def test_bundle_contract_requires_root_and_rejects_unknown_fields(
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "report.pdf"
    contract = tmp_path / "delivery.json"
    _pdf(pdf, [])
    _contract(contract, mode="bundle")
    with pytest.raises(ValueError, match="requires bundle_root"):
        validate_portability(pdf, contract)

    _contract(contract, mode="self_contained", follow_links=True)
    with pytest.raises(ValueError):
        validate_portability(pdf, contract)


def _pdf_with_next_action(
    path: Path, *, next_kind: str | None, primary_kind: str = "/GoTo"
) -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    next_action = DictionaryObject(
        {
            NameObject("/S"): NameObject("/Launch"),
            NameObject("/F"): TextStringObject("open-me.sh"),
        }
    )
    if next_kind == "dictionary":
        next_value = next_action
    elif next_kind == "array":
        next_value = ArrayObject([next_action])
    elif next_kind == "indirect":
        next_value = writer._add_object(next_action)
    elif next_kind == "cyclic":
        cyclic_action = DictionaryObject({NameObject("/S"): NameObject("/GoTo")})
        cyclic_reference = writer._add_object(cyclic_action)
        cyclic_action[NameObject("/Next")] = cyclic_reference
        next_value = cyclic_reference
    elif next_kind is None:
        next_value = None
    else:
        raise AssertionError(f"unsupported fixture kind: {next_kind}")

    action = DictionaryObject({NameObject("/S"): NameObject(primary_kind)})
    if next_value is not None:
        action[NameObject("/Next")] = next_value
    if primary_kind == "/GoTo":
        action[NameObject("/D")] = ArrayObject(
            [writer.pages[0].indirect_reference, NameObject("/Fit")]
        )
    elif primary_kind == "/Launch":
        action[NameObject("/F")] = TextStringObject("primary-launch.sh")
    writer.add_annotation(
        0,
        {
            "/Type": "/Annot",
            "/Subtype": "/Link",
            "/Rect": [0, 0, 10, 10],
            "/A": action,
        },
    )
    writer.write(path)


@pytest.mark.parametrize("next_kind", ["dictionary", "array", "indirect", "cyclic"])
def test_permitted_action_with_any_next_form_is_unknown_not_certified(
    tmp_path: Path, next_kind: str
) -> None:
    pdf = tmp_path / "report.pdf"
    contract = tmp_path / "delivery.json"
    _pdf_with_next_action(pdf, next_kind=next_kind)
    _contract(contract, mode="self_contained")

    failures, unknown = validate_portability(pdf, contract)

    assert failures == []
    assert len(unknown) == 1
    assert "chained /Next actions are unsupported" in unknown[0]


def test_primary_launch_remains_failure_when_it_has_a_next_action(
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "report.pdf"
    contract = tmp_path / "delivery.json"
    _pdf_with_next_action(pdf, next_kind="dictionary", primary_kind="/Launch")
    _contract(contract, mode="self_contained")

    failures, unknown = validate_portability(pdf, contract)

    assert any(
        "launch/file actions violate delivery policy" in item for item in failures
    )
    assert any("chained /Next actions are unsupported" in item for item in unknown)


def test_unchained_allowed_goto_remains_fully_supported(tmp_path: Path) -> None:
    pdf = tmp_path / "report.pdf"
    contract = tmp_path / "delivery.json"
    _pdf_with_next_action(pdf, next_kind=None)
    _contract(contract, mode="self_contained")

    failures, unknown = validate_portability(pdf, contract)

    assert failures == []
    assert unknown == []
