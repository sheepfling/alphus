"""Typed JSON boundaries for C++ artifact reports and policies."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal, NotRequired, TypedDict, cast

from pydantic import BaseModel, ConfigDict, Field

from alphus.support.data_access import JsonValue
from alphus.support.native_artifacts import ArtifactKind

SectionStatus = Literal["skipped", "unavailable", "error", "measured"]


@dataclass(frozen=True, slots=True)
class SectionMetrics:
    """Internal measurement; JSON rows are constructed only at the boundary."""

    status: SectionStatus
    debug_bytes: int | None = None
    text_bytes: int | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class SectionInventory:
    """Named objdump section sizes in bytes."""

    sizes: Mapping[str, int]

    @property
    def debug_bytes(self) -> int:
        return sum(
            size
            for name, size in self.sizes.items()
            if name.startswith((".debug", ".zdebug"))
            or name in {".gnu_debugdata", ".stab", ".stabstr"}
        )

    @property
    def text_bytes(self) -> int:
        return sum(
            size for name, size in self.sizes.items() if name.startswith(".text")
        )


class ArtifactScanOptions(BaseModel):
    """Validated scan settings at the JSON and CLI boundary."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    debug_dominance_min_bytes: Annotated[int, Field(ge=0)] = 64 * 1024 * 1024
    max_review_examples: Annotated[int, Field(ge=0)] = 8
    section_timeout_seconds: Annotated[float, Field(gt=0, allow_inf_nan=False)] = 30.0


@dataclass(slots=True)
class ScannedArtifact:
    path: str
    kind: ArtifactKind
    bytes: int
    sections: SectionMetrics | None = None

    def to_wire(self) -> ArtifactRow:
        row: ArtifactRow = {"path": self.path, "kind": self.kind, "bytes": self.bytes}
        if self.sections is not None:
            row["section_status"] = self.sections.status
            row["debug_bytes"] = self.sections.debug_bytes
            row["text_bytes"] = self.sections.text_bytes
            if self.sections.error is not None:
                row["section_error"] = self.sections.error
        return row


@dataclass(slots=True)
class KindCount:
    count: int = 0
    bytes: int = 0

    def to_wire(self) -> KindTotals:
        return {"count": self.count, "bytes": self.bytes}


@dataclass(slots=True)
class ArtifactSummary:
    count: int
    bytes: int
    executable_count: int
    executable_paths: list[str]
    executable_bytes: int
    static_library_count: int
    static_library_bytes: int
    measured_debug_bytes: int
    section_measured_count: int
    section_unmeasured_count: int
    by_kind: dict[ArtifactKind, KindCount]

    def to_wire(self) -> ArtifactTotals:
        return {
            "count": self.count,
            "bytes": self.bytes,
            "executable_count": self.executable_count,
            "executable_paths": self.executable_paths,
            "executable_bytes": self.executable_bytes,
            "static_library_count": self.static_library_count,
            "static_library_bytes": self.static_library_bytes,
            "measured_debug_bytes": self.measured_debug_bytes,
            "section_measured_count": self.section_measured_count,
            "section_unmeasured_count": self.section_unmeasured_count,
            "by_kind": {kind: count.to_wire() for kind, count in self.by_kind.items()},
        }


@dataclass(slots=True)
class ArtifactReviewSignal:
    code: str
    count: int
    total_debug_bytes: int
    examples: list[str]

    def to_wire(self) -> DebugSignal:
        return {
            "code": self.code,
            "count": self.count,
            "total_debug_bytes": self.total_debug_bytes,
            "examples": self.examples,
        }


@dataclass(slots=True)
class ArtifactInventory:
    root: Path
    include: list[str]
    exclude: list[str]
    include_unix_executables: bool
    section_tool: str | None
    artifacts: list[ScannedArtifact]
    totals: ArtifactSummary
    review_signals: list[ArtifactReviewSignal]

    def to_wire(self) -> ArtifactScan:
        return {
            "schema": 1,
            "root": str(self.root),
            "include": self.include,
            "exclude": self.exclude,
            "include_unix_executables": self.include_unix_executables,
            "section_tool": self.section_tool,
            "artifacts": [artifact.to_wire() for artifact in self.artifacts],
            "totals": self.totals.to_wire(),
            "review_signals": [signal.to_wire() for signal in self.review_signals],
        }


class ArtifactRow(TypedDict):
    """Serialized JSON row; scanning uses immutable semantic measurements."""

    path: str
    kind: ArtifactKind
    bytes: int
    section_status: NotRequired[str]
    section_error: NotRequired[str]
    debug_bytes: NotRequired[int | None]
    text_bytes: NotRequired[int | None]


class KindTotals(TypedDict):
    count: int
    bytes: int


class ArtifactTotals(TypedDict):
    count: int
    bytes: int
    executable_count: int
    executable_paths: list[str]
    executable_bytes: int
    static_library_count: int
    static_library_bytes: int
    measured_debug_bytes: int
    section_measured_count: int
    section_unmeasured_count: int
    by_kind: dict[str, KindTotals]


