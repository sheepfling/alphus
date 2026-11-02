from __future__ import annotations

from pathlib import Path

import pytest

from scripts.check_latex_final_log import validate_final_log


def test_accepts_expected_pdf_output_without_known_reference_warnings(
    tmp_path: Path,
) -> None:
    log = tmp_path / "report.log"
    pdf = tmp_path / "report.pdf"
    log.write_text("Output written on report.pdf (14 pages, 123456 bytes).\n")
    pdf.write_bytes(b"pdf artifact")

    assert validate_final_log(log, pdf) == []


def test_reports_missing_output_mismatch_and_unresolved_references(
    tmp_path: Path,
) -> None:
    log = tmp_path / "report.log"
    pdf = tmp_path / "report.pdf"
    pdf.write_bytes(b"pdf artifact")
    log.write_text(
        "Output written on other.pdf (14 pages, 123456 bytes).\n"
        "LaTeX Warning: Reference `overview' on page 2 undefined.\n"
    )

    issues = validate_final_log(log, pdf)
    assert len(issues) == 1
    assert "expected 'report.pdf'" in issues[0]

    log.write_text(
        "Output written on report.pdf (14 pages, 123456 bytes).\n"
        "There were undefined references.\n"
    )
    assert any("unresolved LaTeX" in issue for issue in validate_final_log(log, pdf))


def test_reports_duplicate_labels_and_hyperref_destinations(tmp_path: Path) -> None:
    log = tmp_path / "report.log"
    pdf = tmp_path / "report.pdf"
    pdf.write_bytes(b"pdf artifact")
    log.write_text(
        "Output written on report.pdf (14 pages, 123456 bytes).\n"
        "LaTeX Warning: Label `overview' multiply defined.\n"
        "pdfTeX warning (ext4): destination with the same identifier "
        "(name{page.1}) has been already used, duplicate ignored\n"
    )

    issues = validate_final_log(log, pdf)
    assert len(issues) == 2
    assert all("unresolved LaTeX" in issue for issue in issues)


@pytest.mark.parametrize(
    "warning",
    [
        (
            "pdfTeX warning (ext4): destination with the same identifier\n"
            "(name{section.2}) has been already used,\n"
            "duplicate ignored\n"
        ),
        (
            "pdfTeX warning (ext4): destination with the same identifier\n"
            "(name{page.1}) has been\n"
            "already used, duplicate ignored\n"
        ),
        (
            "pdfTeX warning (ext4): destination with the same identifier\n"
            "(name{figure.4}) has been already used, duplicate\n"
            "ignored\n"
        ),
        (
            "pdfTeX warning (ext4): destination with the same identifier\n"
            "(name{chapter.generated.with.a.very.long.destination.identifi\n"
            "er.2026}) has been already used, duplicate ignored\n"
        ),
    ],
)
def test_reports_wrapped_pdftex_duplicate_destination_warning(
    tmp_path: Path, warning: str
) -> None:
    log = tmp_path / "report.log"
    pdf = tmp_path / "report.pdf"
    pdf.write_bytes(b"pdf artifact")
    log.write_text("Output written on report.pdf (14 pages, 123456 bytes).\n" + warning)

    issues = validate_final_log(log, pdf)
    assert len(issues) == 1
    assert "unresolved LaTeX" in issues[0]


def test_ignores_unrelated_duplicate_ignored_text(tmp_path: Path) -> None:
    log = tmp_path / "report.log"
    pdf = tmp_path / "report.pdf"
    pdf.write_bytes(b"pdf artifact")
    log.write_text(
        "Output written on report.pdf (14 pages, 123456 bytes).\n"
        "A destination with the same identifier is described in this note;\n"
        "another unrelated check said duplicate ignored.\n"
    )

    assert validate_final_log(log, pdf) == []


def test_ignores_duplicate_destination_phrase_without_pdftex_warning_prefix(
    tmp_path: Path,
) -> None:
    log = tmp_path / "report.log"
    pdf = tmp_path / "report.pdf"
    pdf.write_bytes(b"pdf artifact")
    log.write_text(
        "Output written on report.pdf (14 pages, 123456 bytes).\n"
        "Other tool: destination with the same identifier (name{section.2})\n"
        "has been already used, duplicate ignored\n"
    )

    assert validate_final_log(log, pdf) == []


def test_reports_308_character_destination_wrapped_at_79_columns(
    tmp_path: Path,
) -> None:
    log = tmp_path / "report.log"
    pdf = tmp_path / "report.pdf"
    pdf.write_bytes(b"pdf artifact")
    identifier = "d" * 308
    warning = (
        "pdfTeX warning (ext4): destination with the same identifier "
        f"(name{{{identifier}}}) has been already used, duplicate ignored"
    )
    wrapped = "\n".join(
        warning[index : index + 79] for index in range(0, len(warning), 79)
    )
    log.write_text(
        "Output written on report.pdf (14 pages, 123456 bytes).\n" + wrapped + "\n"
    )

    issues = validate_final_log(log, pdf)
    assert len(issues) == 1
    assert "pdfTeX duplicate destination" in issues[0]


def test_reports_destination_identifier_beyond_bounded_scan_limit(
    tmp_path: Path,
) -> None:
    log = tmp_path / "report.log"
    pdf = tmp_path / "report.pdf"
    pdf.write_bytes(b"pdf artifact")
    identifier = "d" * 4097
    log.write_text(
        "Output written on report.pdf (14 pages, 123456 bytes).\n"
        "pdfTeX warning (ext4): destination with the same identifier "
        f"(name{{{identifier}}}) has been already used, duplicate ignored\n"
    )

    issues = validate_final_log(log, pdf)
    assert len(issues) == 1
    assert "4096-character scan bound" in issues[0]
    assert "manual review required" in issues[0]


def test_missing_pdf_or_log_fails_closed(tmp_path: Path) -> None:
    log = tmp_path / "report.log"
    log.write_text("Output written on report.pdf (1 page, 100 bytes).\n")
    assert (
        "expected PDF output is missing"
        in validate_final_log(log, tmp_path / "report.pdf")[0]
    )

    assert (
        "cannot read final LaTeX log"
        in validate_final_log(tmp_path / "missing.log", tmp_path / "report.pdf")[0]
    )
