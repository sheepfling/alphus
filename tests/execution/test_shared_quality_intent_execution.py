"""Native intent outcomes preserve status distinctions and tool evidence."""

from __future__ import annotations

import json
import subprocess
from io import StringIO
from pathlib import Path
from typing import Literal, NotRequired, TypedDict

import pytest

from alphus.config import (
    CommandRunStep,
    FileInventoryPolicy,
    NativeCapabilityBinding,
    OrchestrationPolicy,
    OrchestrationProfile,
    RuleRunStep,
    SharedQualityIntent,
)
from alphus.execution.orchestration import run_orchestration


class _StepReport(TypedDict):
    status: str
    exit_code: int | None
    stdout: str
    stderr: str
    findings: list[object]


class _IntentBindingReport(TypedDict):
    rule_id: str
    language: str
    backend: str
    native_rule: str
    status: str
    failure_kind: str | None


class _ExecutionReport(TypedDict):
    profile: str
    passed: int
    failed: int
    disabled: NotRequired[int]
    unsupported: NotRequired[int]
    steps: list[_StepReport]
    intent_bindings: NotRequired[list[_IntentBindingReport]]


def _intent(
    *,
    mapping: Literal["exact", "unsupported"] = "exact",
    rollout: Literal["mainline", "provisional"] = "mainline",
    required: bool = True,
    enabled: bool = True,
    language_enabled: bool | None = None,
    extra_binding_language: Literal["cpp"] | None = None,
    step: str | None = "Native complexity",
    language: Literal["python", "cpp"] = "python",
    evidence_format: Literal["raw", "json-array", "json-object"] = "raw",
    exit_codes: tuple[int, ...] = (1,),
    config_codes: tuple[int, ...] = (2,),
) -> SharedQualityIntent:
    binding = NativeCapabilityBinding(
        language=language,
        backend="sample-linter",
        version_range=">=1,<2",
        native_rule="complexity",
        metric="cyclomatic_complexity",
        unit="decision_paths",
        count_method="Count each decision path starting at one.",
        mapping=mapping,
        step=step,
        evidence_format=evidence_format,
        supported_options=("max-complexity",),
        threshold_option="max-complexity",
        effective_configuration=(("max-complexity", 10),),
        violation_exit_codes=exit_codes,
        configuration_exit_codes=config_codes,
    )
    bindings = (binding,)
    if extra_binding_language is not None:
        extra_binding = binding.model_copy(update={"language": extra_binding_language})
        bindings = (binding, extra_binding)
    return SharedQualityIntent(
        rule_id="alphus/any/none/maintainability/function-complexity-review",
        summary="Review functions that exceed a local complexity limit.",
        metric="cyclomatic_complexity",
        unit="decision_paths",
        count_method="Count each decision path starting at one.",
        threshold=10,
        enabled=enabled,
        required=required,
        rollout=rollout,
        profiles=("check",),
        files=FileInventoryPolicy(include=("**/*.py",), exclude=()),
        overrides=(
            ({"language": language, "enabled": language_enabled},)
            if language_enabled is not None
            else ()
        ),
        bindings=bindings,
    )


def _policy(
    tmp_path: Path,
    *,
    exit_code: int = 0,
    intent: SharedQualityIntent | None = None,
    timeout_seconds: float | None = None,
    command: tuple[str, ...] | None = None,
    with_source: bool = True,
) -> OrchestrationPolicy:
    (tmp_path / "quality.toml").write_text("schema_version = 1\n", encoding="utf-8")
    if not (tmp_path / ".git").exists():
        subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    if with_source:
        (tmp_path / "sample.py").write_text("x = 1\n", encoding="utf-8")
    argv = command or (
        "{python}",
        "-c",
        (
            "import sys; "
            "print('native stdout'); "
            "print('native stderr', file=sys.stderr); "
            f"raise SystemExit({exit_code})"
        ),
    )
    command_step = CommandRunStep(
        kind="command",
        name="Native complexity",
        argv=(*argv, "{files}"),
        files=FileInventoryPolicy(include=("**/*.py",), exclude=()),
        timeout_seconds=timeout_seconds,
        rollout="provisional"
        if intent and intent.rollout == "provisional"
        else "mainline",
    )
    return OrchestrationPolicy(
        steps=(command_step,),
        profiles=(
            OrchestrationProfile(name="check", steps=(command_step.name,)),
            OrchestrationProfile(name="aggregate", includes=("check",)),
        ),
        intents=(intent,) if intent else (),
    )


