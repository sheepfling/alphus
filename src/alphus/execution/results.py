"""Structured built-in rule results and compatibility output adapters."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Self, TypeAlias, cast

from pydantic import BaseModel, ConfigDict, TypeAdapter

from alphus.contracts.cli_policy import CliPolicyReport
from alphus.contracts.cyclomatic import CyclomaticReport
from alphus.contracts.findings import (
    Diagnostic,
    Finding,
    Severity,
    severity_meets_threshold,
)
from alphus.contracts.python_style import StyleFindings
from alphus.contracts.shared_utilities import SharedUtilitiesReport
from alphus.policy._generated_feature_definitions import FEATURE_DEFINITIONS
from alphus.policy.base import QualityRuleName, RuleSelector
from alphus.policy.catalog import RULE_SPECS, RuleOutputShape

RuleOutput: TypeAlias = (
    list[Finding]
    | list[Diagnostic]
    | list[str]
    | CliPolicyReport
    | dict[str, StyleFindings]
    | SharedUtilitiesReport
    | CyclomaticReport
)
PythonStyleOutput: TypeAlias = dict[str, dict[str, list[int]]]


class _SharedUtilitiesWire(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    duplicate_groups: tuple[tuple[str, ...], ...]
    failed: bool
    file_hash_implementations: tuple[str, ...]
    direct_git_calls: tuple[str, ...] = ()


class _CyclomaticWire(BaseModel):
    """Validate the direct-rule report and diagnostic envelope together."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    diagnostics: tuple[Diagnostic, ...]
    report: CyclomaticReport
    summary: str


_FINDINGS: TypeAdapter[list[Finding]] = TypeAdapter(list[Finding])
_DIAGNOSTICS: TypeAdapter[list[Diagnostic]] = TypeAdapter(list[Diagnostic])
_MESSAGES: TypeAdapter[list[str]] = TypeAdapter(list[str])
_PYTHON_STYLE: TypeAdapter[PythonStyleOutput] = TypeAdapter(PythonStyleOutput)
_SHARED_UTILITIES: TypeAdapter[_SharedUtilitiesWire] = TypeAdapter(_SharedUtilitiesWire)
_SHARED_REPORT: TypeAdapter[SharedUtilitiesReport] = TypeAdapter(SharedUtilitiesReport)
_CYCLOMATIC_WIRE: TypeAdapter[_CyclomaticWire] = TypeAdapter(_CyclomaticWire)
_ADVISORY_STYLE_CATEGORIES = frozenset({"opaque_mappings", "unnamed_tuple_returns"})
_STYLE_COMPATIBILITY_ONLY_CATEGORIES = frozenset({"concrete_self_returns"})


def _message_rule_id(rule: QualityRuleName) -> str:
    if rule == "cli":
        return _feature_complaint_id(rule, "cli-contract-violation")
    if rule in FEATURE_DEFINITIONS:
        morphology = RULE_SPECS[rule].morphology
        if morphology is None or len(morphology.finding_ids) != 1:
            raise ValueError(
                f"feature message rule {rule!r} needs exactly one morphology finding ID"
            )
        return morphology.finding_ids[0].rule_id
    raise ValueError(f"no diagnostic tag registered for message rule {rule!r}")


def _message_diagnostics(
    rule: QualityRuleName, messages: Sequence[str]
) -> list[Diagnostic]:
    rule_id = _message_rule_id(rule)
    output: list[Diagnostic] = []
    for message in messages:
        inconclusive = "[presentation:inconclusive] "
        if rule == "cli" and message.startswith(inconclusive):
            output.append(
                Diagnostic(
                    source="alphus",
                    rule_id=_feature_complaint_id(rule, "cli-presentation-policy"),
                    message=message,
                    severity="info",
                )
            )
            continue
        marker = "[presentation:"
        if rule == "cli" and message.startswith(marker):
            closing = message.find("] ", len(marker))
            severity_text = message[len(marker) : closing] if closing >= 0 else ""
            if severity_text in {"warning", "error"} and closing >= 0:
                severity: Severity = (
                    "warning" if severity_text == "warning" else "error"
                )
                output.append(
                    Diagnostic(
                        source="alphus",
                        rule_id=_feature_complaint_id(rule, "cli-presentation-policy"),
                        message=message,
                        severity=severity,
                    )
                )
                continue
        output.append(Diagnostic(source="alphus", rule_id=rule_id, message=message))
    return output


