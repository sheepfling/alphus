"""Run a policy-selected quality profile through Python orchestration."""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import asdict
from io import StringIO
from pathlib import Path
from typing import Literal, NoReturn, TextIO, TypeGuard, cast

from alphus.config import (
    CommandRunStep,
    OrchestrationPolicy,
    QualityGateConfig,
    QualityRuleName,
    RuleRunStep,
    load_config,
)
from alphus.contracts.findings import (
    Diagnostic,
    FindingRollups,
    SeverityCounts,
    severity_meets_threshold,
)
from alphus.contracts.process import ExitCode
from alphus.contracts.rule_tags import (
    NAMESPACE,
    PRODUCT_NAME,
    Category,
    Framework,
    Scope,
    rule_tag,
)
from alphus.execution.parallel import StepExecution, run_profile_steps
from alphus.execution.profile_history import (
    capture_profile_context,
    latest_profile_record,
    write_profile_record,
)
from alphus.execution.profile_reporting import ProfileReporter
from alphus.execution.profile_results import (
    IntentExecutionResult,
    IntentStatus,
    OrchestrationResult,
    OrchestrationStepResult,
    StepStatus,
)
from alphus.execution.step_results import RuleRunResult
from alphus.policy.intents import (
    EvidenceFormat,
    EvidenceStream,
    FailureKind,
    IntentMapping,
    ResolvedIntentBinding,
    resolve_intent_bindings,
)
from alphus.support.data_access import JsonValue, validate_json_value

_ORCHESTRATION_CATEGORY = Category.ORCHESTRATION
_RULE_EXECUTION_FAILED = rule_tag(
    Scope.ANY, Framework.NONE, _ORCHESTRATION_CATEGORY, "rule-execution-failed"
)
_COMMAND_EXITED_NONZERO = rule_tag(
    Scope.ANY, Framework.NONE, _ORCHESTRATION_CATEGORY, "command-exited-nonzero"
)
_COMMAND_LAUNCH_FAILED = rule_tag(
    Scope.ANY, Framework.NONE, _ORCHESTRATION_CATEGORY, "command-launch-failed"
)
_COMMAND_TIMED_OUT = rule_tag(
    Scope.ANY, Framework.NONE, _ORCHESTRATION_CATEGORY, "command-timed-out"
)
_COMMAND_OUTPUT_INVALID = rule_tag(
    Scope.ANY, Framework.NONE, _ORCHESTRATION_CATEGORY, "command-output-invalid"
)
_UNSUPPORTED_CAPABILITY = rule_tag(
    Scope.ANY, Framework.NONE, _ORCHESTRATION_CATEGORY, "unsupported-capability"
)
_STATUS_DISABLED = "disabled"
_STATUS_NOT_APPLICABLE = "not_applicable"
_STATUS_UNSUPPORTED = "unsupported"
_UNSUPPORTED_MAPPING: IntentMapping = _STATUS_UNSUPPORTED
_MAINLINE_ROLLOUT: Literal["mainline", "provisional"] = "mainline"
_PROVISIONAL_ROLLOUT: Literal["mainline", "provisional"] = "provisional"
_JSON_ARRAY_EVIDENCE_FORMAT: EvidenceFormat = "json-array"


def _legacy_diagnostic_line(diagnostic: Diagnostic) -> str:
    """Keep the existing string diagnostics field useful for older consumers."""
    location = diagnostic.path or ""
    if diagnostic.line is not None:
        location = f"{location}:{diagnostic.line}" if location else str(diagnostic.line)
    prefix = "" if diagnostic.severity == "error" else f"{diagnostic.severity.upper()} "
    if location:
        return f"{prefix}{location}: {diagnostic.message}"
    return f"{prefix}{diagnostic.message}"


def _is_structured_rule_result(
    value: int | RuleRunResult,
) -> TypeGuard[RuleRunResult]:
    """Narrow the public legacy integer and structured rule result union."""
    return isinstance(value, RuleRunResult)


