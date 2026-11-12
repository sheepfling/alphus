"""Typed native checker evidence shared by fixture and declaration gates."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    NonNegativeInt,
    PositiveInt,
    TypeAdapter,
    model_validator,
)


class PyrightPosition(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)
    line: NonNegativeInt


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
    files_analyzed: Annotated[NonNegativeInt, Field(alias="filesAnalyzed")]
    error_count: Annotated[NonNegativeInt, Field(alias="errorCount")]


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


class NativeDiagnostic(BaseModel):
    """Normalized native diagnostic with one-based source lines."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    path: str
    line: PositiveInt
    severity: Literal["error", "warning", "information"]
    message: str
    rule: str | None = None


class FixtureCaseResult(BaseModel):
    """One checker invocation and the fixture contract it was evaluated against."""

    model_config = ConfigDict(strict=True, frozen=True)
    checker: str
    fixture: str
    analyzed_fixture: str
    expect_errors: bool
    passed: bool
    command: tuple[str, ...] = ()
    returncode: int | None = None
    elapsed_seconds: float = 0.0
    stdout: str = ""
    stderr: str = ""
    diagnostics: str = ""
    native_diagnostics: tuple[NativeDiagnostic, ...] = ()
    issues: tuple[str, ...] = ()
    guidance: str | None = None


class FixtureReport(BaseModel):
    """Versioned fixture-suite output for human and machine consumers."""

    model_config = ConfigDict(strict=True, frozen=True)
    schema_version: Literal[1] = 1
    kind: Literal["stub-typing-fixtures"] = "stub-typing-fixtures"
    passed: bool
    checkers: tuple[str, ...] = ()
    cases: tuple[FixtureCaseResult, ...] = ()
    errors: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_outcome(self) -> Self:
        """Reject successful reports without complete, consistent checker evidence."""
        if len(set(self.checkers)) != len(self.checkers):
            raise ValueError("fixture report contains duplicate checkers")
        if any(name not in {"mypy", "pyright", "ty"} for name in self.checkers):
            raise ValueError("fixture report contains unknown checkers")
        keys = [(case.checker, case.expect_errors) for case in self.cases]
        if len(set(keys)) != len(keys):
            raise ValueError("fixture report contains duplicate checker cases")
        if any(case.checker not in self.checkers for case in self.cases):
            raise ValueError("fixture cases do not match selected checkers")
        for case in self.cases:
            if case.passed and (
                case.issues
                or case.stderr.strip()
                or not case.command
                or case.returncode != int(case.expect_errors)
                or not case.fixture
                or not case.analyzed_fixture
            ):
                raise ValueError("passed fixture case contradicts its process evidence")
            has_errors = any(
                item.severity == "error" for item in case.native_diagnostics
            )
            if case.passed and has_errors != case.expect_errors:
                raise ValueError("passed fixture case contradicts diagnostic evidence")
        if self.passed:
            expected = {
                (name, negative) for name in self.checkers for negative in (False, True)
            }
            if (
                not expected
                or set(keys) != expected
                or self.errors
                or not all(case.passed for case in self.cases)
            ):
                raise ValueError(
                    "successful fixture report requires complete error-free checker coverage"
                )
            for negative in (False, True):
                if (
                    len(
                        {
                            case.fixture
                            for case in self.cases
                            if case.expect_errors == negative
                        }
                    )
                    != 1
                ):
                    raise ValueError("checker cases disagree on fixture identity")
        return self


class MypyDiagnostic(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)
    file: str
    line: PositiveInt
    severity: Literal["error", "warning", "note"]
    message: str
    code: str | None = None


class GitlabPosition(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)
    line: PositiveInt


class GitlabPositions(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)
    begin: GitlabPosition


class GitlabLocation(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)
    path: str
    positions: GitlabPositions


class TyDiagnostic(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)
    check_name: str
    description: str
    severity: Literal["info", "minor", "major", "critical", "blocker"]
    location: GitlabLocation


TY_DIAGNOSTICS = TypeAdapter(tuple[TyDiagnostic, ...])


def parse_checker_diagnostics(
    checker: str, output: str
) -> tuple[NativeDiagnostic, ...]:
    """Validate Pyright JSON, Mypy JSON Lines, or Ty GitLab JSON diagnostics."""
    if checker == "pyright":
        report = PyrightReport.model_validate_json(output)
        errors = sum(item.severity == "error" for item in report.diagnostics)
        if report.summary.error_count != errors:
            raise ValueError("Pyright errorCount disagrees with diagnostics")
        return tuple(
            NativeDiagnostic(
                path=item.file,
                line=item.range.start.line + 1,
                severity=item.severity,
                message=item.message,
                rule=item.rule,
            )
            for item in report.diagnostics
        )
    if checker == "mypy":
        mypy_items = tuple(
            MypyDiagnostic.model_validate_json(line)
            for line in output.splitlines()
            if line.strip()
        )
        return tuple(
            NativeDiagnostic(
                path=item.file,
                line=item.line,
                severity="information" if item.severity == "note" else item.severity,
                message=item.message,
                rule=item.code,
            )
            for item in mypy_items
        )
    if checker == "ty":
        ty_items = TY_DIAGNOSTICS.validate_json(output)
        return tuple(
            NativeDiagnostic(
                path=item.location.path,
                line=item.location.positions.begin.line,
                severity="information"
                if item.severity == "info"
                else ("warning" if item.severity == "minor" else "error"),
                message=item.description,
                rule=item.check_name,
            )
            for item in ty_items
        )
    raise ValueError(f"unknown checker: {checker}")
