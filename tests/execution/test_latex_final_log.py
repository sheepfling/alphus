from __future__ import annotations

from pathlib import Path

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
