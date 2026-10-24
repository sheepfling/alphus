"""Run a policy-selected quality profile through Python orchestration."""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable, Mapping
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import asdict, dataclass, field
from io import StringIO
from pathlib import Path
from typing import Literal, TextIO, TypeGuard, cast

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
    Severity,
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
from alphus.execution.commands import (
    command_arguments,
    step_directory,
    windows_shell_required,
)
from alphus.execution.parallel import StepExecution, run_parallel_steps
from alphus.execution.processes import run_captured_process
from alphus.execution.profile_history import (
    capture_profile_context,
    latest_profile_record,
    write_profile_record,
)
from alphus.execution.profile_reporting import ProfileReporter
from alphus.execution.step_results import RuleRunResult
from alphus.support.inventory import candidate_files

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


@dataclass(frozen=True, slots=True)
class OrchestrationStepResult:
    """Machine-readable outcome for one configured profile step."""

    name: str
    status: Literal["passed", "failed", "not_applicable"]
    exit_code: int
    diagnostics: tuple[str, ...] = ()
    findings: tuple[Diagnostic, ...] = ()
    stdout: str = ""
    stderr: str = ""
    severity_counts: SeverityCounts = field(default_factory=SeverityCounts)
    rollout: Literal["mainline", "provisional"] = "mainline"
    report: Mapping[str, object] | None = None


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


def _render_diagnostic(diagnostic: Diagnostic, reporter: ProfileReporter) -> None:
    """Render normalized findings with stable source and rule provenance."""
    location = diagnostic.path or ""
    if diagnostic.line is not None:
        location = f"{location}:{diagnostic.line}" if location else str(diagnostic.line)
    suffix = f" {location}" if location else ""
    priority = f" [priority={diagnostic.priority}]" if diagnostic.priority else ""
    owner = "" if diagnostic.source == NAMESPACE else f"{diagnostic.source} "
    reporter.info(
        f"{diagnostic.severity.upper()} {owner}"
        f"{diagnostic.rule_id}{suffix}{priority}: {diagnostic.message}"
    )


def _legacy_diagnostic_line(diagnostic: Diagnostic) -> str:
    """Keep the existing string diagnostics field useful for older consumers."""
    location = diagnostic.path or ""
    if diagnostic.line is not None:
        location = f"{location}:{diagnostic.line}" if location else str(diagnostic.line)
    prefix = "" if diagnostic.severity == "error" else f"{diagnostic.severity.upper()} "
    if location:
        return f"{prefix}{location}: {diagnostic.message}"
    return f"{prefix}{diagnostic.message}"


def _write_captured(stream: TextIO, value: str) -> None:
    """Replay command output without interpreting its contents."""
    if value:
        stream.write(value)
        stream.flush()


