"""Stable finding records shared by portable quality rules."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal, NamedTuple, TypeAlias

from alphus.contracts.rule_tags import RuleTag

Severity: TypeAlias = Literal["error", "warning", "info"]
RemediationPriority: TypeAlias = Literal["low", "normal", "high", "urgent"]

SEVERITY_ORDER: Mapping[Severity, int] = MappingProxyType(
    {"info": 0, "warning": 100, "error": 200}
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
    priority: RemediationPriority | None = None

    def __post_init__(self) -> None:
        if self.severity not in SEVERITY_ORDER:
            raise ValueError(f"unsupported diagnostic severity: {self.severity!r}")
        if self.priority is not None and self.priority not in {
            "low",
            "normal",
            "high",
            "urgent",
        }:
            raise ValueError(f"unsupported remediation priority: {self.priority!r}")
        if self.source == "alphus" or self.rule_id.partition("/")[0] == "alphus":
            RuleTag.parse(self.rule_id)


@dataclass(frozen=True, slots=True)
class FindingRollup:
    """Severity totals for one semantic tag dimension."""

    key: str
    count: int
    severity_counts: SeverityCounts


@dataclass(frozen=True, slots=True)
class FindingRollups:
    """Cross-language indexes over normalized Alphus diagnostics."""

    scopes: tuple[FindingRollup, ...] = ()
    categories: tuple[FindingRollup, ...] = ()
    complaints: tuple[FindingRollup, ...] = ()

    @classmethod
    def from_diagnostics(cls, diagnostics: Iterable[Diagnostic]) -> FindingRollups:
        by_scope: dict[str, list[Diagnostic]] = {}
        by_category: dict[str, list[Diagnostic]] = {}
        by_complaint: dict[str, list[Diagnostic]] = {}
        for diagnostic in diagnostics:
            tag = RuleTag.parse(diagnostic.rule_id)
            by_scope.setdefault(tag.scope, []).append(diagnostic)
            by_category.setdefault(tag.category, []).append(diagnostic)
            by_complaint.setdefault(f"{tag.category}/{tag.complaint}", []).append(
                diagnostic
            )

        def rows(groups: Mapping[str, Sequence[Diagnostic]]) -> tuple[FindingRollup, ...]:
            return tuple(
                FindingRollup(key, len(items), SeverityCounts.from_diagnostics(items))
                for key, items in sorted(groups.items())
            )

        return cls(rows(by_scope), rows(by_category), rows(by_complaint))


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
        RuleTag.parse(str(self.rule_id))

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
