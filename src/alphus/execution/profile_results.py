"""Structured outcomes shared by profile execution and reporting."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal

from alphus.contracts.findings import (
    Diagnostic,
    FindingRollups,
    Severity,
    SeverityCounts,
)
from alphus.policy.intents import FailureKind


class StepStatus(StrEnum):
    """Closed set of orchestration step outcomes."""

    DISABLED = "disabled"
    PASSED = "passed"
    FAILED = "failed"
    NOT_APPLICABLE = "not_applicable"
    UNSUPPORTED = "unsupported"


class IntentStatus(StrEnum):
    """Closed set of language-specific intent outcomes."""

    DISABLED = "disabled"
    UNSUPPORTED = "unsupported"
    NOT_SELECTED = "not_selected"
    NOT_APPLICABLE = "not_applicable"
    PASSED = "passed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class OrchestrationStepResult:
    """Machine-readable outcome for one configured profile step."""

    name: str
    status: StepStatus
    exit_code: int | None
    diagnostics: tuple[str, ...] = ()
    findings: tuple[Diagnostic, ...] = ()
    stdout: str = ""
    stderr: str = ""
    severity_counts: SeverityCounts = field(default_factory=SeverityCounts)
    rollout: Literal["mainline", "provisional"] = "mainline"
    # opaque-boundary: Native rule reports retain backend-specific JSON fields.
    report: Mapping[str, object] | None = None


@dataclass(frozen=True, slots=True)
class IntentExecutionResult:
    """One language mapping's outcome with a pointer to native raw evidence."""

    rule_id: str
    language: str
    backend: str
    native_rule: str
    mapping: str
    status: IntentStatus
    failure_kind: FailureKind | None = None
    required: bool = True
    severity: Severity | None = None
    failure_threshold: Severity = "error"
    threshold: int | None = None
    step: str | None = None
    evidence_step: str | None = None
    exit_code: int | None = None


@dataclass(frozen=True, slots=True)
class OrchestrationResult:
    """Machine-readable summary for a configured quality profile."""

    profile: str
    passed: int
    failed: int
    exit_code: int
    steps: tuple[OrchestrationStepResult, ...]
    failure_threshold: Severity = "error"
    severity_counts: SeverityCounts = field(default_factory=SeverityCounts)
    not_applicable: int = 0
    finding_rollups: FindingRollups = field(default_factory=FindingRollups)
    intent_bindings: tuple[IntentExecutionResult, ...] = ()
    unsupported: int = 0
    disabled: int = 0
