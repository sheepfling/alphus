"""Typed JSON boundaries for C++ artifact reports and policies."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
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