def _run(
    tmp_path: Path, policy: OrchestrationPolicy, profile_name: str = "check"
) -> tuple[int, _ExecutionReport]:
    output = StringIO()
    errors = StringIO()
    code = run_orchestration(
        tmp_path,
        tmp_path / "quality.toml",
        policy,
        profile_name,
        lambda _: 0,
        json_output=True,
        stdout=output,
        stderr=errors,
    )
    return code, json.loads(output.getvalue())


@pytest.mark.parametrize(
    ("native_exit", "failure_kind"),
    [(1, "violation"), (2, "configuration_error"), (9, "operational_error")],
)
def test_intent_failure_kinds_link_semantic_identity_to_raw_tool_evidence(
    tmp_path: Path, native_exit: int, failure_kind: str
) -> None:
    policy = _policy(tmp_path, exit_code=native_exit, intent=_intent())
    code, report = _run(tmp_path, policy)

    assert code == 1
    binding = report["intent_bindings"][0]
    assert binding["rule_id"] == (
        "alphus/any/none/maintainability/function-complexity-review"
    )
    assert binding["native_rule"] == "complexity"
    assert binding["status"] == "failed"
    assert binding["failure_kind"] == failure_kind
    assert binding["evidence_step"] == "Native complexity"
    evidence = report["steps"][0]
    assert evidence["stdout"] == "native stdout\n"
    assert evidence["stderr"].startswith("native stderr\n")


def test_missing_tool_is_operational_failure_not_a_clean_intent(
    tmp_path: Path,
) -> None:
    policy = _policy(
        tmp_path,
        intent=_intent(exit_codes=(127,)),
        command=("tool-that-does-not-exist-alphus-test",),
    )
    code, report = _run(tmp_path, policy)

    assert code == 1
    assert report["intent_bindings"][0]["failure_kind"] == "operational_error"
    assert report["intent_bindings"][0]["status"] == "failed"
    assert "tool-that-does-not-exist-alphus-test" in report["steps"][0]["stderr"]


def test_intent_profile_is_selected_through_an_included_profile(
    tmp_path: Path,
) -> None:
    policy = _policy(tmp_path, intent=_intent())
    code, report = _run(tmp_path, policy, "aggregate")

    assert code == 0
    assert report["profile"] == "aggregate"
    assert report["intent_bindings"][0]["status"] == "passed"


@pytest.mark.parametrize(
    ("enabled", "language_enabled"), [(False, None), (True, False)]
)
def test_disabled_intent_does_not_execute_its_native_command(
    tmp_path: Path, enabled: bool, language_enabled: bool | None
) -> None:
    marker = tmp_path / "native-command-ran"
    policy = _policy(
        tmp_path,
        intent=_intent(enabled=enabled, language_enabled=language_enabled),
        command=(
            "{python}",
            "-c",
            (
                "from pathlib import Path; "
                f"Path({str(marker)!r}).write_text('ran'); "
                "raise SystemExit(1)"
            ),
        ),
    )

    code, report = _run(tmp_path, policy)

    assert code == 0
    assert not marker.exists()
    assert report["passed"] == 0
    assert report["failed"] == 0
    assert report["disabled"] == 1
    assert report["steps"][0]["status"] == "disabled"
    assert report["steps"][0]["exit_code"] is None
    assert report["intent_bindings"][0]["status"] == "disabled"


def test_shared_native_command_runs_when_another_selected_binding_is_enabled(
    tmp_path: Path,
) -> None:
    marker = tmp_path / "native-command-ran"
    policy = _policy(
        tmp_path,
        intent=_intent(language_enabled=False, extra_binding_language="cpp"),
        command=(
            "{python}",
            "-c",
            f"from pathlib import Path; Path({str(marker)!r}).write_text('ran')",
        ),
    )

    code, report = _run(tmp_path, policy)

    assert code == 0
    assert marker.read_text(encoding="utf-8") == "ran"
    assert report.get("disabled", 0) == 0
    assert report["steps"][0]["status"] == "passed"
    bindings = {item["language"]: item for item in report["intent_bindings"]}
    assert bindings["python"]["status"] == "disabled"
    assert bindings["cpp"]["status"] == "passed"