def _timeout_output(value: bytes | str | None) -> str:
    """Normalize partial subprocess output returned after a timeout."""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value or ""


def _raise_work_error(error: Exception) -> NoReturn:
    """Preserve timeout output while reporting other unit failures."""
    match error:
        case subprocess.TimeoutExpired():
            raise error
        case _:
            raise OSError(str(error)) from error


def _matches_json_evidence_format(
    value: JsonValue, evidence_format: EvidenceFormat
) -> bool:
    """Check decoded JSON by the selected top-level container protocol."""
    if evidence_format == "raw":
        return True
    match value:
        case list():
            return evidence_format == _JSON_ARRAY_EVIDENCE_FORMAT
        case dict():
            return evidence_format == "json-object"
        case _:
            return False


def run_orchestration(
    root: Path,
    config_path: Path,
    policy: OrchestrationPolicy,
    profile_name: str,
    run_rule: Callable[[QualityRuleName], int | RuleRunResult],
    *,
    json_output: bool = False,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    jobs: int | None = None,
    verbose: bool = False,
    config: QualityGateConfig | None = None,
    history_dir: Path | None = None,
    consumer_id: str | None = None,
) -> int:
    """Run every configured profile step and summarize all outcomes."""
    checkout = root.resolve(strict=True)
    resolved_config = config_path.resolve(strict=True)
    output = stdout if stdout is not None else sys.stdout
    errors = stderr if stderr is not None else sys.stderr
    reporter = ProfileReporter(output, errors, json_output=json_output)
    profile = policy.profile(profile_name)
    plan = policy.resolve_profile(profile_name)
    if profile is None or plan is None:
        reporter.error(f"Unknown orchestration profile: {profile_name}")
        return ExitCode.CONFIG_ERROR

    max_jobs = jobs if jobs is not None else policy.execution.max_jobs
    if not 1 <= max_jobs <= 64:
        reporter.error("--jobs must be between 1 and 64")
        return ExitCode.CONFIG_ERROR
    if policy.execution.prioritize_previous_failures and history_dir is None:
        reporter.error("previous failure priority requires --history-dir")
        return ExitCode.CONFIG_ERROR
    if consumer_id is not None and history_dir is None:
        reporter.error("consumer identity requires --history-dir")
        return ExitCode.CONFIG_ERROR
    history_context = None
    previous_failures: frozenset[str] = frozenset()
    if history_dir is not None:
        try:
            loaded_config = (
                config if config is not None else load_config(resolved_config)
            )
            history_context = capture_profile_context(
                checkout, profile_name, loaded_config, consumer_id=consumer_id
            )
            if policy.execution.prioritize_previous_failures:
                previous = latest_profile_record(
                    history_dir,
                    checkout,
                    profile_name,
                    config_sha256=history_context.config_sha256,
                    consumer_id=consumer_id,
                    match_consumer_id=True,
                )
                if previous is not None:
                    previous_failures = frozenset(previous.failed_steps)
        except (OSError, ValueError) as error:
            reporter.error(f"Cannot read profile history: {error}")
            return ExitCode.CONFIG_ERROR
    selected_steps = {step.name: step for step in policy.steps}
    parallel_results: dict[str, StepExecution] = {}
    step_durations_seconds: dict[str, float] = {}
    work_unit_durations_seconds: dict[str, float] = {}

    failed = 0
    provisional_passed = 0
    provisional_failed = 0
    not_applicable = 0
    disabled = 0
    completed = 0
    results: list[OrchestrationStepResult] = []
    all_findings: list[Diagnostic] = []
    output_invalid_steps: set[str] = set()
    operational_error_steps: set[str] = set()
    threshold = policy.failure_threshold
    active_profiles = set(plan.profiles)
    resolved_intents = resolve_intent_bindings(policy.intents, threshold)
    intent_bindings_by_step: dict[str, list[ResolvedIntentBinding]] = {}
    for item in resolved_intents:
        binding = item.binding
        if binding.step is not None:
            intent_bindings_by_step.setdefault(binding.step, []).append(item)
    json_evidence_by_step: dict[str, tuple[EvidenceFormat, EvidenceStream]] = {
        item.binding.step: (
            item.binding.evidence_format,
            item.binding.evidence_stream,
        )
        for item in resolved_intents
        if item.enabled
        and active_profiles.intersection(item.intent.profiles)
        and item.binding.mapping != _UNSUPPORTED_MAPPING
        and item.binding.evidence_format != "raw"
        and item.binding.step in plan.steps
    }
    if profile.includes:
        reporter.selected_profiles(plan.profiles)
    for index, step_name in enumerate(plan.steps):
        step: RuleRunStep | CommandRunStep = selected_steps[step_name]
        reporter.step_started(step.name)
        active_bindings = [
            item
            for item in intent_bindings_by_step.get(step_name, ())
            if active_profiles.intersection(item.intent.profiles)
        ]
        if active_bindings and not any(item.enabled for item in active_bindings):
            disabled += 1
            completed += 1
            results.append(
                OrchestrationStepResult(
                    name=step.name,
                    status=StepStatus.DISABLED,
                    exit_code=None,
                    diagnostics=(
                        "All selected intent bindings for this step are disabled.",
                    ),
                    rollout=step.rollout,
                )
            )
            reporter.step_disabled(step.name)
            continue
        if step_name not in parallel_results:
            block: list[RuleRunStep | CommandRunStep] = [step]
            if max_jobs > 1 and step.parallel:
                for later_name in plan.steps[index + 1 :]:
                    later = selected_steps[later_name]
                    later_bindings = [
                        item
                        for item in intent_bindings_by_step.get(later_name, ())
                        if active_profiles.intersection(item.intent.profiles)
                    ]
                    if not later.parallel or (
                        later_bindings
                        and not any(item.enabled for item in later_bindings)
                    ):
                        break
                    block.append(later)
            try:
                parallel_results.update(
                    run_profile_steps(
                        checkout,
                        resolved_config,
                        config if config is not None else load_config(resolved_config),
                        block,
                        max_jobs,
                        run_rule=run_rule,
                        verbose=verbose,
                        previously_failed=previous_failures,
                    )
                )
            except (OSError, ValueError) as error:
                reporter.error(f"Cannot schedule quality work: {error}")
                return ExitCode.CONFIG_ERROR
        precomputed = parallel_results.pop(step_name)
        step_durations_seconds[step.name] = precomputed.duration_seconds
        work_unit_durations_seconds.update(precomputed.work_unit_durations)
        captured_stdout = StringIO()
        captured_stderr = StringIO()
        step_stdout = ""
        step_stderr = ""
        # opaque-boundary: Preserve the selected rule's backend report for output.
        step_report: Mapping[str, object] | None = None
        findings: list[Diagnostic] = []
        skipped_empty_file_scope = False
        legacy_diagnostics: tuple[str, ...] = ()
        attempted_command: str | None = None
        exit_code = ExitCode.LAUNCH_ERROR
        try:
            match step:
                case RuleRunStep():
                    rule_result: int | RuleRunResult
                    if precomputed.error is not None:
                        _raise_work_error(precomputed.error)
                    if precomputed.rule is None:
                        raise ValueError("quality rule returned no result")
                    rule_result = precomputed.rule
                    captured_stdout.write(precomputed.stdout)
                    captured_stderr.write(precomputed.stderr)
                    if _is_structured_rule_result(rule_result):
                        findings = list(rule_result.findings)
                        if step.severity is not None or step.priority is not None:
                            findings = [
                                Diagnostic(
                                    source=item.source,
                                    rule_id=item.rule_id,
                                    message=item.message,
                                    severity=(
                                        step.severity
                                        if step.severity is not None
                                        else item.severity
                                    ),
                                    path=item.path,
                                    line=item.line,
                                    priority=step.priority or item.priority,
                                    _rule_tag=item.tag,
                                )
                                for item in findings
                            ]
                        legacy_diagnostics = tuple(
                            _legacy_diagnostic_line(finding) for finding in findings
                        )
                        step_stderr = rule_result.stderr or captured_stderr.getvalue()
                        step_stdout = rule_result.stdout or captured_stdout.getvalue()
                        step_report = rule_result.report
                        if rule_result.execution_failure is not None:
                            message = rule_result.execution_failure
                            findings.append(
                                Diagnostic(
                                    source=NAMESPACE,
                                    rule_id=_RULE_EXECUTION_FAILED,
                                    message=message,
                                )
                            )
                            exit_code = rule_result.exit_code or ExitCode.CONFIG_ERROR
                            legacy_diagnostics = (message,)
                        elif rule_result.exit_code not in {
                            ExitCode.SUCCESS,
                            ExitCode.QUALITY_FAILURE,
                        }:
                            message = (
                                f"{PRODUCT_NAME} rule execution failed with exit code "
                                f"{rule_result.exit_code}"
                            )
                            findings.append(
                                Diagnostic(
                                    source=NAMESPACE,
                                    rule_id=_RULE_EXECUTION_FAILED,
                                    message=message,
                                )
                            )
                            exit_code = rule_result.exit_code
                            legacy_diagnostics = (message,)
                        elif (
                            rule_result.exit_code == ExitCode.QUALITY_FAILURE
                            and not rule_result.findings
                        ):
                            message = f"{PRODUCT_NAME} rule failed without structured findings."
                            findings.append(
                                Diagnostic(
                                    source=NAMESPACE,
                                    rule_id=_RULE_EXECUTION_FAILED,
                                    message=message,
                                )
                            )
                            exit_code = ExitCode.CONFIG_ERROR
                            legacy_diagnostics = (message,)
                        else:
                            exit_code = (
                                ExitCode.QUALITY_FAILURE
                                if any(
                                    severity_meets_threshold(
                                        finding.severity, threshold
                                    )
                                    for finding in findings
                                )
                                else ExitCode.SUCCESS
                            )
                    else:
                        exit_code = cast(int, rule_result)
                        step_stdout = captured_stdout.getvalue()
                        step_stderr = captured_stderr.getvalue()
                        if exit_code != ExitCode.SUCCESS:
                            raw_lines = tuple(
                                line
                                for captured in (captured_stdout, captured_stderr)
                                for line in captured.getvalue().splitlines()
                            )
                            legacy_diagnostics = raw_lines or (
                                f"rule runner exited with status {exit_code}",
                            )
                            findings.append(
                                Diagnostic(
                                    source=NAMESPACE,
                                    rule_id=_RULE_EXECUTION_FAILED,
                                    message=f"rule runner exited with status {exit_code}",
                                )
                            )
                case CommandRunStep():
                    attempted_command = precomputed.attempted_command
                    if precomputed.error is not None:
                        _raise_work_error(precomputed.error)
                    if precomputed.not_applicable:
                        skipped_empty_file_scope = True
                        exit_code = ExitCode.SUCCESS
                    else:
                        if precomputed.command is None:
                            raise ValueError("quality command returned no result")
                        result = precomputed.command
                        exit_code = result.returncode
                        step_stdout = result.stdout or ""
                        step_stderr = result.stderr or ""
                        evidence_contract = json_evidence_by_step.get(step.name)
                        if evidence_contract is not None:
                            evidence_format, evidence_stream = evidence_contract
                            expected_shape = (
                                "JSON array"
                                if evidence_format == _JSON_ARRAY_EVIDENCE_FORMAT
                                else "JSON object"
                            )
                            evidence = (
                                step_stdout
                                if evidence_stream == "stdout"
                                else step_stderr
                            )
                            try:
                                parsed_evidence = validate_json_value(evidence)
                                if not _matches_json_evidence_format(
                                    parsed_evidence, evidence_format
                                ):
                                    raise TypeError(
                                        f"expected a top-level {expected_shape}"
                                    )
                            except (
                                json.JSONDecodeError,
                                ValueError,
                                TypeError,
                                RecursionError,
                            ):
                                output_invalid_steps.add(step.name)
                                operational_error_steps.add(step.name)
                                message = (
                                    f"{step.name}: expected a valid {expected_shape} on "
                                    f"{evidence_stream}"
                                )
                                step_stderr = f"{step_stderr}{message}\n"
                                legacy_diagnostics = (message,)
                                findings.append(
                                    Diagnostic(
                                        source=step.name,
                                        rule_id=_COMMAND_OUTPUT_INVALID,
                                        message=message,
                                    )
                                )
                                exit_code = ExitCode.LAUNCH_ERROR
                        if result.returncode != ExitCode.SUCCESS:
                            legacy_diagnostics = tuple(
                                line
                                for captured in (step_stdout, step_stderr)
                                for line in captured.splitlines()
                            )
                            findings.append(
                                Diagnostic(
                                    source=step.name,
                                    rule_id=_COMMAND_EXITED_NONZERO,
                                    message=(
                                        f"command exited with status {result.returncode}"
                                    ),
                                )
                            )
                        elif step.name in output_invalid_steps:
                            invalid_format, invalid_stream = json_evidence_by_step[
                                step.name
                            ]
                            invalid_shape = (
                                "JSON array"
                                if invalid_format == _JSON_ARRAY_EVIDENCE_FORMAT
                                else "JSON object"
                            )
                            invalid_message = (
                                f"{step.name}: expected a valid {invalid_shape} "
                                f"on {invalid_stream}"
                            )
                            legacy_diagnostics = (invalid_message,)
        except subprocess.TimeoutExpired as error:
            operational_error_steps.add(step.name)
            step_stdout = _timeout_output(error.stdout)
            step_stderr = _timeout_output(error.stderr)
            timeout = (
                f" after {step.timeout_seconds} seconds"
                if isinstance(step, CommandRunStep) and step.timeout_seconds is not None
                else ""
            )
            message = f"{step.name}: command timed out{timeout}"
            step_stderr = f"{step_stderr}{message}\n"
            legacy_diagnostics = (message,)
            findings.append(
                Diagnostic(
                    source=NAMESPACE if isinstance(step, RuleRunStep) else step.name,
                    rule_id=(
                        _RULE_EXECUTION_FAILED
                        if isinstance(step, RuleRunStep)
                        else _COMMAND_TIMED_OUT
                    ),
                    message=message,
                )
            )
            exit_code = ExitCode.LAUNCH_ERROR
        except (OSError, ValueError, subprocess.CalledProcessError) as error:
            operational_error_steps.add(step.name)
            detail = str(error)
            if attempted_command is not None and attempted_command not in detail:
                detail = f"{attempted_command}: {detail}"
            message = f"{step.name}: {detail}"
            captured_stderr.write(f"{message}\n")
            step_stderr = captured_stderr.getvalue()
            legacy_diagnostics = (message,)
            findings.append(
                Diagnostic(
                    source=NAMESPACE if isinstance(step, RuleRunStep) else step.name,
                    rule_id=(
                        _RULE_EXECUTION_FAILED
                        if isinstance(step, RuleRunStep)
                        else _COMMAND_LAUNCH_FAILED
                    ),
                    message=message,
                )
            )
            exit_code = ExitCode.LAUNCH_ERROR

        completed += 1
        provisional = step.rollout == _PROVISIONAL_ROLLOUT
        if skipped_empty_file_scope:
            not_applicable += 1
            results.append(
                OrchestrationStepResult(
                    step.name,
                    StepStatus.NOT_APPLICABLE,
                    exit_code,
                    diagnostics=("No files matched the configured command scope.",),
                    rollout=step.rollout,
                )
            )
        elif exit_code == ExitCode.SUCCESS:
            if provisional:
                provisional_passed += 1
            results.append(
                OrchestrationStepResult(
                    step.name,
                    StepStatus.PASSED,
                    exit_code,
                    diagnostics=legacy_diagnostics,
                    findings=tuple(findings),
                    stdout=step_stdout,
                    stderr=step_stderr,
                    severity_counts=SeverityCounts.from_diagnostics(findings),
                    rollout=step.rollout,
                    report=step_report,
                )
            )
            all_findings.extend(findings)
        else:
            if provisional:
                provisional_failed += 1
            else:
                failed += 1
            results.append(
                OrchestrationStepResult(
                    step.name,
                    StepStatus.FAILED,
                    exit_code,
                    diagnostics=legacy_diagnostics,
                    findings=tuple(findings),
                    stdout=step_stdout,
                    stderr=step_stderr,
                    severity_counts=SeverityCounts.from_diagnostics(findings),
                    rollout=step.rollout,
                    report=step_report,
                )
            )
            all_findings.extend(findings)
        reporter.step_completed(results[-1], rule=isinstance(step, RuleRunStep))

    intent_results: list[IntentExecutionResult] = []
    unsupported_count = 0
    blocking_unsupported = False
    step_results = {result.name: result for result in results}
    for item in resolved_intents:
        intent = item.intent
        binding = item.binding
        if not item.enabled:
            intent_results.append(
                IntentExecutionResult(
                    intent.rule_id,
                    binding.language,
                    binding.backend,
                    binding.native_rule,
                    binding.mapping,
                    IntentStatus.DISABLED,
                    required=intent.required,
                    severity=item.severity,
                    failure_threshold=item.failure_threshold,
                    threshold=item.threshold,
                    step=binding.step,
                )
            )
            continue
        if not active_profiles.intersection(intent.profiles):
            status = IntentStatus.NOT_SELECTED
            failure_kind = None
            step_result = None
        elif binding.mapping == _UNSUPPORTED_MAPPING:
            status = IntentStatus.UNSUPPORTED
            failure_kind = FailureKind.UNSUPPORTED_CAPABILITY
            step_result = None
            unsupported_count += 1
            blocking = intent.required and intent.rollout == _MAINLINE_ROLLOUT
            blocking_unsupported = blocking_unsupported or blocking
            message = (
                f"{intent.rule_id} has no supported {binding.language} mapping "
                f"for {binding.metric} ({binding.unit})"
            )
            finding = Diagnostic(
                source=NAMESPACE,
                rule_id=_UNSUPPORTED_CAPABILITY,
                message=message,
                severity="error" if blocking else "warning",
            )
            results.append(
                OrchestrationStepResult(
                    name=f"unsupported capability: {intent.rule_id} [{binding.language}]",
                    status=StepStatus.UNSUPPORTED,
                    exit_code=ExitCode.CONFIG_ERROR,
                    diagnostics=(message,),
                    findings=(finding,),
                    severity_counts=SeverityCounts.from_diagnostics((finding,)),
                    rollout=intent.rollout,
                )
            )
            completed += 1
            all_findings.append(finding)
            reporter.unsupported(message, blocking=blocking)
        elif binding.step not in plan.steps:
            status = IntentStatus.NOT_SELECTED
            failure_kind = None
            step_result = None
        else:
            step_result = step_results.get(binding.step or "")
            if step_result is None:
                status = IntentStatus.FAILED
                failure_kind = FailureKind.OPERATIONAL_ERROR
            elif step_result.status == StepStatus.NOT_APPLICABLE:
                status = IntentStatus.NOT_APPLICABLE
                failure_kind = FailureKind.NO_MATCHING_FILES
            elif step_result.status == StepStatus.PASSED:
                status = IntentStatus.PASSED
                failure_kind = None
            elif binding.step in operational_error_steps:
                status = IntentStatus.FAILED
                failure_kind = FailureKind.OPERATIONAL_ERROR
            elif step_result.exit_code in binding.violation_exit_codes:
                status = IntentStatus.FAILED
                failure_kind = FailureKind.VIOLATION
            elif step_result.exit_code in binding.configuration_exit_codes:
                status = IntentStatus.FAILED
                failure_kind = FailureKind.CONFIGURATION_ERROR
            else:
                status = IntentStatus.FAILED
                failure_kind = FailureKind.OPERATIONAL_ERROR
        intent_results.append(
            IntentExecutionResult(
                intent.rule_id,
                binding.language,
                binding.backend,
                binding.native_rule,
                binding.mapping,
                status,
                failure_kind=failure_kind,
                required=intent.required,
                severity=item.severity,
                failure_threshold=item.failure_threshold,
                threshold=item.threshold,
                step=binding.step,
                evidence_step=(binding.step if step_result is not None else None),
                exit_code=(step_result.exit_code if step_result is not None else None),
            )
        )

    passed = (
        completed
        - failed
        - provisional_passed
        - provisional_failed
        - not_applicable
        - unsupported_count
        - disabled
    )
    exit_code = (
        ExitCode.QUALITY_FAILURE if failed or blocking_unsupported else ExitCode.SUCCESS
    )
    result = OrchestrationResult(
        profile_name,
        passed,
        failed,
        exit_code,
        tuple(results),
        threshold,
        SeverityCounts.from_diagnostics(all_findings),
        not_applicable,
        FindingRollups.from_diagnostics(all_findings),
        tuple(intent_results),
        unsupported_count,
        disabled,
    )
    payload = None
    if json_output or history_context is not None:
        payload = asdict(result)
        # ``asdict`` includes the private parsed RuleTag cache. Replace each
        # finding with its explicit public wire adapter to preserve the JSON
        # schema and keep semantic identity internal.
        for step_payload, step_result in zip(payload["steps"], result.steps):
            step_payload["findings"] = [
                finding.to_wire() for finding in step_result.findings
            ]
            if step_result.report is None:
                step_payload.pop("report")
        if not not_applicable:
            del payload[_STATUS_NOT_APPLICABLE]
        if result.intent_bindings:
            payload["intent_bindings"] = [
                asdict(item) for item in result.intent_bindings
            ]
        else:
            del payload["intent_bindings"]
        if not result.unsupported:
            del payload[_STATUS_UNSUPPORTED]
        if not result.disabled:
            del payload[_STATUS_DISABLED]
        for step_payload in payload["steps"]:
            if step_payload["rollout"] == _MAINLINE_ROLLOUT:
                del step_payload["rollout"]
            for finding_payload in step_payload["findings"]:
                if finding_payload["priority"] is None:
                    del finding_payload["priority"]
        if provisional_passed or provisional_failed:
            payload[_PROVISIONAL_ROLLOUT] = {
                "passed": provisional_passed,
                "failed": provisional_failed,
            }
        if profile.includes:
            payload["profiles"] = plan.profiles
    if history_context is not None and payload is not None and history_dir is not None:
        try:
            saved = write_profile_record(
                history_dir,
                history_context,
                result=payload,
                total_steps=len(results),
                passed=passed,
                failed=failed,
                provisional_passed=provisional_passed,
                provisional_failed=provisional_failed,
                not_applicable=not_applicable,
                exit_code=exit_code,
                failed_steps=tuple(
                    step.name for step in results if step.status == "failed"
                ),
                step_durations_seconds=step_durations_seconds,
                work_unit_durations_seconds=work_unit_durations_seconds,
            )
        except (OSError, ValueError) as error:
            reporter.error(f"Cannot write profile history: {error}")
            return ExitCode.CONFIG_ERROR
        reporter.history_saved(saved)
    if json_output and payload is not None:
        reporter.json_result(payload)
    else:
        reporter.summary(
            result,
            provisional_passed=provisional_passed,
            provisional_failed=provisional_failed,
        )
    return exit_code
