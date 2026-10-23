"""Structured built-in rule results and compatibility output adapters."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TypeAlias

from pydantic import BaseModel, ConfigDict, TypeAdapter

from alphus.config_base import QualityRuleName
from alphus.findings import Diagnostic, Finding, Severity, severity_meets_threshold
from alphus.gates.source.python_style import StyleFindings
from alphus.rule_catalog import RULE_SPECS
from alphus.shared_utilities import SharedUtilitiesReport

RuleOutput: TypeAlias = (
    list[Finding] | list[str] | dict[str, StyleFindings] | SharedUtilitiesReport
)
PythonStyleOutput: TypeAlias = dict[str, dict[str, list[int]]]


class _SharedUtilitiesWire(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    duplicate_groups: tuple[tuple[str, ...], ...]
    failed: bool
    file_hash_implementations: tuple[str, ...]


_FINDINGS: TypeAdapter[list[Finding]] = TypeAdapter(list[Finding])
_MESSAGES: TypeAdapter[list[str]] = TypeAdapter(list[str])
_PYTHON_STYLE: TypeAdapter[PythonStyleOutput] = TypeAdapter(PythonStyleOutput)
_SHARED_UTILITIES: TypeAdapter[_SharedUtilitiesWire] = TypeAdapter(_SharedUtilitiesWire)
_SHARED_REPORT: TypeAdapter[SharedUtilitiesReport] = TypeAdapter(SharedUtilitiesReport)


def _style_diagnostics(
    payload: Mapping[str, Mapping[str, Sequence[int]]],
) -> tuple[Diagnostic, ...]:
    return tuple(
        Diagnostic(
            source="alphus",
            rule_id=f"python-style.{category}",
            path=path,
            line=line,
            message=category.replace("_", " "),
        )
        for path, buckets in payload.items()
        for category, lines in buckets.items()
        for line in lines
    )


def _shared_diagnostics(
    groups: Sequence[Sequence[str]],
    hash_implementations: Sequence[str],
    *,
    failed: bool,
) -> tuple[Diagnostic, ...]:
    diagnostics = [
        Diagnostic(
            source="alphus",
            rule_id="shared-utilities.duplicate-helper",
            message=f"Duplicate Python helper: {', '.join(group)}",
        )
        for group in groups
    ]
    if len(hash_implementations) > 1:
        diagnostics.append(
            Diagnostic(
                source="alphus",
                rule_id="shared-utilities.file-hash-implementation",
                message=(
                    "Repeated file SHA-256 implementation: "
                    f"{', '.join(hash_implementations)}"
                ),
            )
        )
    if failed and not diagnostics:
        diagnostics.append(
            Diagnostic(
                source="alphus",
                rule_id="shared-utilities.failure",
                message="Shared utilities check reported failure without details.",
            )
        )
    return tuple(diagnostics)


def diagnostics_from_output(
    rule: QualityRuleName, output: RuleOutput
) -> tuple[Diagnostic, ...]:
    """Normalize a checker result without serializing it through the CLI."""
    shape = RULE_SPECS[rule].output_shape
    if shape == "findings":
        return tuple(item.as_diagnostic() for item in _FINDINGS.validate_python(output))
    if shape == "messages":
        return tuple(
            Diagnostic(source="alphus", rule_id=f"alphus.{rule}", message=message)
            for message in _MESSAGES.validate_python(output)
        )
    if shape == "python-style":
        payload = _PYTHON_STYLE.validate_python(output)
        return _style_diagnostics(payload)
    report = _SHARED_REPORT.validate_python(output)
    return _shared_diagnostics(
        report.duplicate_groups,
        report.file_hash_implementations,
        failed=report.failed,
    )


def diagnostics_from_json(
    rule: QualityRuleName, encoded: str
) -> tuple[Diagnostic, ...]:
    """Validate the older direct-rule JSON shapes before normalization."""
    shape = RULE_SPECS[rule].output_shape
    if shape == "findings":
        return tuple(item.as_diagnostic() for item in _FINDINGS.validate_json(encoded))
    if shape == "messages":
        return tuple(
            Diagnostic(source="alphus", rule_id=f"alphus.{rule}", message=message)
            for message in _MESSAGES.validate_json(encoded)
        )
    if shape == "python-style":
        return _style_diagnostics(_PYTHON_STYLE.validate_json(encoded))
    report = _SHARED_UTILITIES.validate_json(encoded)
    return _shared_diagnostics(
        report.duplicate_groups,
        report.file_hash_implementations,
        failed=report.failed,
    )


@dataclass(frozen=True, slots=True)
class RuleEvaluation:
    """One rule's raw output, normalized diagnostics, and threshold decision."""

    rule: QualityRuleName
    output: RuleOutput
    diagnostics: tuple[Diagnostic, ...]
    failed: bool

    @classmethod
    def from_output(
        cls, rule: QualityRuleName, output: RuleOutput, threshold: Severity
    ) -> RuleEvaluation:
        diagnostics = diagnostics_from_output(rule, output)
        return cls(
            rule=rule,
            output=output,
            diagnostics=diagnostics,
            failed=any(
                severity_meets_threshold(diagnostic.severity, threshold)
                for diagnostic in diagnostics
            ),
        )
