"""Stable finding records shared by portable quality rules."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal, NamedTuple, TypeAlias

Severity: TypeAlias = Literal["error", "warning", "info"]

SEVERITY_ORDER: Mapping[Severity, int] = MappingProxyType(
    {"info": 0, "warning": 1, "error": 2}
)


def severity_meets_threshold(severity: Severity, threshold: Severity) -> bool:
    """Return whether a diagnostic is at or above the configured failure level."""
    return SEVERITY_ORDER[severity] >= SEVERITY_ORDER[threshold]


@dataclass(frozen=True, slots=True)
class SeverityCounts:
    """Triage counts for the three supported diagnostic levels."""

    error: int = 0
    warning: int = 0
    info: int = 0

    @classmethod
    def from_diagnostics(cls, diagnostics: Iterable[Diagnostic]) -> SeverityCounts:
        """Count diagnostic severities without classifying unstructured output."""
        errors = warnings = infos = 0
        for diagnostic in diagnostics:
            match diagnostic.severity:
                case "error":
                    errors += 1
                case "warning":
                    warnings += 1
                case "info":
                    infos += 1
        return cls(errors, warnings, infos)


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """A normalized, provenance-bearing finding used in aggregate reports."""

    source: str
    rule_id: str
    message: str
    severity: Severity = "error"
    path: str | None = None
    line: int | None = None

    def __post_init__(self) -> None:
        if self.severity not in SEVERITY_ORDER:
            raise ValueError(f"unsupported diagnostic severity: {self.severity!r}")


class SourceFinding(NamedTuple):
    """One source-level location and explanation before repository context is added."""

    line: int
    message: str


@dataclass(frozen=True, slots=True)
class Finding:
    """One actionable result from a quality rule."""

    rule_id: str
    path: str
    message: str
    line: int | None = None
    severity: Severity = "error"

    def __post_init__(self) -> None:
        if self.severity not in SEVERITY_ORDER:
            raise ValueError(f"unsupported finding severity: {self.severity!r}")

    def as_diagnostic(self, *, source: str = "alphus") -> Diagnostic:
        """Add checker provenance while retaining the public finding fields."""
        return Diagnostic(
            source=source,
            rule_id=self.rule_id,
            message=self.message,
            severity=self.severity,
            path=self.path,
            line=self.line,
        )
