"""Stable finding records shared by portable quality rules."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Literal, NamedTuple, Self, TypeAlias, TypeVar, get_args

from pydantic import BaseModel, ConfigDict

from alphus.contracts.rule_tags import NAMESPACE, Category, RuleTag, Scope

Severity: TypeAlias = Literal["error", "warning", "info"]
RemediationPriority: TypeAlias = Literal["low", "normal", "high", "urgent"]
WireValue: TypeAlias = str | int | None
WirePayload: TypeAlias = dict[str, WireValue]
REMEDIATION_PRIORITIES: frozenset[str] = frozenset(get_args(RemediationPriority))


class _WireModel(BaseModel):
    """Strict schema used only when data crosses the public wire boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class DiagnosticWire(_WireModel):
    """Stable public JSON shape for one normalized diagnostic."""

    source: str
    rule_id: str
    message: str
    severity: Severity
    path: str | None
    line: int | None
    priority: RemediationPriority | None


class FindingWire(_WireModel):
    """Stable public JSON shape for one direct rule finding."""

    rule_id: str
    path: str
    message: str
    line: int | None
    severity: Severity


@dataclass(frozen=True, slots=True)
class LineLengthMeasurement:
    """Measured width and selected limit for one line-length diagnostic."""

    codepoints: int
    limit_codepoints: int


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
            if tag.rule_id != self.rule_id and (
                self.source == NAMESPACE or RuleTag.is_alphus_id(self.rule_id)
            ):
                raise ValueError(
                    "diagnostic rule tag does not match its public rule ID"
                )
        elif self.source == NAMESPACE or RuleTag.is_alphus_id(self.rule_id):
            tag = RuleTag.parse(self.rule_id)
            object.__setattr__(self, "_rule_tag", tag)

    @property
    def tag(self) -> RuleTag | None:
        """Return an internal semantic identity when one is available."""
        return self._rule_tag

    def matches_category(self, category: Category) -> bool:
        """Match a finding by its typed category without parsing its wire ID."""
        return self._rule_tag is not None and self._rule_tag.category is category

    def to_wire(self) -> WirePayload:
        """Serialize only the established public diagnostic fields."""
        return DiagnosticWire(
            source=self.source,
            rule_id=self.rule_id,
            message=self.message,
            severity=self.severity,
            path=self.path,
            line=self.line,
            priority=self.priority,
        ).model_dump()


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


def deduplicate_semantic_diagnostics(
    diagnostics: Iterable[Diagnostic],
) -> tuple[Diagnostic, ...]:
    """Prefer native evidence when it exactly overlaps an Alphus semantic finding.

    The key includes the typed rule, source location, and message. Separate
    native rules keep their own IDs, and findings with different evidence remain
    distinct. The public diagnostic wire shape is unchanged.
    """
    items = tuple(diagnostics)
    semantic_keys = {
        (item.tag.rule_id, item.path, item.line, item.message)
        for item in items
        if item.tag is not None and item.source != NAMESPACE
    }
    severity_for_key: dict[tuple[str, str | None, int | None, str], Severity] = {}
    for item in items:
        if item.tag is None:
            continue
        key = (item.tag.rule_id, item.path, item.line, item.message)
        current = severity_for_key.get(key)
        if current is None or SEVERITY_ORDER[item.severity] > SEVERITY_ORDER[current]:
            severity_for_key[key] = item.severity

    output: list[Diagnostic] = []
    seen: set[tuple[object, ...]] = set()
    for item in items:
        if item.tag is None:
            output.append(item)
            continue
        semantic_key = (item.tag.rule_id, item.path, item.line, item.message)
        if semantic_key in semantic_keys:
            if item.source == NAMESPACE:
                continue
            identity = (
                *semantic_key,
                item.source,
                item.rule_id,
            )
            if identity in seen:
                continue
            seen.add(identity)
            severity = severity_for_key[semantic_key]
            output.append(
                item if item.severity == severity else replace(item, severity=severity)
            )
            continue
        identity = (
            *semantic_key,
            item.source,
            item.rule_id,
            item.severity,
            item.priority,
        )
        if identity not in seen:
            seen.add(identity)
            output.append(item)
    return tuple(output)


@dataclass(frozen=True, slots=True)
class FindingRollups:
    """Cross-language indexes over Alphus and mapped native diagnostics."""

    scopes: tuple[FindingRollup, ...] = ()
    categories: tuple[FindingRollup, ...] = ()
    complaints: tuple[FindingRollup, ...] = ()

    @classmethod
    def from_diagnostics(cls, diagnostics: Iterable[Diagnostic]) -> Self:
        by_scope: dict[Scope, list[Diagnostic]] = {}
        by_category: dict[Category, list[Diagnostic]] = {}
        by_complaint: dict[_ComplaintKey, list[Diagnostic]] = {}
        for diagnostic in deduplicate_semantic_diagnostics(diagnostics):
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
            wire_key: Callable[[_RollupKey], str],
        ) -> tuple[FindingRollup, ...]:
            return tuple(
                FindingRollup(
                    wire_key(key), len(items), SeverityCounts.from_diagnostics(items)
                )
                for key, items in sorted(
                    groups.items(), key=lambda item: wire_key(item[0])
                )
            )

        return cls(
            rows(by_scope, str),
            rows(by_category, str),
            rows(by_complaint, lambda key: f"{key.category}/{key.complaint}"),
        )


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
    line_length: LineLengthMeasurement | None = field(
        default=None, repr=False, compare=False
    )
    _rule_tag: RuleTag = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.severity not in SEVERITY_ORDER:
            raise ValueError(f"unsupported finding severity: {self.severity!r}")
        object.__setattr__(self, "_rule_tag", RuleTag.parse(str(self.rule_id)))

    @property
    def tag(self) -> RuleTag:
        """Return the validated semantic identity for internal consumers."""
        return self._rule_tag

    def to_wire(self) -> WirePayload:
        """Serialize only the established public finding fields."""
        return FindingWire(
            rule_id=self.rule_id,
            path=self.path,
            message=self.message,
            line=self.line,
            severity=self.severity,
        ).model_dump()

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
