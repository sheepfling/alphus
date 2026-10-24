"""Expand profile work into process-backed units and reduce ordered results."""

from __future__ import annotations

import hashlib
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import cast

from alphus.config import QualityGateConfig
from alphus.execution.commands import (
    command_arguments,
    step_directory,
    windows_shell_required,
)
from alphus.execution.processes import run_captured_process
from alphus.execution.scheduler import WorkOutcome, WorkUnit, run_work_units
from alphus.execution.step_results import RuleRunResult
from alphus.execution.worker_protocol import (
    WORKER_RESPONSE,
    WorkerRequest,
    WorkerResponse,
)
from alphus.gates.source.cyclomatic_complexity import (
    BackendRun,
    CyclomaticBackendPlan,
    CyclomaticReport,
    backend_failure,
    build_cyclomatic_plan,
    combine_cyclomatic_backends,
    report_exit_code,
    report_payload,
    report_summary,
)
from alphus.policy.orchestration import CommandRunStep, RuleRunStep
from alphus.support.inventory import candidate_files


@dataclass(frozen=True, slots=True)
class StepExecution:
    """Raw result for the existing profile result normalizer."""

    rule: RuleRunResult | None = None
    command: subprocess.CompletedProcess[str] | None = None
    not_applicable: bool = False
    error: Exception | None = None
    cyclomatic_report: CyclomaticReport | None = None


def _request_payload(request: WorkerRequest) -> str:
    """Serialize the trusted plan before sending it to another process."""
    return request.model_dump_json()


def _invoke_worker(request: WorkerRequest, timeout: int | None) -> WorkerResponse:
    root = request.root
    completed = run_captured_process(
        [
            sys.executable,
            "-c",
            "from alphus.execution._worker import main; raise SystemExit(main())",
        ],
        Path(root),
        input_text=_request_payload(request),
        timeout=timeout,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"Alphus worker exited {completed.returncode}: {completed.stderr.strip()}"
        )
    response = WORKER_RESPONSE.validate_json(completed.stdout)
    if response.kind == "error":
        raise RuntimeError(response.error)
    if completed.stderr:
        raise RuntimeError(f"Alphus worker emitted stderr: {completed.stderr.strip()}")
    return response


def _invoke_command(
    argv: tuple[str, ...], directory: Path, timeout: int | None
) -> subprocess.CompletedProcess[str]:
    return run_captured_process(
        argv,
        directory,
        shell=windows_shell_required(argv),
        timeout=timeout,
    )


def _decode_rule(outcome: WorkOutcome) -> StepExecution:
    if outcome.error is not None:
        return StepExecution(error=outcome.error)
    response = cast(WorkerResponse, outcome.value)
    if response.kind != "rule":
        return StepExecution(error=ValueError("unexpected rule worker response"))
    try:
        return StepExecution(
            rule=RuleRunResult(
                findings=tuple(item.to_diagnostic() for item in response.findings),
                execution_failure=response.execution_failure,
                exit_code=response.exit_code,
                stdout=response.stdout,
                stderr=response.stderr,
                report=response.report,
            )
        )
    except (TypeError, ValueError) as error:
        return StepExecution(error=error)


def _decode_backend(
    outcome: WorkOutcome,
    plan: CyclomaticBackendPlan,
    config: QualityGateConfig,
) -> BackendRun:
    policy = config.checks.cyclomatic_complexity
    assert policy is not None
    if outcome.error is not None:
        return backend_failure(plan, policy, str(outcome.error))
    try:
        response = cast(WorkerResponse, outcome.value)
        if response.kind != "cyclomatic_backend":
            raise ValueError("unexpected cyclomatic backend response")
        result = response.result
        if (
            result.language != plan.language
            or result.backend != plan.backend
            or result.expected_version != plan.expected_version
            or result.maximum != plan.maximum
            or result.variant != plan.variant
            or result.selected_file_count != len(plan.files)
        ):
            raise ValueError("cyclomatic backend provenance changed")
        return (
            result,
            response.records,
            tuple(item.to_finding() for item in response.findings),
        )
    except (KeyError, TypeError, ValueError) as error:
        return backend_failure(
            plan, policy, f"invalid backend worker response: {error}"
        )


