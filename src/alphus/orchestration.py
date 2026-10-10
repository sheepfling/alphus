"""Run a policy-selected quality profile through Python orchestration."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import asdict, dataclass
from io import StringIO
from pathlib import Path, PurePosixPath
from typing import Literal, TextIO

from alphus.config import (
    CommandRunStep,
    OrchestrationPolicy,
    QualityRuleName,
    RuleRunStep,
)
from alphus.inventory import candidate_files


@dataclass(frozen=True, slots=True)
class OrchestrationStepResult:
    """Machine-readable outcome for one configured profile step."""

    name: str
    status: Literal["passed", "failed"]
    exit_code: int
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class OrchestrationResult:
    """Machine-readable summary for a configured quality profile."""

    profile: str
    passed: int
    failed: int
    exit_code: int
    steps: tuple[OrchestrationStepResult, ...]


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
            arguments.extend(path.as_posix() for path in files)
            continue
        argument = configured_argument
        for token, value in replacements.items():
            argument = argument.replace(token, value)
        arguments.append(argument)
    return arguments


def _windows_shell_required(arguments: Sequence[str]) -> bool:
    """Allow Windows batch launchers such as npm.cmd without shell snippets."""
    if os.name != "nt":
        return False
    executable = shutil.which(arguments[0])
    return Path(executable or arguments[0]).suffix.casefold() in {".cmd", ".bat"}


def run_orchestration(
    root: Path,
    config_path: Path,
    policy: OrchestrationPolicy,
    profile_name: str,
    run_rule: Callable[[QualityRuleName], int],
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
    if profile is None:
        print(f"Unknown orchestration profile: {profile_name}", file=errors, flush=True)
        return 2

    failed = 0
    completed = 0
    results: list[OrchestrationStepResult] = []
    for step_name in profile.steps:
        step = next(item for item in policy.steps if item.name == step_name)
        if not json_output:
            print(f"==> {step.name}", file=output, flush=True)
        captured_stdout = StringIO()
        captured_stderr = StringIO()
        skipped_empty_file_scope = False
        try:
            match step:
                case RuleRunStep(rule=rule):
                    if json_output:
                        with (
                            redirect_stdout(captured_stdout),
                            redirect_stderr(captured_stderr),
                        ):
                            exit_code = run_rule(rule)
                    else:
                        exit_code = run_rule(rule)
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
                        arguments = _arguments(
                            step, checkout, resolved_config, selected_files
                        )
                        directory = _step_directory(checkout, working_directory)
                        result = subprocess.run(
                            arguments,
                            cwd=directory,
                            check=False,
                            shell=_windows_shell_required(arguments),
                            capture_output=json_output,
                            text=json_output,
                        )
                        exit_code = result.returncode
                        if json_output:
                            captured_stdout.write(result.stdout or "")
                            captured_stderr.write(result.stderr or "")
        except (OSError, ValueError, subprocess.CalledProcessError) as error:
            message = f"{step.name}: {error}"
            captured_stderr.write(f"{message}\n")
            if not json_output:
                print(message, file=errors, flush=True)
            exit_code = 127

        completed += 1
        if exit_code == 0:
            results.append(
                OrchestrationStepResult(
                    step.name,
                    "passed",
                    exit_code,
                    ("No files matched the configured command scope.",)
                    if skipped_empty_file_scope
                    else (),
                )
            )
            if not json_output:
                details = " (no files matched)" if skipped_empty_file_scope else ""
                print(f"PASS {step.name}{details}", file=output, flush=True)
        else:
            failed += 1
            diagnostics = tuple(
                line
                for captured in (captured_stdout, captured_stderr)
                for line in captured.getvalue().splitlines()
            )
            results.append(
                OrchestrationStepResult(step.name, "failed", exit_code, diagnostics)
            )
            if not json_output:
                print(f"FAIL {step.name} (exit {exit_code})", file=output, flush=True)
        captured_errors = captured_stderr.getvalue()
        if json_output and captured_errors:
            print(captured_errors, end="", file=errors, flush=True)

    passed = completed - failed
    exit_code = 1 if failed else 0
    if json_output:
        result = OrchestrationResult(
            profile_name, passed, failed, exit_code, tuple(results)
        )
        print(json.dumps(asdict(result), sort_keys=True), file=output, flush=True)
    else:
        print(
            f"Quality profile {profile_name}: {passed} passed, {failed} failed",
            file=output,
            flush=True,
        )
    return exit_code
