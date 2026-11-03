"""Caller-supplied manifests assess selected profile coverage explicitly."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from alphus.execution.audit_manifest import (
    AuditCheckAssessment,
    AuditCompletion,
    AuditManifest,
    AuditManifestCheck,
    AuditPlanIntent,
    AuditPlanStep,
    AuditResultFinding,
    ProfileAuditPlan,
    ProfileAuditResult,
    assess_profile_audit,
)


def _manifest(
    *,
    expected_files: Sequence[str] | None = ("src/example.py",),
    required_argv: Sequence[str] = (),
    rule_id: str | None = None,
    language: str | None = None,
    native_rule: str | None = None,
) -> AuditManifest:
    return AuditManifest(
        format="alphus.audit-manifest",
        schema_version=1,
        profile="audit",
        checks=(
            AuditManifestCheck(
                check_id="source-review",
                step="Source review",
                expected_files=(
                    None if expected_files is None else tuple(expected_files)
                ),
                required_argv=tuple(required_argv),
                rule_id=rule_id,
                language=language,
                native_rule=native_rule,
            ),
        ),
    )


def _plan(
    *, kind: str = "rule", files: Sequence[str] | None = None
) -> ProfileAuditPlan:
    return {
        "profile": "audit",
        "steps": [
            AuditPlanStep(
                name="Source review",
                kind=kind,
                selected_files=(
                    list(files) if files is not None else ["src/example.py"]
                ),
            )
        ],
        "intents": [],
    }


def _result(
    *, status: str = "passed", findings: Sequence[AuditResultFinding] = ()
) -> ProfileAuditResult:
    return {
        "profile": "audit",
        "steps": [
            {
                "name": "Source review",
                "status": status,
                "findings": list(findings),
            }
        ],
    }


def _checks(assessment: AuditCompletion) -> list[AuditCheckAssessment]:
    return assessment["checks"]


def _plan_step(plan: ProfileAuditPlan) -> AuditPlanStep:
    return plan["steps"][0]


def test_manifest_distinguishes_executed_zero_and_executed_findings() -> None:
    manifest = _manifest()

    zero = assess_profile_audit(manifest, _plan(), _result())
    findings = assess_profile_audit(
        manifest,
        _plan(),
        _result(findings=(AuditResultFinding(rule_id="sample/rule"),)),
    )

    assert zero["status"] == "complete"
    assert _checks(zero)[0]["status"] == "executed_zero"
    assert _checks(zero)[0].get("findings_state") == "zero_findings"
    assert findings["status"] == "complete"
    assert _checks(findings)[0]["status"] == "executed_with_findings"
    assert _checks(findings)[0].get("structured_finding_count") == 1


def test_manifest_marks_requested_but_unselected_step_incomplete() -> None:
    manifest = _manifest()

    assessment = assess_profile_audit(
        manifest,
        {"profile": "audit", "steps": [], "intents": []},
        {"profile": "audit", "steps": []},
    )

    assert assessment["status"] == "incomplete"
    assert _checks(assessment)[0]["status"] == "not_selected"
    assert _checks(assessment)[0]["complete"] is False


def test_manifest_rejects_scope_mismatch_and_empty_inventory() -> None:
    manifest = _manifest()
    mismatch = assess_profile_audit(manifest, _plan(files=[]), _result())
    empty = assess_profile_audit(manifest, _plan(), _result(status="not_applicable"))
    empty_rule_inventory = assess_profile_audit(
        _manifest(expected_files=()),
        _plan(files=[]),
        _result(status="passed"),
    )

    assert _checks(mismatch)[0]["status"] == "scope_mismatch"
    assert mismatch["status"] == "incomplete"
    assert _checks(empty)[0]["status"] == "empty_inventory"
    assert empty["status"] == "incomplete"
    assert _checks(empty_rule_inventory)[0]["status"] == "empty_inventory"
    assert empty_rule_inventory["status"] == "incomplete"


def test_unstructured_command_result_does_not_claim_zero_findings() -> None:
    manifest = _manifest()

    assessment = assess_profile_audit(manifest, _plan(kind="command"), _result())

    assert assessment["status"] == "complete"
    assert _checks(assessment)[0]["status"] == "executed"
    assert _checks(assessment)[0].get("findings_state") == "unknown"


@pytest.mark.parametrize(
    "rule_id",
    [
        "alphus/any/none/orchestration/command-exited-nonzero",
        "alphus/any/none/orchestration/rule-execution-failed",
    ],
)
def test_operational_failure_findings_remain_incomplete(rule_id: str) -> None:
    assessment = assess_profile_audit(
        _manifest(),
        _plan(kind="command"),
        _result(
            status="failed",
            findings=(AuditResultFinding(rule_id=rule_id),),
        ),
    )

    assert assessment["status"] == "incomplete"
    assert _checks(assessment)[0]["status"] == "execution_failure"
    assert _checks(assessment)[0]["complete"] is False


def test_violation_intent_keeps_command_nonzero_evidence_as_findings() -> None:
    selectors = AuditPlanIntent(
        rule_id="alphus/python/none/testing/example",
        language="python",
        native_rule="ANN",
        step="Source review",
    )
    manifest = _manifest(
        rule_id=selectors["rule_id"],
        language=selectors["language"],
        native_rule=selectors["native_rule"],
    )
    plan = _plan(kind="command")
    plan["intents"] = [selectors]
    result = _result(
        status="failed",
        findings=(
            AuditResultFinding(
                rule_id="alphus/any/none/orchestration/command-exited-nonzero"
            ),
        ),
    )
    result["intent_bindings"] = [
        {
            **selectors,
            "status": "failed",
            "failure_kind": "violation",
        }
    ]

    assessment = assess_profile_audit(manifest, plan, result)

    assert assessment["status"] == "complete"
    assert _checks(assessment)[0]["status"] == "executed_with_findings"
    assert _checks(assessment)[0]["findings_state"] == "with_findings"

    result["steps"][0]["findings"] = [
        AuditResultFinding(
            rule_id="alphus/any/none/orchestration/command-launch-failed"
        )
    ]
    operational = assess_profile_audit(manifest, plan, result)

    assert operational["status"] == "incomplete"
    assert _checks(operational)[0]["status"] == "execution_failure"


def test_source_family_coverage_warning_keeps_audit_incomplete() -> None:
    finding = AuditResultFinding(
        rule_id="alphus/any/none/maintainability/flat-source-family",
        message=(
            "Lexical source-family scan incomplete: more than 1 selected files "
            "were available and the inventory was limited; no clean result can "
            "be inferred from the partial evidence."
        ),
    )

    plan = _plan()
    plan["steps"][0]["selected_files"] = None
    assessment = assess_profile_audit(
        _manifest(expected_files=None),
        plan,
        _result(findings=(finding,)),
    )

    assert assessment["status"] == "incomplete"
    assert _checks(assessment)[0]["status"] == "incomplete"
    assert _checks(assessment)[0]["complete"] is False
    assert _checks(assessment)[0]["findings_state"] == "with_findings"


def test_inconclusive_cli_presentation_finding_keeps_audit_incomplete() -> None:
    plan = _plan()
    plan["steps"][0]["kind"] = "rule"
    plan["steps"][0]["selected_files"] = None
    assessment = assess_profile_audit(
        _manifest(expected_files=None),
        plan,
        _result(
            findings=(
                AuditResultFinding(
                    rule_id="alphus/python/none/style/cli-presentation-policy",
                    message=(
                        "[presentation:inconclusive] Could not verify the renderer."
                    ),
                ),
            )
        ),
    )

    assert assessment["status"] == "incomplete"
    assert _checks(assessment)[0]["status"] == "incomplete"
    assert _checks(assessment)[0]["complete"] is False
    assert _checks(assessment)[0]["findings_state"] == "with_findings"


def test_ordinary_source_family_finding_keeps_completed_audit() -> None:
    plan = _plan()
    plan["steps"][0]["selected_files"] = None
    assessment = assess_profile_audit(
        _manifest(expected_files=None),
        plan,
        _result(
            findings=(
                AuditResultFinding(
                    rule_id="alphus/any/none/maintainability/flat-source-family",
                    message="Sibling source names share a prefix.",
                ),
            )
        ),
    )

    assert assessment["status"] == "complete"
    assert _checks(assessment)[0]["status"] == "executed_with_findings"


def test_manifest_checks_required_native_selector_tokens() -> None:
    manifest = _manifest(required_argv=("--select=ANN",))
    plan = _plan(kind="command")
    _plan_step(plan)["expanded_argv"] = ["ruff", "check", "--select=ANN"]

    selected = assess_profile_audit(manifest, plan, _result())
    _plan_step(plan)["expanded_argv"] = ["ruff", "check", "--select=E"]
    missing = assess_profile_audit(manifest, plan, _result())

    assert _checks(selected)[0]["status"] == "executed"
    assert selected["status"] == "complete"
    assert _checks(missing)[0]["status"] == "selector_mismatch"
    assert missing["status"] == "incomplete"


def test_preflight_failure_marks_all_manifest_checks_incomplete() -> None:
    manifest = _manifest()

    assessment = assess_profile_audit(
        manifest,
        None,
        None,
        unavailable_reason="missing policy",
    )

    assert assessment["status"] == "incomplete"
    assert _checks(assessment)[0]["status"] == "incomplete"
    assert assessment.get("reason") == "missing policy"


def test_manifest_rejects_parent_traversal() -> None:
    manifest_file = Path("../outside.py")
    with pytest.raises(ValueError, match="canonical relative POSIX paths"):
        _manifest(expected_files=(manifest_file.as_posix(),))


@pytest.mark.parametrize(
    ("intent_status", "failure_kind", "expected"),
    [
        ("not_selected", None, "not_selected"),
        ("disabled", None, "disabled"),
        ("unsupported", "unsupported_capability", "unsupported"),
        ("not_applicable", "no_matching_files", "empty_inventory"),
        ("failed", "violation", "executed_with_findings"),
        ("failed", "operational_error", "execution_failure"),
        ("failed", None, "incomplete"),
        ("failed", "unrecognized", "incomplete"),
        ("passed", "violation", "incomplete"),
        ("running", None, "incomplete"),
        ("passed", None, "executed_zero"),
    ],
)
def test_manifest_uses_explicit_intent_completion_states(
    intent_status: str, failure_kind: str | None, expected: str
) -> None:
    selectors = AuditPlanIntent(
        rule_id="alphus/python/none/testing/example",
        language="python",
        native_rule="ANN",
        step="Source review",
    )
    manifest = _manifest(
        rule_id=selectors["rule_id"],
        language=selectors["language"],
        native_rule=selectors["native_rule"],
    )
    plan = _plan()
    plan["intents"] = [selectors]
    result = _result(status="failed" if intent_status == "failed" else "passed")
    result["intent_bindings"] = [
        {
            "rule_id": selectors["rule_id"],
            "language": selectors["language"],
            "native_rule": selectors["native_rule"],
            "status": intent_status,
            "failure_kind": failure_kind,
            "step": "Source review",
        }
    ]

    assessment = assess_profile_audit(manifest, plan, result)

    assert _checks(assessment)[0]["status"] == expected
    assert assessment["status"] == (
        "complete"
        if expected in {"executed_zero", "executed_with_findings"}
        else "incomplete"
    )


@pytest.mark.parametrize("mismatch_source", ["plan", "result"])
def test_intent_bound_to_another_step_cannot_satisfy_manifest(
    mismatch_source: str,
) -> None:
    selectors = AuditPlanIntent(
        rule_id="alphus/python/none/testing/example",
        language="python",
        native_rule="ANN",
        step="Other review",
    )
    manifest = _manifest(
        rule_id=selectors["rule_id"],
        language=selectors["language"],
        native_rule=selectors["native_rule"],
    )
    plan = _plan()
    result = _result()
    if mismatch_source == "plan":
        plan["intents"] = [selectors]
    else:
        selectors["step"] = "Source review"
        plan["intents"] = [selectors]
        result["intent_bindings"] = [
            {
                "rule_id": selectors["rule_id"],
                "language": selectors["language"],
                "native_rule": selectors["native_rule"],
                "status": "passed",
                "failure_kind": None,
                "step": "Other review",
            }
        ]

    assessment = assess_profile_audit(manifest, plan, result)

    assert assessment["status"] == "incomplete"
    assert _checks(assessment)[0]["status"] == "scope_mismatch"