@pytest.mark.parametrize(
    ("output", "expected_status", "expected_failure_kind", "expected_code"),
    [
        ("[]", "passed", None, 0),
        ("not valid json", "failed", "operational_error", 1),
        ('{"diagnostics": []}', "failed", "operational_error", 1),
        ("[NaN]", "failed", "operational_error", 1),
    ],
)
def test_declared_json_evidence_is_validated_without_rewriting_raw_output(
    tmp_path: Path,
    output: str,
    expected_status: str,
    expected_failure_kind: str | None,
    expected_code: int,
) -> None:
    policy = _policy(
        tmp_path,
        intent=_intent(evidence_format="json-array", exit_codes=(127,)),
        command=("{python}", "-c", f"print({output!r})"),
    )
    code, report = _run(tmp_path, policy)

    assert code == expected_code
    binding = report["intent_bindings"][0]
    assert binding["status"] == expected_status
    assert binding["failure_kind"] == expected_failure_kind
    assert report["steps"][0]["stdout"] == f"{output}\n"
    if expected_failure_kind:
        assert "command-output-invalid" in str(report["steps"][0]["findings"])


@pytest.mark.parametrize(
    ("output", "expected_status", "expected_failure_kind", "expected_code"),
    [
        ('{"diagnostics": []}', "passed", None, 0),
        ("[]", "failed", "operational_error", 1),
        ("not valid json", "failed", "operational_error", 1),
    ],
)
def test_declared_json_object_evidence_is_validated_without_rewriting_raw_output(
    tmp_path: Path,
    output: str,
    expected_status: str,
    expected_failure_kind: str | None,
    expected_code: int,
) -> None:
    policy = _policy(
        tmp_path,
        intent=_intent(evidence_format="json-object", exit_codes=(127,)),
        command=("{python}", "-c", f"print({output!r})"),
    )

    code, report = _run(tmp_path, policy)

    assert code == expected_code
    binding = report["intent_bindings"][0]
    assert binding["status"] == expected_status
    assert binding["failure_kind"] == expected_failure_kind
    assert report["steps"][0]["stdout"] == f"{output}\n"
    if expected_failure_kind:
        assert "expected a valid JSON object on stdout" in str(
            report["steps"][0]["stderr"]
        )


def test_command_timeout_is_operational_failure_with_partial_output(
    tmp_path: Path,
) -> None:
    policy = _policy(
        tmp_path,
        intent=_intent(exit_codes=(127,)),
        timeout_seconds=0.1,
        command=(
            "{python}",
            "-c",
            "import sys,time; print('before timeout', flush=True); time.sleep(2)",
        ),
    )
    code, report = _run(tmp_path, policy)

    assert code == 1
    assert report["intent_bindings"][0]["failure_kind"] == "operational_error"
    assert report["steps"][0]["stdout"] == "before timeout\n"
    assert "timed out after 0.1 seconds" in report["steps"][0]["stderr"]


def test_empty_inventory_is_reported_separately_from_success(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    intent = _intent()
    policy = _policy(tmp_path, intent=intent, with_source=False)
    code, report = _run(tmp_path, policy)

    assert code == 0
    assert report["steps"][0]["status"] == "not_applicable"
    assert report["intent_bindings"][0]["status"] == "not_applicable"
    assert report["intent_bindings"][0]["failure_kind"] == "no_matching_files"


@pytest.mark.parametrize(
    ("rollout", "required", "expected_code"),
    [("provisional", True, 0), ("mainline", False, 0), ("mainline", True, 1)],
)
def test_unsupported_capabilities_are_explicit_and_only_required_mainline_blocks(
    tmp_path: Path,
    rollout: Literal["mainline", "provisional"],
    required: bool,
    expected_code: int,
) -> None:
    (tmp_path / "quality.toml").write_text("schema_version = 1\n", encoding="utf-8")
    unsupported = _intent(
        mapping="unsupported",
        rollout=rollout,
        required=required,
        step=None,
        language="cpp",
    )
    unused_step = RuleRunStep(kind="rule", name="Other", rule="line-length")
    policy = OrchestrationPolicy(
        steps=(unused_step,),
        profiles=(OrchestrationProfile(name="check", steps=("Other",)),),
        intents=(unsupported,),
    )
    output = StringIO()
    code = run_orchestration(
        tmp_path,
        tmp_path / "quality.toml",
        policy,
        "check",
        lambda _: 0,
        json_output=True,
        stdout=output,
        stderr=StringIO(),
    )
    report = json.loads(output.getvalue())

    assert code == expected_code
    assert report["unsupported"] == 1
    assert report["intent_bindings"][0]["status"] == "unsupported"
    assert report["intent_bindings"][0]["failure_kind"] == "unsupported_capability"
    synthetic = next(
        step for step in report["steps"] if step["status"] == "unsupported"
    )
    assert synthetic["findings"][0]["severity"] == (
        "error" if expected_code else "warning"
    )
