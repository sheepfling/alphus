"""Typed JSON boundaries for C++ artifact reports and policies."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from typing import Literal, NotRequired, TypedDict

from alphus.support.data_access import (
    JsonValue,
    require_json_array,
    require_json_boolean,
    require_json_integer,
    require_json_object,
    require_json_string,
)
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


@dataclass(slots=True)
class ArtifactScanOptions:
    """Review thresholds and subprocess budget for one artifact scan."""

    debug_dominance_min_bytes: int = 64 * 1024 * 1024
    max_review_examples: int = 8
    section_timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        if self.debug_dominance_min_bytes < 0:
            raise ValueError("debug_dominance_min_bytes must be nonnegative")
        if self.max_review_examples < 0:
            raise ValueError("max_review_examples must be nonnegative")
        if (
            not isfinite(self.section_timeout_seconds)
            or self.section_timeout_seconds <= 0
        ):
            raise ValueError("section_timeout_seconds must be positive")


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


def _artifact_row(value: JsonValue) -> ArtifactRow:
    source = require_json_object(value, "artifact entry must be a JSON object")
    row: ArtifactRow = {
        "path": require_json_string(
            source.get("path"), "artifact path must be a string"
        ),
        "kind": ArtifactKind(
            require_json_string(source.get("kind"), "artifact kind must be a string")
        ),
        "bytes": require_json_integer(
            source.get("bytes"), "artifact bytes must be an integer"
        ),
    }
    for field in ("section_status", "section_error"):
        value = source.get(field)
        if value is not None:
            row[field] = require_json_string(value, f"{field} must be a string")
    for field in ("debug_bytes", "text_bytes"):
        value = source.get(field)
        if field in source:
            row[field] = (
                None
                if value is None
                else require_json_integer(value, f"{field} must be an integer")
            )
    return row


def parse_artifact_baseline(value: JsonValue) -> ArtifactBaseline:
    baseline = require_json_object(value, "baseline must be a JSON object")
    if baseline.get("schema") != 1:
        raise ValueError("baseline must be a schema 1 artifact report")
    include = [
        require_json_string(item, "baseline include entries must be strings")
        for item in require_json_array(
            baseline.get("include"), "baseline requires include patterns"
        )
    ]
    exclude = [
        require_json_string(item, "baseline exclude entries must be strings")
        for item in require_json_array(
            baseline.get("exclude"), "baseline requires exclude patterns"
        )
    ]
    artifacts = [
        _artifact_row(item)
        for item in require_json_array(
            baseline.get("artifacts"), "baseline requires artifacts"
        )
    ]
    totals = require_json_object(baseline.get("totals"), "baseline requires totals")
    executable_bytes = require_json_integer(
        totals.get("executable_bytes"), "baseline executable_bytes must be an integer"
    )
    include_unix_executables = require_json_boolean(
        baseline.get("include_unix_executables"),
        "baseline include_unix_executables must be a boolean",
    )
    return {
        "include": include,
        "exclude": exclude,
        "include_unix_executables": include_unix_executables,
        "artifacts": artifacts,
        "totals": {"executable_bytes": executable_bytes},
    }