def _cli_policy_diagnostics(report: CliPolicyReport) -> list[Diagnostic]:
    return [
        Diagnostic(
            source="alphus",
            rule_id=(
                _feature_complaint_id("cli", "cli-presentation-policy")
                if finding.classification == "presentation"
                else _feature_complaint_id("cli", "cli-contract-violation")
            ),
            message=finding.to_legacy_message(),
            severity=finding.severity,
        )
        for finding in report.findings
    ]


def _style_diagnostics(
    payload: Mapping[str, Mapping[str, Sequence[int]]],
) -> list[Diagnostic]:
    return [
        Diagnostic(
            source="alphus",
            rule_id=_feature_complaint_id("python-style", category.replace("_", "-")),
            path=path,
            line=line,
            message=category.replace("_", " "),
            severity=("warning" if category in _ADVISORY_STYLE_CATEGORIES else "error"),
        )
        for path, buckets in payload.items()
        for category, lines in buckets.items()
        for line in lines
        if category not in _STYLE_COMPATIBILITY_ONLY_CATEGORIES
    ]


def _feature_complaint_id(rule: RuleSelector, complaint: str) -> str:
    spec = RULE_SPECS.get(rule)
    morphology = None if spec is None else spec.morphology
    if morphology is None:
        raise ValueError(f"rule {rule!r} has no feature-owned morphology")
    matches = [
        tag.rule_id for tag in morphology.finding_ids if tag.complaint == complaint
    ]
    if len(matches) != 1:
        raise ValueError(
            f"rule {rule!r} morphology must declare complaint {complaint!r} exactly once"
        )
    return matches[0]


def _shared_diagnostics(
    rule: RuleSelector,
    groups: Sequence[Sequence[str]],
    hash_implementations: Sequence[str],
    direct_git_calls: Sequence[str],
    *,
    failed: bool,
) -> list[Diagnostic]:
    diagnostics = [
        Diagnostic(
            source="alphus",
            rule_id=_feature_complaint_id(rule, "duplicate-helper"),
            message=f"Duplicate Python helper: {', '.join(group)}",
        )
        for group in groups
    ]
    if len(hash_implementations) > 1:
        diagnostics.append(
            Diagnostic(
                source="alphus",
                rule_id=_feature_complaint_id(
                    rule, "duplicate-file-hash-implementation"
                ),
                message=(
                    "Repeated file SHA-256 implementation: "
                    f"{', '.join(hash_implementations)}"
                ),
            )
        )
    diagnostics.extend(
        Diagnostic(
            source="alphus",
            rule_id=_feature_complaint_id(rule, "direct-git-subprocess"),
            message=f"Git subprocess bypasses shared adapter: {location}",
        )
        for location in direct_git_calls
    )
    if failed and not diagnostics:
        diagnostics.append(
            Diagnostic(
                source="alphus",
                rule_id=_feature_complaint_id(rule, "shared-utilities-check-failed"),
                message="Shared utilities check reported failure without details.",
            )
        )
    return diagnostics


