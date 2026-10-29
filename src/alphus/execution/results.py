"""Structured built-in rule results and compatibility output adapters."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Self, TypeAlias

from pydantic import BaseModel, ConfigDict, TypeAdapter

from alphus.contracts.cli_policy import CliPolicyReport
from alphus.contracts.findings import (
    Diagnostic,
    Finding,
    Severity,
    severity_meets_threshold,
)
from alphus.contracts.rule_tags import Category, Framework, Scope, rule_tag
from alphus.gates.hygiene.shared_utilities import SharedUtilitiesReport
from alphus.gates.languages.python.style import StyleFindings
from alphus.gates.source.cyclomatic_complexity import CyclomaticReport
from alphus.policy.base import QualityRuleName
from alphus.policy.catalog import RULE_SPECS, RuleOutputShape

RuleOutput: TypeAlias = (
    list[Finding]
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
_MESSAGES: TypeAdapter[list[str]] = TypeAdapter(list[str])
_PYTHON_STYLE: TypeAdapter[PythonStyleOutput] = TypeAdapter(PythonStyleOutput)
_SHARED_UTILITIES: TypeAdapter[_SharedUtilitiesWire] = TypeAdapter(_SharedUtilitiesWire)
_SHARED_REPORT: TypeAdapter[SharedUtilitiesReport] = TypeAdapter(SharedUtilitiesReport)
_CYCLOMATIC_WIRE: TypeAdapter[_CyclomaticWire] = TypeAdapter(_CyclomaticWire)
_ADVISORY_STYLE_CATEGORIES = frozenset({"opaque_mappings", "unnamed_tuple_returns"})
_STYLE_COMPATIBILITY_ONLY_CATEGORIES = frozenset({"concrete_self_returns"})
_CLI_PRESENTATION_RULE_ID = rule_tag(
    Scope.PYTHON, Framework.NONE, Category.STYLE, "cli-presentation-policy"
)

_MESSAGE_RULE_IDS: Mapping[QualityRuleName, str] = MappingProxyType(
    {
        "runtime-types": rule_tag(
            Scope.PYTHON,
            Framework.NONE,
            Category.TYPING,
            "runtime-type-contract-violation",
        ),
        "cli": rule_tag(
            Scope.PYTHON, Framework.NONE, Category.CORRECTNESS, "cli-contract-violation"
        ),
        "script-policy": rule_tag(
            Scope.PYTHON, Framework.NONE, Category.SECURITY, "script-policy-violation"
        ),
    }
)


def _message_diagnostics(
    rule: QualityRuleName, messages: Sequence[str]
) -> list[Diagnostic]:
    try:
        rule_id = _MESSAGE_RULE_IDS[rule]
    except KeyError as error:
        raise ValueError(
            f"no diagnostic tag registered for message rule {rule!r}"
        ) from error
    output: list[Diagnostic] = []
    for message in messages:
        inconclusive = "[presentation:inconclusive] "
        if rule == "cli" and message.startswith(inconclusive):
            output.append(
                Diagnostic(
                    source="alphus",
                    rule_id=_CLI_PRESENTATION_RULE_ID,
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
                        rule_id=_CLI_PRESENTATION_RULE_ID,
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
                _CLI_PRESENTATION_RULE_ID
                if finding.classification == "presentation"
                else _MESSAGE_RULE_IDS["cli"]
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
            rule_id=rule_tag(
                Scope.PYTHON, Framework.NONE, Category.STYLE, category.replace("_", "-")
            ),
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


def _shared_diagnostics(
    groups: Sequence[Sequence[str]],
    hash_implementations: Sequence[str],
    direct_git_calls: Sequence[str],
    *,
    failed: bool,
) -> list[Diagnostic]:
    diagnostics = [
        Diagnostic(
            source="alphus",
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
                source="alphus",
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
            source="alphus",
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
                source="alphus",
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
        if rule == "cli" and isinstance(output, CliPolicyReport):
            return _cli_policy_diagnostics(output)
        return _message_diagnostics(rule, _MESSAGES.validate_python(output))
    if shape is RuleOutputShape.PYTHON_STYLE:
        payload = _PYTHON_STYLE.validate_python(output)
        return _style_diagnostics(payload)
    if shape is RuleOutputShape.CYCLOMATIC_REPORT:
        return list(output.diagnostics) if isinstance(output, CyclomaticReport) else []
    if shape is not RuleOutputShape.SHARED_UTILITIES:
        raise ValueError(f"rule {rule!r} has no output normalizer")
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
    if shape is RuleOutputShape.CYCLOMATIC_REPORT:
        payload = _CYCLOMATIC_WIRE.validate_json(encoded)
        if payload.report.diagnostics != payload.diagnostics:
            raise ValueError("cyclomatic complexity report diagnostics do not match")
        return list(payload.diagnostics)
    if shape is not RuleOutputShape.SHARED_UTILITIES:
        raise ValueError(f"rule {rule!r} has no JSON output normalizer")
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
