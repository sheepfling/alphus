"""Structured built-in rule results and compatibility output adapters."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Self, TypeAlias

from pydantic import BaseModel, ConfigDict, TypeAdapter

from alphus.contracts.findings import (
    Diagnostic,
    Finding,
    Severity,
    severity_meets_threshold,
)
from alphus.contracts.rule_tags import NAMESPACE, Category, Framework, Scope, rule_tag
from alphus.gates.hygiene.shared_utilities import SharedUtilitiesReport
from alphus.gates.source.python_style import StyleFindings
from alphus.policy.base import QualityRuleName
from alphus.policy.catalog import RULE_SPECS, RuleOutputShape

# Compatibility union until legacy rule outputs migrate to normalized findings.
RuleOutput: TypeAlias = (
    list[Finding] | list[str] | dict[str, StyleFindings] | SharedUtilitiesReport
)
# Legacy direct-rule payload retained for its existing CLI/JSON contract.
PythonStyleOutput: TypeAlias = dict[str, dict[str, list[int]]]


class _SharedUtilitiesWire(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    duplicate_groups: tuple[tuple[str, ...], ...]
    failed: bool
    file_hash_implementations: tuple[str, ...]
    direct_git_calls: tuple[str, ...] = ()


_FINDINGS: TypeAdapter[list[Finding]] = TypeAdapter(list[Finding])
_MESSAGES: TypeAdapter[list[str]] = TypeAdapter(list[str])
_PYTHON_STYLE: TypeAdapter[PythonStyleOutput] = TypeAdapter(PythonStyleOutput)
_SHARED_UTILITIES: TypeAdapter[_SharedUtilitiesWire] = TypeAdapter(_SharedUtilitiesWire)
_SHARED_REPORT: TypeAdapter[SharedUtilitiesReport] = TypeAdapter(SharedUtilitiesReport)


def _message_diagnostics(
    rule: QualityRuleName, messages: Sequence[str]
) -> list[Diagnostic]:
    rule_id = RULE_SPECS[rule].message_rule_id
    if rule_id is None:
        raise ValueError(f"no diagnostic tag registered for message rule {rule!r}")
    return [
        Diagnostic(source=NAMESPACE, rule_id=rule_id, message=message)
        for message in messages
    ]


def _style_diagnostics(
    payload: Mapping[str, Mapping[str, Sequence[int]]],
) -> list[Diagnostic]:
    return [
        Diagnostic(
            source=NAMESPACE,
            rule_id=rule_tag(
                Scope.PYTHON, Framework.NONE, Category.STYLE, category.replace("_", "-")
            ),
            path=path,
            line=line,
            message=category.replace("_", " "),
        )
        for path, buckets in payload.items()
        for category, lines in buckets.items()
        for line in lines
    ]


def _shared_diagnostics(
    groups: Sequence[Sequence[str]],
    hash_implementations: Sequence[str],
    direct_git_calls: Sequence[str],
    *,
    failed: bool,
) -> list[Diagnostic]:
    diagnostics = [
        Diagnostic(
            source=NAMESPACE,
            rule_id=rule_tag(
                Scope.PYTHON,
                Framework.NONE,
                Category.MAINTAINABILITY,
                "duplicate-helper",
            ),
            message=f"Duplicate Python helper: {', '.join(group)}",
        )
        for group in groups
    ]
    if len(hash_implementations) > 1:
        diagnostics.append(
            Diagnostic(
                source=NAMESPACE,
                rule_id=rule_tag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.MAINTAINABILITY,
                    "duplicate-file-hash-implementation",
                ),
                message=(
                    "Repeated file SHA-256 implementation: "
                    f"{', '.join(hash_implementations)}"
                ),
            )
        )
    diagnostics.extend(
        Diagnostic(
            source=NAMESPACE,
            rule_id=rule_tag(
                Scope.PYTHON,
                Framework.NONE,
                Category.MAINTAINABILITY,
                "direct-git-subprocess",
            ),
            message=f"Git subprocess bypasses shared adapter: {location}",
        )
        for location in direct_git_calls
    )
    if failed and not diagnostics:
        diagnostics.append(
            Diagnostic(
                source=NAMESPACE,
                rule_id=rule_tag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.MAINTAINABILITY,
                    "shared-utilities-check-failed",
                ),
                message="Shared utilities check reported failure without details.",
            )
        )
    return diagnostics


def diagnostics_from_output(
    rule: QualityRuleName, output: RuleOutput
) -> list[Diagnostic]:
    """Normalize a checker result without serializing it through the CLI."""
    shape = RULE_SPECS[rule].output_shape
    if shape is RuleOutputShape.FINDINGS:
        return [item.as_diagnostic() for item in _FINDINGS.validate_python(output)]
    if shape is RuleOutputShape.MESSAGES:
        return _message_diagnostics(rule, _MESSAGES.validate_python(output))
    if shape is RuleOutputShape.PYTHON_STYLE:
        payload = _PYTHON_STYLE.validate_python(output)
        return _style_diagnostics(payload)
    report = _SHARED_REPORT.validate_python(output)
    return _shared_diagnostics(
        report.duplicate_groups,
        report.file_hash_implementations,
        report.direct_git_calls,
        failed=report.failed,
    )


def diagnostics_from_json(rule: QualityRuleName, encoded: str) -> list[Diagnostic]:
    """Validate the older direct-rule JSON shapes before normalization."""
    shape = RULE_SPECS[rule].output_shape
    if shape is RuleOutputShape.FINDINGS:
        return [item.as_diagnostic() for item in _FINDINGS.validate_json(encoded)]
    if shape is RuleOutputShape.MESSAGES:
        return _message_diagnostics(rule, _MESSAGES.validate_json(encoded))
    if shape is RuleOutputShape.PYTHON_STYLE:
        return _style_diagnostics(_PYTHON_STYLE.validate_json(encoded))
    report = _SHARED_UTILITIES.validate_json(encoded)
    return _shared_diagnostics(
        report.duplicate_groups,
        report.file_hash_implementations,
        report.direct_git_calls,
        failed=report.failed,
    )


@dataclass(slots=True)
class RuleEvaluation:
    """One rule's raw output, normalized diagnostics, and threshold decision."""

    rule: QualityRuleName
    output: RuleOutput
    diagnostics: list[Diagnostic]
    failed: bool

    @classmethod
    def from_output(
        cls, rule: QualityRuleName, output: RuleOutput, threshold: Severity
    ) -> Self:
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
