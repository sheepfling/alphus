"""Run a policy-selected quality profile through Python orchestration."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import asdict, dataclass, field
from io import StringIO
from pathlib import Path, PurePosixPath
from typing import Literal, TextIO

from alphus.config import (
    CommandRunStep,
    OrchestrationPolicy,
    QualityRuleName,
    RuleRunStep,
)
from alphus.findings import (
    Diagnostic,
    Severity,
    SeverityCounts,
    severity_meets_threshold,
)
from alphus.support.inventory import candidate_files
from alphus.support.platform_utils import is_windows


@dataclass(frozen=True, slots=True)
class OrchestrationStepResult:
    """Machine-readable outcome for one configured profile step."""

    name: str
    status: Literal["passed", "failed"]
    exit_code: int
    diagnostics: tuple[str, ...] = ()
    findings: tuple[Diagnostic, ...] = ()
    stdout: str = ""
    stderr: str = ""
    severity_counts: SeverityCounts = field(default_factory=SeverityCounts)
    rollout: Literal["mainline", "provisional"] = "mainline"


@dataclass(frozen=True, slots=True)
class RuleRunResult:
    """Structured outcome from an Alphus-owned rule invocation."""

    findings: tuple[Diagnostic, ...] = ()
    execution_failure: str | None = None
    exit_code: int = 0
    stderr: str = ""


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


def _step_directory(root: Path, working_directory: str) -> Path:
    """Resolve one configured step directory without leaving the checkout."""
    if working_directory == ".":
        return root
    relative = PurePosixPath(working_directory)
    directory = root.joinpath(*relative.parts).resolve(strict=True)
    if not directory.is_dir() or not directory.is_relative_to(root):
        raise ValueError(
            f"step working directory must resolve inside the checkout: {working_directory}"
        )
    return directory


def _arguments(
    step: CommandRunStep,
    root: Path,
    config_path: Path,
    files: Sequence[Path] = (),
    directory: Path | None = None,
) -> list[str]:
    """Expand only the documented runner placeholders in an argv vector."""
    replacements = {
        "{python}": sys.executable,
        "{root}": str(root),
        "{config}": str(config_path),
    }
    arguments: list[str] = []
    for configured_argument in step.argv:
        if configured_argument == "{files}":
            arguments.extend(
                _relative_file_argument(root, directory or root, path) for path in files
            )
            continue
        argument = configured_argument
        for token, value in replacements.items():
            argument = argument.replace(token, value)
        arguments.append(argument)
    return arguments


def _relative_file_argument(root: Path, directory: Path, path: Path) -> str:
    """Name an inventoried file relative to the command's working directory."""
    base_parts = directory.relative_to(root).parts
    file_parts = path.parts
    common = 0
    for base_part, file_part in zip(base_parts, file_parts):
        if base_part != file_part:
            break
        common += 1
    parts = ("..",) * (len(base_parts) - common) + file_parts[common:]
    return PurePosixPath(*parts).as_posix()


def _windows_shell_required(arguments: Sequence[str]) -> bool:
    """Allow Windows batch launchers such as npm.cmd without shell snippets."""
    if not is_windows():
        return False
    executable = shutil.which(arguments[0])
    return Path(executable or arguments[0]).suffix.casefold() in {".cmd", ".bat"}


