"""Stable finding records shared by portable quality rules."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal, NamedTuple, Self, TypeAlias, TypeVar, get_args

from alphus.contracts.rule_tags import NAMESPACE, Category, RuleTag, Scope

Severity: TypeAlias = Literal["error", "warning", "info"]
RemediationPriority: TypeAlias = Literal["low", "normal", "high", "urgent"]
REMEDIATION_PRIORITIES: frozenset[str] = frozenset(get_args(RemediationPriority))

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
    def from_diagnostics(cls, diagnostics: Iterable[Diagnostic]) -> Self:
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
    _rule_tag: RuleTag | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.severity not in SEVERITY_ORDER:
            raise ValueError(f"unsupported diagnostic severity: {self.severity!r}")
        if self.priority is not None and self.priority not in REMEDIATION_PRIORITIES:
            raise ValueError(f"unsupported remediation priority: {self.priority!r}")
        tag = self._rule_tag
        if tag is not None:
            if tag.rule_id != self.rule_id:
                raise ValueError(
                    "diagnostic rule tag does not match its public rule ID"
                )
        elif self.source == NAMESPACE or RuleTag.is_alphus_id(self.rule_id):
            tag = RuleTag.parse(self.rule_id)
            object.__setattr__(self, "_rule_tag", tag)

    @property
    def tag(self) -> RuleTag | None:
        """Return the parsed Alphus identity, or ``None`` for a native tool ID."""
        return self._rule_tag

    def matches_category(self, category: Category) -> bool:
        """Match a finding by its typed category without parsing its wire ID."""
        return self._rule_tag is not None and self._rule_tag.category is category

    def to_wire(self) -> dict[str, object]:
        """Serialize only the established public diagnostic fields."""
        return {
            "source": self.source,
            "rule_id": self.rule_id,
            "message": self.message,
            "severity": self.severity,
            "path": self.path,
            "line": self.line,
            "priority": self.priority,
        }


@dataclass(frozen=True, slots=True)
class FindingRollup:
    """Severity totals for one semantic tag dimension."""

    key: str
    count: int
    severity_counts: SeverityCounts


class _ComplaintKey(NamedTuple):
    category: Category
    complaint: str


_RollupKey = TypeVar("_RollupKey", Scope, Category, _ComplaintKey)


@dataclass(frozen=True, slots=True)
class FindingRollups:
    """Cross-language indexes over normalized Alphus diagnostics."""

    scopes: tuple[FindingRollup, ...] = ()
    categories: tuple[FindingRollup, ...] = ()
    complaints: tuple[FindingRollup, ...] = ()

    @classmethod
    def from_diagnostics(cls, diagnostics: Iterable[Diagnostic]) -> Self:
        by_scope: dict[Scope, list[Diagnostic]] = {}
        by_category: dict[Category, list[Diagnostic]] = {}
        by_complaint: dict[_ComplaintKey, list[Diagnostic]] = {}
        for diagnostic in diagnostics:
            tag = diagnostic.tag
            if tag is None:
                continue
            by_scope.setdefault(tag.scope, []).append(diagnostic)
            by_category.setdefault(tag.category, []).append(diagnostic)
            by_complaint.setdefault(
                _ComplaintKey(tag.category, tag.complaint), []
            ).append(diagnostic)

        def rows(
            groups: Mapping[_RollupKey, Sequence[Diagnostic]],
        ) -> tuple[FindingRollup, ...]:
            def wire_key(key: _RollupKey) -> str:
                if isinstance(key, _ComplaintKey):
                    return f"{key.category}/{key.complaint}"
                return str(key)

            return tuple(
                FindingRollup(
                    wire_key(key), len(items), SeverityCounts.from_diagnostics(items)
                )
                for key, items in sorted(
                    groups.items(), key=lambda item: wire_key(item[0])
                )
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
    _rule_tag: RuleTag = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.severity not in SEVERITY_ORDER:
            raise ValueError(f"unsupported finding severity: {self.severity!r}")
        object.__setattr__(self, "_rule_tag", RuleTag.parse(str(self.rule_id)))

    @property
    def tag(self) -> RuleTag:
        """Return the validated semantic identity for internal consumers."""
        return self._rule_tag

    def to_wire(self) -> dict[str, object]:
        """Serialize only the established public finding fields."""
        return {
            "rule_id": self.rule_id,
            "path": self.path,
            "message": self.message,
            "line": self.line,
            "severity": self.severity,
        }

    def as_diagnostic(self, *, source: str = "alphus") -> Diagnostic:
        """Add checker provenance while retaining the public finding fields."""
        return Diagnostic(
            source=source,
            rule_id=self.rule_id,
            message=self.message,
            severity=self.severity,
            path=self.path,
            line=self.line,
            _rule_tag=self.tag,
        )
