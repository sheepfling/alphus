"""Versioned, validated messages for private quality worker processes."""

from __future__ import annotations

from typing import Annotated, Literal, Self, TypeAlias

from pydantic import Field, TypeAdapter, model_validator

from alphus.contracts.findings import (
    Diagnostic,
    Finding,
    RemediationPriority,
    Severity,
)
from alphus.gates.source.cyclomatic_complexity import (
    CyclomaticBackendPlan,
    CyclomaticBackendResult,
    CyclomaticFunctionMetric,
)
from alphus.policy.base import QualityRuleName, StrictModel


class WorkerRequest(StrictModel):
    """One fully specified unit of work against a pinned policy snapshot."""

    version: Literal[1] = 1
    kind: Literal["rule", "cyclomatic_backend"]
    root: str
    config_path: str
    config_fingerprint: str
    rule: QualityRuleName | None = None
    verbose: bool = False
    language: str | None = None
    expected_plan: CyclomaticBackendPlan | None = None

    @model_validator(mode="after")
    def validate_variant(self) -> WorkerRequest:
        if self.kind == "rule":
            if self.rule is None or self.language is not None or self.expected_plan:
                raise ValueError("rule worker request has invalid fields")
        elif self.language is None or self.expected_plan is None or self.rule:
            raise ValueError("backend worker request has invalid fields")
        return self


class DiagnosticPayload(StrictModel):
    """Public diagnostic fields without internal rule tag state."""

    source: str
    rule_id: str
    message: str
    severity: Severity
    path: str | None
    line: int | None
    priority: RemediationPriority | None

    @classmethod
    def from_diagnostic(cls, diagnostic: Diagnostic) -> Self:
        return cls.model_validate(diagnostic.to_wire())

    def to_diagnostic(self) -> Diagnostic:
        return Diagnostic(**self.model_dump())


class FindingPayload(StrictModel):
    """Public finding fields without internal rule tag state."""

    rule_id: str
    path: str
    message: str
    line: int | None
    severity: Severity

    @classmethod
    def from_finding(cls, finding: Finding) -> Self:
        return cls.model_validate(finding.to_wire())

    def to_finding(self) -> Finding:
        return Finding(**self.model_dump())


class RuleWorkerResponse(StrictModel):
    """One normalized built-in rule result."""

    version: Literal[1] = 1
    kind: Literal["rule"] = "rule"
    findings: tuple[DiagnosticPayload, ...]
    execution_failure: str | None
    exit_code: int
    stdout: str
    stderr: str
    # opaque-boundary: Native rule reports have heterogeneous validated JSON fields.
    report: dict[str, object] | None


class BackendWorkerResponse(StrictModel):
    """One native cyclomatic backend result with its records."""

    version: Literal[1] = 1
    kind: Literal["cyclomatic_backend"] = "cyclomatic_backend"
    result: CyclomaticBackendResult
    records: tuple[CyclomaticFunctionMetric, ...]
    findings: tuple[FindingPayload, ...]


class ErrorWorkerResponse(StrictModel):
    """A rejected request or worker execution failure."""

    version: Literal[1] = 1
    kind: Literal["error"] = "error"
    error: str


WorkerResponse: TypeAlias = Annotated[
    RuleWorkerResponse | BackendWorkerResponse | ErrorWorkerResponse,
    Field(discriminator="kind"),
]
WORKER_RESPONSE = TypeAdapter(WorkerResponse)