def diagnostics_from_output(rule: RuleSelector, output: RuleOutput) -> list[Diagnostic]:
    """Normalize a checker result without serializing it through the CLI."""
    spec = RULE_SPECS.get(rule)  # plugin diagnostics already use the shared contract
    if spec is None:
        return _DIAGNOSTICS.validate_python(output)
    shape = spec.output_shape
    if shape is RuleOutputShape.FINDINGS:
        return [
            item.as_diagnostic()
            for item in _FINDINGS.validate_python(output, strict=True)
        ]
    if shape is RuleOutputShape.MESSAGES:
        if rule == "cli" and isinstance(output, CliPolicyReport):
            return _cli_policy_diagnostics(output)
        return _message_diagnostics(
            cast(QualityRuleName, rule), _MESSAGES.validate_python(output)
        )
    if shape is RuleOutputShape.PYTHON_STYLE:
        payload = _PYTHON_STYLE.validate_python(output)
        return _style_diagnostics(payload)
    if shape is RuleOutputShape.CYCLOMATIC_REPORT:
        if not isinstance(output, CyclomaticReport):
            raise TypeError("cyclomatic-complexity runner must return CyclomaticReport")
        return list(output.diagnostics)
    if shape is not RuleOutputShape.SHARED_UTILITIES:
        raise ValueError(f"rule {rule!r} has no output normalizer")
    report = _SHARED_REPORT.validate_python(output)
    return _shared_diagnostics(
        rule,
        report.duplicate_groups,
        report.file_hash_implementations,
        report.direct_git_calls,
        failed=report.failed,
    )


def diagnostics_from_json(rule: RuleSelector, encoded: str) -> list[Diagnostic]:
    """Validate the older direct-rule JSON shapes before normalization."""
    spec = RULE_SPECS.get(rule)
    if spec is None:
        return _DIAGNOSTICS.validate_json(encoded)
    shape = spec.output_shape
    if shape is RuleOutputShape.FINDINGS:
        return [item.as_diagnostic() for item in _FINDINGS.validate_json(encoded)]
    if shape is RuleOutputShape.MESSAGES:
        return _message_diagnostics(
            cast(QualityRuleName, rule), _MESSAGES.validate_json(encoded)
        )
    if shape is RuleOutputShape.PYTHON_STYLE:
        return _style_diagnostics(_PYTHON_STYLE.validate_json(encoded))
    if shape is RuleOutputShape.CYCLOMATIC_REPORT:
        payload = _CYCLOMATIC_WIRE.validate_json(encoded)
        if payload.report.diagnostics != payload.diagnostics:
            raise ValueError("cyclomatic complexity report diagnostics do not match")
        return list(payload.diagnostics)
    if shape is not RuleOutputShape.SHARED_UTILITIES:
        raise ValueError(f"rule {rule!r} has no JSON output normalizer")
    report = _SHARED_UTILITIES.validate_json(encoded)
    return _shared_diagnostics(
        rule,
        report.duplicate_groups,
        report.file_hash_implementations,
        report.direct_git_calls,
        failed=report.failed,
    )


def is_nonfatal_cli_presentation_diagnostic(diagnostic: Diagnostic) -> bool:
    """Keep inconclusive renderer evidence nonfatal across profile adapters."""
    return (
        diagnostic.rule_id == _feature_complaint_id("cli", "cli-presentation-policy")
        and diagnostic.severity == "info"
    )


@dataclass(slots=True)
class RuleEvaluation:
    """One rule's raw output, normalized diagnostics, and threshold decision."""

    rule: RuleSelector
    output: RuleOutput
    diagnostics: list[Diagnostic]
    failed: bool

    @classmethod
    def from_output(
        cls, rule: RuleSelector, output: RuleOutput, threshold: Severity
    ) -> Self:
        diagnostics = diagnostics_from_output(rule, output)
        nonfatal_cli_messages: set[str] = set()
        if rule == "cli" and isinstance(output, CliPolicyReport):
            nonfatal_cli_messages = {
                finding.to_legacy_message()
                for finding in output.findings
                if finding.evidence == "unresolved"
            }
        elif rule == "cli" and isinstance(output, list):
            for message in output:
                match message:
                    case str() as legacy_message if legacy_message.startswith(
                        "[presentation:inconclusive] "
                    ):
                        nonfatal_cli_messages.add(legacy_message)
                    case _:
                        pass
        return cls(
            rule=rule,
            output=output,
            diagnostics=diagnostics,
            failed=any(
                severity_meets_threshold(diagnostic.severity, threshold)
                and diagnostic.message not in nonfatal_cli_messages
                for diagnostic in diagnostics
            ),
        )