def run_parallel_steps(
    root: Path,
    config_path: Path,
    config: QualityGateConfig,
    steps: Sequence[RuleRunStep | CommandRunStep],
    max_jobs: int,
    *,
    verbose: bool = False,
) -> dict[str, StepExecution]:
    """Run one contiguous parallel profile block with a shared worker budget."""
    tasks: list[WorkUnit] = []
    step_keys: dict[str, tuple[str, ...]] = {}
    plans: dict[str, tuple[CyclomaticBackendPlan, ...]] = {}
    skipped: set[str] = set()
    prepared_commands: dict[str, tuple[tuple[str, ...], Path]] = {}
    planning_errors: dict[str, Exception] = {}
    config_fingerprint = hashlib.sha256(config.model_dump_json().encode()).hexdigest()
    for step in steps:
        try:
            if isinstance(step, CommandRunStep):
                selected = (
                    candidate_files(root, step.files) if step.files is not None else []
                )
                if step.files is not None and not selected:
                    skipped.add(step.name)
                    step_keys[step.name] = ()
                else:
                    step_keys[step.name] = (step.name,)
                    directory = step_directory(root, step.working_directory)
                    argv = tuple(
                        command_arguments(step, root, config_path, selected, directory)
                    )
                    prepared_commands[step.name] = (argv, directory)
            elif step.rule == "cyclomatic-complexity":
                policy = config.checks.cyclomatic_complexity
                if policy is None:
                    raise ValueError("cyclomatic complexity policy is missing")
                plan = build_cyclomatic_plan(root, policy)
                plans[step.name] = plan.backends
                step_keys[step.name] = tuple(
                    f"{step.name}\0{backend.language}" for backend in plan.backends
                )
            else:
                step_keys[step.name] = (step.name,)
        except (OSError, ValueError) as error:
            planning_errors[step.name] = error
            step_keys[step.name] = ()

    for step in steps:
        if step.name in planning_errors:
            continue
        dependencies = tuple(
            key for name in step.after if name in step_keys for key in step_keys[name]
        )
        if isinstance(step, CommandRunStep):
            if step.name in skipped:
                continue
            argv, directory = prepared_commands[step.name]
            tasks.append(
                WorkUnit(
                    key=step.name,
                    run=partial(_invoke_command, argv, directory, step.timeout_seconds),
                    slots=step.slots,
                    locks=step.locks,
                    after=dependencies,
                )
            )
            continue
        if step.name in plans:
            policy = config.checks.cyclomatic_complexity
            assert policy is not None
            for backend in plans[step.name]:
                request = WorkerRequest(
                    kind="cyclomatic_backend",
                    root=str(root),
                    config_path=str(config_path),
                    config_fingerprint=config_fingerprint,
                    language=backend.language,
                    expected_plan=backend,
                )
                tasks.append(
                    WorkUnit(
                        key=f"{step.name}\0{backend.language}",
                        run=partial(
                            _invoke_worker,
                            request,
                            step.timeout_seconds or (2 * policy.timeout_seconds + 5),
                        ),
                        slots=step.slots,
                        locks=step.locks,
                        after=dependencies,
                    )
                )
            continue
        request = WorkerRequest(
            kind="rule",
            root=str(root),
            config_path=str(config_path),
            config_fingerprint=config_fingerprint,
            rule=step.rule,
            verbose=verbose,
        )
        tasks.append(
            WorkUnit(
                key=step.name,
                run=partial(_invoke_worker, request, step.timeout_seconds),
                slots=step.slots,
                locks=step.locks,
                after=dependencies,
            )
        )

    outcomes = run_work_units(tasks, max_jobs)
    executed: dict[str, StepExecution] = {}
    for step in steps:
        if step.name in planning_errors:
            executed[step.name] = StepExecution(error=planning_errors[step.name])
        elif step.name in skipped:
            executed[step.name] = StepExecution(not_applicable=True)
        elif isinstance(step, CommandRunStep):
            outcome = outcomes[step.name]
            if outcome.error is not None:
                executed[step.name] = StepExecution(error=outcome.error)
            else:
                executed[step.name] = StepExecution(
                    command=cast(subprocess.CompletedProcess[str], outcome.value)
                )
        elif step.name in plans:
            policy = config.checks.cyclomatic_complexity
            assert policy is not None
            threshold = (
                config.orchestration.failure_threshold
                if config.orchestration is not None
                else "error"
            )
            runs = tuple(
                _decode_backend(
                    outcomes[f"{step.name}\0{backend.language}"], backend, config
                )
                for backend in plans[step.name]
            )
            report: CyclomaticReport = combine_cyclomatic_backends(policy, runs)
            executed[step.name] = StepExecution(
                cyclomatic_report=report,
                rule=RuleRunResult(
                    findings=report.diagnostics,
                    exit_code=report_exit_code(report, threshold),
                    stdout=report_summary(report) + "\n",
                    report=report_payload(report),
                ),
            )
        else:
            executed[step.name] = _decode_rule(outcomes[step.name])
    return executed


def run_parallel_cyclomatic(
    root: Path, config_path: Path, config: QualityGateConfig, max_jobs: int
) -> CyclomaticReport:
    """Use the profile scheduler for a direct cyclomatic rule invocation."""
    step = RuleRunStep(
        kind="rule",
        name="Cyclomatic complexity",
        rule="cyclomatic-complexity",
        parallel=True,
    )
    execution = run_parallel_steps(root, config_path, config, (step,), max_jobs)[
        step.name
    ]
    if execution.error is not None:
        raise RuntimeError(str(execution.error)) from execution.error
    if execution.cyclomatic_report is None:
        raise RuntimeError("cyclomatic worker returned no report")
    return execution.cyclomatic_report