class DebugSignal(TypedDict):
    code: str
    count: int
    total_debug_bytes: int
    examples: list[str]


class LimitFinding(TypedDict):
    code: str
    observed: int | None
    limit: int
    path: NotRequired[str]


class ArtifactComparison(TypedDict):
    new_artifacts: list[str]
    removed_artifacts: list[str]
    total_executable_growth_bytes: int


class ArtifactGate(TypedDict):
    passed: bool
    policy: str
    findings: list[LimitFinding]
    comparison: ArtifactComparison | None


class ArtifactScan(TypedDict):
    schema: int
    root: str
    include: list[str]
    exclude: list[str]
    include_unix_executables: bool
    section_tool: str | None
    artifacts: list[ArtifactRow]
    totals: ArtifactTotals
    review_signals: list[DebugSignal]
    run_id: NotRequired[str | None]
    manifest_sha256: NotRequired[str]
    gate: NotRequired[ArtifactGate]


class ArtifactBaselineTotals(TypedDict):
    executable_bytes: int


class ArtifactBaseline(TypedDict):
    include: list[str]
    exclude: list[str]
    include_unix_executables: bool
    artifacts: list[ArtifactRow]
    totals: ArtifactBaselineTotals


class ArtifactPolicy(TypedDict):
    schema: int
    name: str
    limits: dict[str, int]
    include: list[str]
    exclude: list[str]
    scan: NotRequired[ArtifactScanOptions]


class ArtifactRowDocument(BaseModel):
    """Validate one serialized artifact row."""

    model_config = ConfigDict(extra="forbid", strict=True)

    path: str
    kind: ArtifactKind
    bytes: Annotated[int, Field(ge=0)]
    section_status: SectionStatus | None = None
    section_error: str | None = None
    debug_bytes: Annotated[int, Field(ge=0)] | None = None
    text_bytes: Annotated[int, Field(ge=0)] | None = None


class ArtifactBaselineTotalsDocument(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    executable_bytes: Annotated[int, Field(ge=0)]


class ArtifactBaselineDocument(BaseModel):
    """Validate an on-disk baseline before comparison."""

    model_config = ConfigDict(extra="ignore", strict=True)

    schema_version: Annotated[Literal[1], Field(alias="schema")]
    include: list[str]
    exclude: list[str]
    include_unix_executables: bool
    artifacts: list[ArtifactRowDocument]
    totals: ArtifactBaselineTotalsDocument


def parse_artifact_baseline(value: JsonValue) -> ArtifactBaseline:
    """Read only the baseline fields needed by the policy evaluator."""
    document = ArtifactBaselineDocument.model_validate(value)
    return cast(
        ArtifactBaseline, document.model_dump(mode="json", exclude={"schema_version"})
    )


class KindTotalsDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    count: Annotated[int, Field(ge=0)]
    bytes: Annotated[int, Field(ge=0)]


class ArtifactTotalsDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    count: Annotated[int, Field(ge=0)]
    bytes: Annotated[int, Field(ge=0)]
    executable_count: Annotated[int, Field(ge=0)]
    executable_paths: list[str]
    executable_bytes: Annotated[int, Field(ge=0)]
    static_library_count: Annotated[int, Field(ge=0)]
    static_library_bytes: Annotated[int, Field(ge=0)]
    measured_debug_bytes: Annotated[int, Field(ge=0)]
    section_measured_count: Annotated[int, Field(ge=0)]
    section_unmeasured_count: Annotated[int, Field(ge=0)]
    by_kind: dict[ArtifactKind, KindTotalsDocument]


class DebugSignalDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    code: str
    count: Annotated[int, Field(ge=0)]
    total_debug_bytes: Annotated[int, Field(ge=0)]
    examples: list[str]


class LimitFindingDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    code: str
    observed: int | None
    limit: Annotated[int, Field(ge=0)]
    path: str | None = None


class ArtifactComparisonDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    new_artifacts: list[str]
    removed_artifacts: list[str]
    total_executable_growth_bytes: int


class ArtifactGateDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    passed: bool
    policy: str
    findings: list[LimitFindingDocument]
    comparison: ArtifactComparisonDocument | None


class ArtifactScanDocument(BaseModel):
    """Validate every on-disk C++ artifact report before emission."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Annotated[Literal[1], Field(alias="schema")]
    root: str
    include: list[str]
    exclude: list[str]
    include_unix_executables: bool
    section_tool: str | None
    artifacts: list[ArtifactRowDocument]
    totals: ArtifactTotalsDocument
    review_signals: list[DebugSignalDocument]
    run_id: str | None = None
    manifest_sha256: str | None = None
    gate: ArtifactGateDocument | None = None


def validate_artifact_report(report: ArtifactScan) -> ArtifactScan:
    """Serialize through the report schema without changing its JSON shape."""
    document = ArtifactScanDocument.model_validate(report)
    return cast(
        ArtifactScan,
        document.model_dump(mode="json", by_alias=True, exclude_unset=True),
    )
