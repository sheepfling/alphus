"""Stable typed results shared by cyclomatic planning and consumers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from alphus.contracts.findings import Diagnostic, Severity


@dataclass(frozen=True, slots=True)
class CyclomaticFunctionMetric:
    """One native function record or one native gate diagnostic."""

    language: str
    backend: str
    backend_version: str
    native_rule: str
    count_method: str
    function_identity: str
    path: str
    line: int
    column: int | None
    value: int | None
    maximum: int
    severity: Severity
    violated: bool
    native_message: str | None = None


@dataclass(frozen=True, slots=True)
class CyclomaticBackendPlan:
    """Deterministic native invocation, selected scope, and capability limits."""

    language: str
    backend: str
    expected_version: str
    native_rule: str
    count_method: str
    maximum: int
    severity: Severity
    variant: str | None
    files: tuple[str, ...]
    command: tuple[str, ...] | None
    api_call: str | None
    numeric_inventory: bool
    unsupported_capabilities: tuple[str, ...]
    status: Literal["ready", "no_matching_files"]


@dataclass(frozen=True, slots=True)
class CyclomaticPlan:
    """Resolved, side-effect-free plan for all configured language backends."""

    metric: str
    maximum: int
    severity: Severity
    timeout_seconds: int
    lizard_manifest_max_bytes: int
    backends: tuple[CyclomaticBackendPlan, ...]


@dataclass(frozen=True, slots=True)
class CyclomaticBackendResult:
    """One backend's tool/version provenance and analyzed-file coverage."""

    language: str
    backend: str
    status: Literal["clean", "violations", "no_matching_files", "operational_failure"]
    expected_version: str
    actual_version: str | None
    native_rule: str
    count_method: str
    maximum: int
    severity: Severity
    variant: str | None
    selected_file_count: int
    analyzed_file_count: int
    record_scope: Literal["all_functions", "violations_only"]
    effective_options: tuple[tuple[str, str], ...]
    failure: str | None = None


@dataclass(frozen=True, slots=True)
class CyclomaticReport:
    """Serializable result preserving metric provenance and coverage limits."""

    metric: str
    outcome: Literal[
        "clean",
        "violations",
        "incomplete_coverage",
        "no_matching_files",
        "operational_failure",
    ]
    backends: tuple[CyclomaticBackendResult, ...]
    functions: tuple[CyclomaticFunctionMetric, ...]
    diagnostics: tuple[Diagnostic, ...]
