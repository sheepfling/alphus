"""Caller-declared profile audit requirements and conservative completion."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import PurePosixPath
from typing import Literal, NotRequired, Required, Self

from pydantic import model_validator
from typing_extensions import TypedDict

from alphus.contracts.rule_tags import Category, Framework, Scope, rule_tag
from alphus.policy.base import StrictModel, require_unique


class AuditManifestCheck(StrictModel):
    """One required check, its exact expected inventory, and optional intent."""

    check_id: str
    step: str
    expected_files: tuple[str, ...] | None
    required_argv: tuple[str, ...] = ()
    rule_id: str | None = None
    language: str | None = None
    native_rule: str | None = None

    @model_validator(mode="after")
    def validate_check(self) -> Self:
        if not self.check_id or self.check_id != self.check_id.strip():
            raise ValueError("audit check_id must be non-empty and trimmed")
        if not self.step or self.step != self.step.strip():
            raise ValueError("audit step must be non-empty and trimmed")
        selectors = (self.rule_id, self.language, self.native_rule)
        if any(value is not None for value in selectors) and not all(
            value is not None for value in selectors
        ):
            raise ValueError(
                "rule_id, language, and native_rule must be supplied together"
            )
        for label, value in (
            ("rule_id", self.rule_id),
            ("language", self.language),
            ("native_rule", self.native_rule),
        ):
            if value is not None and (not value or value != value.strip()):
                raise ValueError(f"audit {label} must be non-empty and trimmed")
        if any(not value for value in self.required_argv):
            raise ValueError("audit required_argv values must be non-empty")
        require_unique(self.required_argv, "audit required_argv values must be unique")
        if self.expected_files is not None:
            require_unique(
                self.expected_files,
                "audit expected_files must not contain duplicates",
            )
            for value in self.expected_files:
                path = PurePosixPath(value)
                if (
                    not value
                    or path.is_absolute()
                    or "\\" in value
                    or ".." in path.parts
                    or path.as_posix() != value
                ):
                    raise ValueError(
                        "audit expected_files must be canonical relative POSIX paths"
                    )
        return self


class AuditManifest(StrictModel):
    """Versioned, caller-supplied set of checks required for one profile audit."""

    format: Literal["alphus.audit-manifest"]
    schema_version: Literal[1]
    profile: str
    checks: tuple[AuditManifestCheck, ...]

    @model_validator(mode="after")
    def validate_manifest(self) -> Self:
        if not self.profile or self.profile != self.profile.strip():
            raise ValueError("audit profile must be non-empty and trimmed")
        if not self.checks:
            raise ValueError("audit manifest must declare at least one check")
        require_unique(
            tuple(check.check_id for check in self.checks),
            "audit check_id values must be unique",
        )
        return self


class AuditPlanStep(TypedDict, total=False):
    """Selected step and resolved scope from the saved profile plan."""

    name: Required[str]
    kind: str
    selected_files: list[str] | None
    expanded_argv: list[str]


class AuditPlanIntent(TypedDict):
    """Native intent selector recorded by the resolved plan."""

    rule_id: str
    language: str
    native_rule: str
    step: str | None


class AuditResultFinding(TypedDict):
    """Stable finding identity used to distinguish tool failures from findings."""

    rule_id: str


class ProfileAuditPlan(TypedDict):
    """Evidence needed from the resolved profile plan."""

    profile: str
    steps: list[AuditPlanStep]
    intents: list[AuditPlanIntent]


class AuditResultStep(TypedDict, total=False):
    """Observed step outcome from the profile execution report."""

    name: Required[str]
    status: Required[str]
    findings: list[AuditResultFinding]


class AuditResultIntent(TypedDict, total=False):
    """Observed outcome for one native semantic intent."""

    rule_id: Required[str]
    language: Required[str]
    native_rule: Required[str]
    status: Required[str]
    failure_kind: str | None
    step: Required[str | None]


class ProfileAuditResult(TypedDict):
    """Evidence needed from the profile execution report."""

    profile: str
    steps: list[AuditResultStep]
    intent_bindings: NotRequired[list[AuditResultIntent]]


AuditCheckStatus = Literal[
    "not_selected",
    "scope_mismatch",
    "selector_mismatch",
    "missing_policy",
    "not_executed",
    "disabled",
    "unsupported",
    "empty_inventory",
    "execution_failure",
    "incomplete",
    "executed",
    "executed_zero",
    "executed_with_findings",
]


class AuditCheckAssessment(TypedDict, total=False):
    """Completion and finding evidence for one manifest entry."""

    check_id: Required[str]
    step: Required[str]
    status: Required[AuditCheckStatus]
    complete: Required[bool]
    reason: str
    expected_files: list[str] | None
    selected_files: list[str] | None
    required_argv: list[str]
    expanded_argv: list[str]
    rule_id: str
    language: str
    native_rule: str
    findings_state: Literal["with_findings", "zero_findings", "unknown"]
    structured_finding_count: int


class AuditCompletion(TypedDict):
    """Versioned assessment kept separate from severity and enforcement."""

    schema: Literal["alphus.profile-audit-completion"]
    schema_version: Literal[1]
    profile: str
    status: Literal["complete", "incomplete"]
    checks: list[AuditCheckAssessment]
    reason: NotRequired[str]


_COMPLETE_STATES = frozenset({"executed", "executed_zero", "executed_with_findings"})
_COMMAND_EXITED_NONZERO_RULE = rule_tag(
    Scope.ANY, Framework.NONE, Category.ORCHESTRATION, "command-exited-nonzero"
)
_OPERATIONAL_FAILURE_RULES = frozenset(
    rule_tag(Scope.ANY, Framework.NONE, Category.ORCHESTRATION, complaint)
    for complaint in (
        "command-exited-nonzero",
        "command-launch-failed",
        "command-timed-out",
        "command-output-invalid",
        "rule-execution-failed",
    )
)


def _incomplete_assessment(
    manifest: AuditManifest,
    reason: str,
    *,
    status: AuditCheckStatus = "incomplete",
) -> AuditCompletion:
    checks: list[AuditCheckAssessment] = [
        {
            "check_id": check.check_id,
            "step": check.step,
            "status": status,
            "complete": False,
        }
        for check in manifest.checks
    ]
    _attach_check_scope(checks, manifest, None)
    return {
        "schema": "alphus.profile-audit-completion",
        "schema_version": 1,
        "profile": manifest.profile,
        "status": "incomplete",
        "reason": reason,
        "checks": checks,
    }


def _attach_check_scope(
    assessments: Sequence[AuditCheckAssessment],
    manifest: AuditManifest,
    planned_steps: Sequence[AuditPlanStep] | None,
) -> None:
    """Retain declared and resolved scope with every completion outcome."""
    for manifest_check in manifest.checks:
        assessment = next(
            row for row in assessments if row["check_id"] == manifest_check.check_id
        )
        planned_step = (
            next(
                (row for row in planned_steps if row["name"] == manifest_check.step),
                None,
            )
            if planned_steps is not None
            else None
        )
        assessment["expected_files"] = (
            None
            if manifest_check.expected_files is None
            else list(manifest_check.expected_files)
        )
        assessment["selected_files"] = (
            None if planned_step is None else planned_step.get("selected_files")
        )
        assessment["required_argv"] = list(manifest_check.required_argv)
        assessment["expanded_argv"] = (
            [] if planned_step is None else planned_step.get("expanded_argv", [])
        )
        if (
            manifest_check.rule_id is not None
            and manifest_check.language is not None
            and manifest_check.native_rule is not None
        ):
            assessment["rule_id"] = manifest_check.rule_id
            assessment["language"] = manifest_check.language
            assessment["native_rule"] = manifest_check.native_rule


def assess_profile_audit(
    manifest: AuditManifest,
    plan: ProfileAuditPlan | None,
    result: ProfileAuditResult | None,
    *,
    unavailable_reason: str | None = None,
    unavailable_status: AuditCheckStatus = "incomplete",
) -> AuditCompletion:
    """Compare declared checks with selected scope and observed execution states.

    A command step without structured findings is reported as executed with
    unknown finding state. Its exit status alone is not evidence of zero findings.
    """
    if unavailable_reason is not None:
        return _incomplete_assessment(
            manifest, unavailable_reason, status=unavailable_status
        )
    if (
        plan is None
        or result is None
        or plan.get("profile") != manifest.profile
        or result.get("profile") != manifest.profile
    ):
        return _incomplete_assessment(
            manifest,
            "manifest profile does not match available plan and result evidence",
        )

    planned_steps = {row["name"]: row for row in plan["steps"]}
    executed_steps = {row["name"]: row for row in result["steps"]}
    planned_intents = plan["intents"]
    executed_intents = result.get("intent_bindings", [])
    checks: list[AuditCheckAssessment] = []

    for check in manifest.checks:
        planned_step = planned_steps.get(check.step)
        if planned_step is None:
            checks.append(
                {
                    "check_id": check.check_id,
                    "step": check.step,
                    "status": "not_selected",
                    "complete": False,
                }
            )
            continue

        actual_files = planned_step.get("selected_files")
        if check.expected_files is None:
            if actual_files is not None:
                checks.append(
                    {
                        "check_id": check.check_id,
                        "step": check.step,
                        "status": "scope_mismatch",
                        "complete": False,
                        "expected_files": None,
                        "selected_files": actual_files,
                    }
                )
                continue
        elif actual_files is None or sorted(actual_files) != sorted(
            check.expected_files
        ):
            checks.append(
                {
                    "check_id": check.check_id,
                    "step": check.step,
                    "status": "scope_mismatch",
                    "complete": False,
                    "expected_files": list(check.expected_files),
                    "selected_files": actual_files,
                }
            )
            continue

        if planned_step.get("kind") == "rule" and actual_files == []:
            checks.append(
                {
                    "check_id": check.check_id,
                    "step": check.step,
                    "status": "empty_inventory",
                    "complete": False,
                    "expected_files": list(check.expected_files or ()),
                    "selected_files": [],
                    "reason": "the selected built-in rule has no files to inspect",
                }
            )
            continue

        expanded_argv = planned_step.get("expanded_argv", [])
        if any(argument not in expanded_argv for argument in check.required_argv):
            checks.append(
                {
                    "check_id": check.check_id,
                    "step": check.step,
                    "status": "selector_mismatch",
                    "complete": False,
                    "required_argv": list(check.required_argv),
                    "expanded_argv": expanded_argv,
                }
            )
            continue

        executed_intent: AuditResultIntent | None = None
        if check.rule_id is not None:
            matching_planned_intents = [
                row
                for row in planned_intents
                if row.get("rule_id") == check.rule_id
                and row.get("language") == check.language
                and row.get("native_rule") == check.native_rule
            ]
            planned_intent = next(
                (
                    row
                    for row in matching_planned_intents
                    if row.get("step") == check.step
                ),
                None,
            )
            if planned_intent is None:
                status: AuditCheckStatus = (
                    "scope_mismatch" if matching_planned_intents else "not_selected"
                )
                checks.append(
                    {
                        "check_id": check.check_id,
                        "step": check.step,
                        "status": status,
                        "complete": False,
                        "reason": "declared semantic/native intent is bound to a different step"
                        if matching_planned_intents
                        else "declared semantic/native intent is absent from the resolved plan",
                    }
                )
                continue
            executed_intent = next(
                (
                    row
                    for row in executed_intents
                    if row.get("rule_id") == check.rule_id
                    and row.get("language") == check.language
                    and row.get("native_rule") == check.native_rule
                    and row.get("step") == check.step
                ),
                None,
            )
            if executed_intent is None:
                mismatched_result_binding = any(
                    row.get("rule_id") == check.rule_id
                    and row.get("language") == check.language
                    and row.get("native_rule") == check.native_rule
                    for row in executed_intents
                )
                checks.append(
                    {
                        "check_id": check.check_id,
                        "step": check.step,
                        "status": (
                            "scope_mismatch"
                            if mismatched_result_binding
                            else "not_executed"
                        ),
                        "complete": False,
                        "reason": "executed intent evidence is bound to a different step"
                        if mismatched_result_binding
                        else "no execution evidence for the declared intent step",
                    }
                )
                continue
            intent_status = executed_intent.get("status")
            intent_states: dict[str, AuditCheckStatus] = {
                "not_selected": "not_selected",
                "disabled": "disabled",
                "unsupported": "unsupported",
                "not_applicable": "empty_inventory",
            }
            if intent_status in intent_states:
                checks.append(
                    {
                        "check_id": check.check_id,
                        "step": check.step,
                        "status": intent_states[intent_status],
                        "complete": False,
                    }
                )
                continue
            failure_kind = executed_intent.get("failure_kind")
            if intent_status == "failed" and failure_kind not in {
                "violation",
                "operational_error",
                "configuration_error",
            }:
                checks.append(
                    {
                        "check_id": check.check_id,
                        "step": check.step,
                        "status": "incomplete",
                        "complete": False,
                        "reason": "failed intent has no recognized failure kind",
                    }
                )
                continue
            if intent_status == "passed" and failure_kind is not None:
                checks.append(
                    {
                        "check_id": check.check_id,
                        "step": check.step,
                        "status": "incomplete",
                        "complete": False,
                        "reason": "passed intent has a contradictory failure kind",
                    }
                )
                continue
            if intent_status not in {"passed", "failed"}:
                checks.append(
                    {
                        "check_id": check.check_id,
                        "step": check.step,
                        "status": "incomplete",
                        "complete": False,
                        "reason": "intent has an unknown execution status",
                    }
                )
                continue

        executed_step = executed_steps.get(check.step)
        if executed_step is None:
            checks.append(
                {
                    "check_id": check.check_id,
                    "step": check.step,
                    "status": "not_executed",
                    "complete": False,
                }
            )
            continue

        step_status = executed_step.get("status")
        if step_status in {"disabled", "unsupported", "not_applicable"}:
            step_states: dict[str, AuditCheckStatus] = {
                "disabled": "disabled",
                "unsupported": "unsupported",
                "not_applicable": "empty_inventory",
            }
            checks.append(
                {
                    "check_id": check.check_id,
                    "step": check.step,
                    "status": step_states[step_status],
                    "complete": False,
                }
            )
            continue
        if step_status not in {"passed", "failed"}:
            checks.append(
                {
                    "check_id": check.check_id,
                    "step": check.step,
                    "status": "not_executed",
                    "complete": False,
                }
            )
            continue

        findings = executed_step.get("findings", [])
        violation_evidence = (
            executed_intent is not None
            and executed_intent.get("failure_kind") == "violation"
        )
        operational_evidence = any(
            finding["rule_id"] in _OPERATIONAL_FAILURE_RULES
            and not (
                violation_evidence
                and finding["rule_id"] == _COMMAND_EXITED_NONZERO_RULE
            )
            for finding in findings
        ) or (
            executed_intent is not None
            and executed_intent.get("failure_kind")
            in {"operational_error", "configuration_error"}
        )
        if operational_evidence:
            checks.append(
                {
                    "check_id": check.check_id,
                    "step": check.step,
                    "status": "execution_failure",
                    "complete": False,
                    "findings_state": "unknown",
                    "structured_finding_count": len(findings),
                }
            )
            continue
        if findings or violation_evidence:
            state: AuditCheckStatus = "executed_with_findings"
            findings_state: Literal["with_findings", "zero_findings", "unknown"] = (
                "with_findings"
            )
        elif step_status == "failed":
            state = "execution_failure"
            findings_state = "unknown"
        elif planned_step.get("kind") == "rule":
            state = "executed_zero"
            findings_state = "zero_findings"
        else:
            state = "executed"
            findings_state = "unknown"
        checks.append(
            {
                "check_id": check.check_id,
                "step": check.step,
                "status": state,
                "complete": state in _COMPLETE_STATES,
                "findings_state": findings_state,
                "structured_finding_count": len(findings),
            }
        )

    _attach_check_scope(checks, manifest, plan["steps"])
    complete = all(check["complete"] for check in checks)
    return {
        "schema": "alphus.profile-audit-completion",
        "schema_version": 1,
        "profile": manifest.profile,
        "status": "complete" if complete else "incomplete",
        "checks": checks,
    }
