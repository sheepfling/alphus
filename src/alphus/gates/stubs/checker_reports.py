"""Typed native checker evidence shared by fixture and declaration gates."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class PyrightPosition(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)
    line: Annotated[int, Field(ge=0)]


class PyrightRange(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)
    start: PyrightPosition


class PyrightDiagnostic(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)
    severity: Literal["error", "warning", "information"]
    file: str
    message: str
    range: PyrightRange
    rule: str | None = None


class PyrightSummary(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)
    files_analyzed: Annotated[int, Field(alias="filesAnalyzed", ge=0)]
    error_count: Annotated[int, Field(alias="errorCount", ge=0)]


class PyrightReport(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)
    summary: PyrightSummary
    diagnostics: Annotated[
        tuple[PyrightDiagnostic, ...], Field(alias="generalDiagnostics")
    ]


def pyright_output(output: str) -> str:
    """Validate the machine report and retain native diagnostic evidence."""
    report = PyrightReport.model_validate_json(output)
    if report.summary.files_analyzed != 1:
        raise ValueError(
            f"expected 1 analyzed file, got {report.summary.files_analyzed}"
        )
    lines: list[str] = []
    for diagnostic in report.diagnostics:
        if diagnostic.severity != "error":
            continue
        suffix = f" ({diagnostic.rule})" if diagnostic.rule else ""
        message = diagnostic.message.replace("\n", " ")
        lines.append(
            f"{diagnostic.file}:{diagnostic.range.start.line + 1}: error: {message}{suffix}"
        )
    if report.summary.error_count != len(lines):
        raise ValueError("Pyright errorCount disagrees with diagnostics")
    return "\n".join(lines)
