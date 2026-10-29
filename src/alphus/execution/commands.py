"""Shared argument and working-directory handling for profile commands."""

from __future__ import annotations

import shutil
from collections.abc import Sequence
from pathlib import Path, PurePosixPath

from alphus.config import CommandRunStep
from alphus.support.platform_utils import is_windows
from alphus.support.python_runtime import current_python_executable


def step_directory(root: Path, working_directory: str) -> Path:
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


def command_arguments(
    step: CommandRunStep,
    root: Path,
    config_path: Path,
    files: Sequence[Path] = (),
    directory: Path | None = None,
    argv: Sequence[str] | None = None,
) -> list[str]:
    """Expand only the documented runner placeholders in an argv vector."""
    replacements = {
        "{python}": current_python_executable(),
        "{root}": str(root),
        "{config}": str(config_path),
    }
    arguments: list[str] = []
    for configured_argument in step.argv if argv is None else argv:
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


def windows_shell_required(arguments: Sequence[str]) -> bool:
    """Allow Windows batch launchers such as npm.cmd without shell snippets."""
    if not is_windows():
        return False
    executable = shutil.which(arguments[0])
    return Path(executable or arguments[0]).suffix.casefold() in {".cmd", ".bat"}
