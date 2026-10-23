"""Resolve and explicitly apply configured, file-scoped command fixers."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TextIO

from alphus.execution.commands import (
    command_arguments,
    step_directory,
    windows_shell_required,
)
from alphus.policy.orchestration import CommandRunStep, OrchestrationPolicy, RuleRunStep
from alphus.support.inventory import candidate_files


@dataclass(frozen=True, slots=True)
class FixPlanEntry:
    """One selected profile step and its optional explicit fix command."""

    name: str
    kind: Literal["rule", "command"]
    fix_argv: tuple[str, ...] | None = None
    expanded_argv: tuple[str, ...] | None = None
    working_directory: str | None = None
    files: tuple[str, ...] = ()

    @property
    def fixable(self) -> bool:
        return self.fix_argv is not None


def resolve_fix_plan(
    root: Path,
    config_path: Path,
    policy: OrchestrationPolicy,
    profile_name: str,
) -> tuple[FixPlanEntry, ...]:
    """Show every selected step and resolve only declared file-scoped fixers."""
    checkout = root.resolve(strict=True)
    plan = policy.resolve_profile(profile_name)
    if plan is None:
        raise ValueError(f"unknown quality profile: {profile_name}")
    steps = {step.name: step for step in policy.steps}
    entries: list[FixPlanEntry] = []
    for name in plan.steps:
        step: CommandRunStep | RuleRunStep = steps[name]
        if not isinstance(step, CommandRunStep):
            entries.append(FixPlanEntry(name=name, kind=step.kind))
            continue
        selected = (
            candidate_files(checkout, step.files) if step.files is not None else []
        )
        scoped_files = tuple(path.as_posix() for path in selected)
        if step.fix_argv is None:
            entries.append(FixPlanEntry(name=name, kind="command", files=scoped_files))
            continue
        if step.files is None:
            raise ValueError(f"fixer {name!r} has no file scope")
        directory = step_directory(checkout, step.working_directory)
        arguments = command_arguments(
            step,
            checkout,
            config_path,
            selected,
            directory,
            argv=step.fix_argv,
        )
        entries.append(
            FixPlanEntry(
                name=name,
                kind="command",
                fix_argv=step.fix_argv,
                expanded_argv=tuple(arguments),
                working_directory=step.working_directory,
                files=scoped_files,
            )
        )
    return tuple(entries)


def apply_fixes(
    root: Path,
    entries: tuple[FixPlanEntry, ...],
    selected_names: tuple[str, ...],
    output: TextIO,
    errors: TextIO,
) -> int:
    """Run named fixers in profile order, stopping on the first failure."""
    if not selected_names:
        raise ValueError("--apply-fixes requires at least one --fix-step")
    if len(set(selected_names)) != len(selected_names):
        raise ValueError("--fix-step names must be unique")
    by_name = {entry.name: entry for entry in entries}
    for name in selected_names:
        entry = by_name.get(name)
        if entry is None:
            raise ValueError(f"step {name!r} is not in the selected profile")
        if not entry.fixable:
            raise ValueError(f"step {name!r} has no configured fixer")
    chosen = set(selected_names)
    checkout = root.resolve(strict=True)
    for entry in entries:
        if entry.name not in chosen:
            continue
        if not entry.files:
            print(f"SKIP {entry.name}: no files matched", file=output, flush=True)
            continue
        if entry.expanded_argv is None or entry.working_directory is None:
            raise ValueError(f"step {entry.name!r} has no resolved fix command")
        directory = step_directory(checkout, entry.working_directory)
        print(
            f"APPLY {entry.name}: {json.dumps(entry.expanded_argv)}",
            file=output,
            flush=True,
        )
        try:
            result = subprocess.run(
                list(entry.expanded_argv),
                cwd=directory,
                shell=windows_shell_required(entry.expanded_argv),
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as error:
            print(f"FAIL {entry.name}: {error}", file=errors, flush=True)
            return 1
        if result.stdout:
            print(result.stdout, end="", file=output, flush=True)
        if result.stderr:
            print(result.stderr, end="", file=errors, flush=True)
        if result.returncode != 0:
            print(
                f"FAIL {entry.name}: fix command exited {result.returncode}",
                file=errors,
                flush=True,
            )
            return 1
        print(f"APPLIED {entry.name}: {len(entry.files)} file(s) selected", file=output)
    return 0