def _is_structured_rule_result(
    value: int | RuleRunResult,
) -> TypeGuard[RuleRunResult]:
    """Narrow the public legacy integer and structured rule result union."""
    return isinstance(value, RuleRunResult)


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
) -> int:
    """Run every configured profile step and summarize all outcomes."""
    checkout = root.resolve(strict=True)
    resolved_config = config_path.resolve(strict=True)
    output = stdout if stdout is not None else sys.stdout
    errors = stderr if stderr is not None else sys.stderr
    reporter = ProfileReporter(output, errors)
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
    history_context = None
    previous_failures: frozenset[str] = frozenset()
    if history_dir is not None:
        try:
            loaded_config = (
                config if config is not None else load_config(resolved_config)
            )
            history_context = capture_profile_context(
                checkout, profile_name, loaded_config
            )
            if policy.execution.prioritize_previous_failures:
                previous = latest_profile_record(
                    history_dir,
                    checkout,
                    profile_name,
                    config_sha256=history_context.config_sha256,
                )
                if previous is not None:
                    previous_failures = frozenset(previous.failed_steps)
        except (OSError, ValueError) as error:
            reporter.error(f"Cannot read profile history: {error}")
            return ExitCode.CONFIG_ERROR
    selected_steps = {step.name: step for step in policy.steps}
    parallel_results: dict[str, StepExecution] = {}

    failed = 0
    provisional_passed = 0
    provisional_failed = 0
    not_applicable = 0
    completed = 0
    results: list[OrchestrationStepResult] = []
    all_findings: list[Diagnostic] = []
    threshold = policy.failure_threshold
    if profile.includes and not json_output:
        reporter.info(f"Selected profiles: {', '.join(plan.profiles)}")
    for index, step_name in enumerate(plan.steps):
        step: RuleRunStep | CommandRunStep = selected_steps[step_name]
        if (
            (max_jobs > 1 and step.parallel)
            or (isinstance(step, RuleRunStep) and step.timeout_seconds is not None)
        ) and step_name not in parallel_results:
            block: list[RuleRunStep | CommandRunStep] = [step]
            if max_jobs > 1 and step.parallel:
                for later_name in plan.steps[index + 1 :]:
                    later = selected_steps[later_name]
                    if not later.parallel:
                        break
                    block.append(later)
            try:
                parallel_results.update(
                    run_parallel_steps(
                        checkout,
                        resolved_config,
                        config if config is not None else load_config(resolved_config),
                        block,
                        max_jobs,
                        verbose=verbose,
                        previously_failed=previous_failures,
                    )
                )
            except (OSError, ValueError) as error:
                reporter.error(f"Cannot schedule quality work: {error}")
                return ExitCode.CONFIG_ERROR
        precomputed = parallel_results.pop(step_name, None)
        if not json_output:
            reporter.info(f"==> {step.name}")
        captured_stdout = StringIO()
        captured_stderr = StringIO()
        step_stdout = ""
        step_stderr = ""
        step_report: Mapping[str, object] | None = None
        findings: list[Diagnostic] = []
        skipped_empty_file_scope = False
        legacy_diagnostics: tuple[str, ...] = ()
        attempted_command: str | None = None
        exit_code = ExitCode.LAUNCH_ERROR
        try:
            match step:
                case RuleRunStep(rule=rule):
                    rule_result: int | RuleRunResult
                    if precomputed is None:
                        with (
                            redirect_stdout(captured_stdout),
                            redirect_stderr(captured_stderr),
                        ):
                            rule_result = run_rule(rule)
                    else:
                        if precomputed.error is not None:
                            raise OSError(str(precomputed.error))
                        if precomputed.rule is None:
                            raise ValueError("parallel rule returned no result")
                        rule_result = precomputed.rule
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
                case CommandRunStep(working_directory=working_directory):
                    selected_files = (
                        candidate_files(checkout, step.files)
                        if precomputed is None and step.files is not None
                        else []
                    )
                    if precomputed is not None and precomputed.error is not None:
                        raise OSError(str(precomputed.error))
                    if (precomputed is not None and precomputed.not_applicable) or (
                        precomputed is None
                        and step.files is not None
                        and not selected_files
                    ):
                        skipped_empty_file_scope = True
                        exit_code = ExitCode.SUCCESS
                    else:
                        if precomputed is None:
                            directory = step_directory(checkout, working_directory)
                            arguments = command_arguments(
                                step,
                                checkout,
                                resolved_config,
                                selected_files,
                                directory,
                            )
                            attempted_command = arguments[0]
                            result = run_captured_process(
                                arguments,
                                directory,
                                shell=windows_shell_required(arguments),
                                timeout=step.timeout_seconds,
                            )
                        else:
                            if precomputed.command is None:
                                raise ValueError("parallel command returned no result")
                            result = precomputed.command
                        exit_code = result.returncode
                        step_stdout = result.stdout or ""
                        step_stderr = result.stderr or ""
                        if exit_code != ExitCode.SUCCESS:
                            legacy_diagnostics = tuple(
                                line
                                for captured in (step_stdout, step_stderr)
                                for line in captured.splitlines()
                            )
                            findings.append(
                                Diagnostic(
                                    source=step.name,
                                    rule_id=_COMMAND_EXITED_NONZERO,
                                    message=f"command exited with status {exit_code}",
                                )
                            )
        except (
            OSError,
            ValueError,
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
        ) as error:
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

        if not json_output:
            _write_captured(output, step_stdout)
            _write_captured(errors, step_stderr)

        completed += 1
        provisional = step.rollout == "provisional"
        if skipped_empty_file_scope:
            not_applicable += 1
            results.append(
                OrchestrationStepResult(
                    step.name,
                    "not_applicable",
                    exit_code,
                    diagnostics=("No files matched the configured command scope.",),
                    rollout=step.rollout,
                )
            )
            if not json_output:
                reporter.info(f"NOT APPLICABLE {step.name}: no files matched")
        elif exit_code == ExitCode.SUCCESS:
            if provisional:
                provisional_passed += 1
            results.append(
                OrchestrationStepResult(
                    step.name,
                    "passed",
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
            if not json_output and isinstance(step, RuleRunStep):
                for finding in findings:
                    _render_diagnostic(finding, reporter)
            if not json_output:
                prefix = "PROVISIONAL PASS" if provisional else "PASS"
                reporter.info(f"{prefix} {step.name}")
        else:
            if provisional:
                provisional_failed += 1
            else:
                failed += 1
            results.append(
                OrchestrationStepResult(
                    step.name,
                    "failed",
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
            if not json_output and isinstance(step, RuleRunStep):
                for finding in findings:
                    _render_diagnostic(finding, reporter)
            if not json_output:
                prefix = "PROVISIONAL FAIL" if provisional else "FAIL"
                reporter.info(f"{prefix} {step.name} (exit {exit_code})")
        if json_output and step_stderr:
            reporter.captured_error(step_stderr)

    passed = (
        completed - failed - provisional_passed - provisional_failed - not_applicable
    )
    exit_code = ExitCode.QUALITY_FAILURE if failed else ExitCode.SUCCESS
    payload = None
    if json_output or history_context is not None:
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
        )
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
            del payload["not_applicable"]
        for step_payload in payload["steps"]:
            if step_payload["rollout"] == "mainline":
                del step_payload["rollout"]
            for finding_payload in step_payload["findings"]:
                if finding_payload["priority"] is None:
                    del finding_payload["priority"]
        if provisional_passed or provisional_failed:
            payload["provisional"] = {
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
            )
        except (OSError, ValueError) as error:
            reporter.error(f"Cannot write profile history: {error}")
            return ExitCode.CONFIG_ERROR
        errors.write(f"history={saved}\n")
    if json_output and payload is not None:
        reporter.info(json.dumps(payload, sort_keys=True))
    else:
        summary = f"Quality profile {profile_name}: {passed} passed, {failed} failed"
        if not_applicable:
            summary += f", {not_applicable} not applicable"
        if provisional_passed or provisional_failed:
            summary += (
                f", {provisional_passed} provisional passed, "
                f"{provisional_failed} provisional failed"
            )
        reporter.info(summary)
        counts = SeverityCounts.from_diagnostics(all_findings)
        if counts.error or counts.warning or counts.info:
            reporter.info(
                "Diagnostic triage: "
                f"{counts.error} error(s), {counts.warning} warning(s), "
                f"{counts.info} info(s); failure threshold={threshold}"
            )
    return exit_code