def _render_diagnostic(diagnostic: Diagnostic, output: TextIO) -> None:
    """Render normalized findings with stable source and rule provenance."""
    location = diagnostic.path or ""
    if diagnostic.line is not None:
        location = f"{location}:{diagnostic.line}" if location else str(diagnostic.line)
    suffix = f" {location}" if location else ""
    priority = f" [priority={diagnostic.priority}]" if diagnostic.priority else ""
    print(
        f"{diagnostic.severity.upper()} {diagnostic.source} "
        f"{diagnostic.rule_id}{suffix}{priority}: {diagnostic.message}",
        file=output,
        flush=True,
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
) -> int:
    """Run every configured profile step and summarize all outcomes."""
    checkout = root.resolve(strict=True)
    resolved_config = config_path.resolve(strict=True)
    output = stdout if stdout is not None else sys.stdout
    errors = stderr if stderr is not None else sys.stderr
    profile = policy.profile(profile_name)
    plan = policy.resolve_profile(profile_name)
    if profile is None or plan is None:
        print(f"Unknown orchestration profile: {profile_name}", file=errors, flush=True)
        return 2

    failed = 0
    provisional_passed = 0
    provisional_failed = 0
    completed = 0
    results: list[OrchestrationStepResult] = []
    all_findings: list[Diagnostic] = []
    threshold = policy.failure_threshold
    if profile.includes and not json_output:
        print(f"Selected profiles: {', '.join(plan.profiles)}", file=output, flush=True)
    for step_name in plan.steps:
        step: RuleRunStep | CommandRunStep = next(
            item for item in policy.steps if item.name == step_name
        )
        if not json_output:
            print(f"==> {step.name}", file=output, flush=True)
        captured_stdout = StringIO()
        captured_stderr = StringIO()
        step_stdout = ""
        step_stderr = ""
        findings: list[Diagnostic] = []
        skipped_empty_file_scope = False
        legacy_diagnostics: tuple[str, ...] = ()
        attempted_command: str | None = None
        exit_code = 127
        try:
            match step:
                case RuleRunStep(rule=rule):
                    with (
                        redirect_stdout(captured_stdout),
                        redirect_stderr(captured_stderr),
                    ):
                        rule_result: int | RuleRunResult = run_rule(rule)
                    if isinstance(rule_result, RuleRunResult):
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
                                )
                                for item in findings
                            ]
                        legacy_diagnostics = tuple(
                            _legacy_diagnostic_line(finding) for finding in findings
                        )
                        step_stderr = rule_result.stderr or captured_stderr.getvalue()
                        step_stdout = captured_stdout.getvalue()
                        if rule_result.execution_failure is not None:
                            message = rule_result.execution_failure
                            findings.append(
                                Diagnostic(
                                    source="alphus",
                                    rule_id="orchestration.rule-execution",
                                    message=message,
                                )
                            )
                            exit_code = rule_result.exit_code or 2
                            legacy_diagnostics = (message,)
                        elif rule_result.exit_code not in {0, 1}:
                            message = (
                                "Alphus rule execution failed with exit code "
                                f"{rule_result.exit_code}"
                            )
                            findings.append(
                                Diagnostic(
                                    source="alphus",
                                    rule_id="orchestration.rule-execution",
                                    message=message,
                                )
                            )
                            exit_code = rule_result.exit_code
                            legacy_diagnostics = (message,)
                        elif rule_result.exit_code == 1 and not rule_result.findings:
                            message = "Alphus rule failed without structured findings."
                            findings.append(
                                Diagnostic(
                                    source="alphus",
                                    rule_id="orchestration.rule-execution",
                                    message=message,
                                )
                            )
                            exit_code = 2
                            legacy_diagnostics = (message,)
                        else:
                            exit_code = (
                                1
                                if any(
                                    severity_meets_threshold(
                                        finding.severity, threshold
                                    )
                                    for finding in findings
                                )
                                else 0
                            )
                    else:
                        exit_code = rule_result
                        step_stdout = captured_stdout.getvalue()
                        step_stderr = captured_stderr.getvalue()
                        if exit_code != 0:
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
                                    source="alphus",
                                    rule_id="orchestration.rule-execution",
                                    message=f"rule runner exited with status {exit_code}",
                                )
                            )
                case CommandRunStep(working_directory=working_directory):
                    selected_files = (
                        candidate_files(checkout, step.files)
                        if step.files is not None
                        else []
                    )
                    if step.files is not None and not selected_files:
                        skipped_empty_file_scope = True
                        exit_code = 0
                    else:
                        directory = _step_directory(checkout, working_directory)
                        arguments = _arguments(
                            step, checkout, resolved_config, selected_files, directory
                        )
                        attempted_command = arguments[0]
                        result = subprocess.run(
                            arguments,
                            cwd=directory,
                            check=False,
                            shell=_windows_shell_required(arguments),
                            capture_output=True,
                            text=True,
                        )
                        exit_code = result.returncode
                        step_stdout = result.stdout or ""
                        step_stderr = result.stderr or ""
                        if exit_code != 0:
                            legacy_diagnostics = tuple(
                                line
                                for captured in (step_stdout, step_stderr)
                                for line in captured.splitlines()
                            )
                            findings.append(
                                Diagnostic(
                                    source=step.name,
                                    rule_id="orchestration.command-exit",
                                    message=f"command exited with status {exit_code}",
                                )
                            )
        except (OSError, ValueError, subprocess.CalledProcessError) as error:
            detail = str(error)
            if attempted_command is not None and attempted_command not in detail:
                detail = f"{attempted_command}: {detail}"
            message = f"{step.name}: {detail}"
            captured_stderr.write(f"{message}\n")
            step_stderr = captured_stderr.getvalue()
            legacy_diagnostics = (message,)
            findings.append(
                Diagnostic(
                    source="alphus" if isinstance(step, RuleRunStep) else step.name,
                    rule_id=(
                        "orchestration.rule-execution"
                        if isinstance(step, RuleRunStep)
                        else "orchestration.command-launch"
                    ),
                    message=message,
                )
            )
            exit_code = 127

        if not json_output:
            _write_captured(output, step_stdout)
            _write_captured(errors, step_stderr)

        completed += 1
        provisional = step.rollout == "provisional"
        if exit_code == 0:
            if provisional:
                provisional_passed += 1
            results.append(
                OrchestrationStepResult(
                    step.name,
                    "passed",
                    exit_code,
                    diagnostics=(
                        legacy_diagnostics
                        or (
                            ("No files matched the configured command scope.",)
                            if skipped_empty_file_scope
                            else ()
                        )
                    ),
                    findings=tuple(findings),
                    stdout=step_stdout,
                    stderr=step_stderr,
                    severity_counts=SeverityCounts.from_diagnostics(findings),
                    rollout=step.rollout,
                )
            )
            all_findings.extend(findings)
            if not json_output and isinstance(step, RuleRunStep):
                for finding in findings:
                    _render_diagnostic(finding, output)
            if not json_output:
                details = " (no files matched)" if skipped_empty_file_scope else ""
                prefix = "PROVISIONAL PASS" if provisional else "PASS"
                print(f"{prefix} {step.name}{details}", file=output, flush=True)
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
                )
            )
            all_findings.extend(findings)
            if not json_output and isinstance(step, RuleRunStep):
                for finding in findings:
                    _render_diagnostic(finding, output)
            if not json_output:
                prefix = "PROVISIONAL FAIL" if provisional else "FAIL"
                print(
                    f"{prefix} {step.name} (exit {exit_code})", file=output, flush=True
                )
        if json_output and step_stderr:
            print(step_stderr, end="", file=errors, flush=True)

    passed = completed - failed - provisional_passed - provisional_failed
    exit_code = 1 if failed else 0
    if json_output:
        result = OrchestrationResult(
            profile_name,
            passed,
            failed,
            exit_code,
            tuple(results),
            threshold,
            SeverityCounts.from_diagnostics(all_findings),
        )
        payload = asdict(result)
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
        print(json.dumps(payload, sort_keys=True), file=output, flush=True)
    else:
        summary = f"Quality profile {profile_name}: {passed} passed, {failed} failed"
        if provisional_passed or provisional_failed:
            summary += (
                f", {provisional_passed} provisional passed, "
                f"{provisional_failed} provisional failed"
            )
        print(summary, file=output, flush=True)
        counts = SeverityCounts.from_diagnostics(all_findings)
        if counts.error or counts.warning or counts.info:
            print(
                "Diagnostic triage: "
                f"{counts.error} error(s), {counts.warning} warning(s), "
                f"{counts.info} info(s); failure threshold={threshold}",
                file=output,
                flush=True,
            )
    return exit_code
