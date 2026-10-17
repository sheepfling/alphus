"""Check launcher scripts against a configured Python module boundary."""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

from alphus.config import ScriptPolicy
from alphus.inventory import matches_path

_CMD_DIRECTORY = re.compile(r'(?i)^cd /d "%~dp0(?:\.\.(?:[\\/]\.\.)*)?"$')
_PYTHON_EXECUTABLE = (
    r"(?:py(?:\.exe)?(?: -3(?:\.\d+)?)?|python(?:3)?(?:\.exe)?|"
    r'"[^\"]*[\\/]python(?:\.exe)?")'
)


def launcher_files(paths: Iterable[Path], policy: ScriptPolicy) -> list[Path]:
    """Select configured launcher file suffixes from the caller's inventory."""
    return [
        path
        for path in paths
        if path.suffix.lower() in policy.extensions
        and not any(
            matches_path(path.as_posix(), pattern) for pattern in policy.exclude
        )
    ]


def _python_module_pattern(policy: ScriptPolicy) -> re.Pattern[str]:
    module_name = (
        re.escape(policy.python_module_prefix) + r"(?:\.[A-Za-z_][A-Za-z0-9_]*)+"
    )
    return re.compile(rf"(?i)^{_PYTHON_EXECUTABLE} -m (?P<module>{module_name}) %\*$")


def _module_exists(root: Path, module_name: str) -> bool:
    """Require a contained, non-symlink Python module or package entrypoint."""
    module_path = Path(*module_name.split("."))
    for candidate in (
        root / module_path.with_suffix(".py"),
        root / module_path / "__main__.py",
    ):
        if candidate.is_symlink() or not candidate.is_file():
            continue
        if candidate.resolve(strict=True).is_relative_to(root):
            return True
    return False


def is_python_cmd_router(source: str, root: Path, policy: ScriptPolicy) -> bool:
    """Allow a short CMD wrapper around one configured Python module."""
    if len(source.splitlines()) > policy.cmd_router_line_limit:
        return False
    commands = [
        line.strip()
        for line in source.splitlines()
        if line.strip() and not line.strip().casefold().startswith(("::", "rem "))
    ]
    if not commands or commands.pop(0).casefold() != "@echo off":
        return False
    if commands and commands[0].casefold() == "setlocal":
        commands.pop(0)
    if not commands or _CMD_DIRECTORY.fullmatch(commands.pop(0)) is None:
        return False
    if len(commands) != 2 or commands[1].casefold() != "exit /b %errorlevel%":
        return False
    match = _python_module_pattern(policy).fullmatch(commands[0])
    if match is None:
        return False
    return _module_exists(root, match.group("module"))


def policy_issues(root: Path, paths: Iterable[Path], policy: ScriptPolicy) -> list[str]:
    """Report configured non-Python launchers without legacy exemptions."""
    checkout = root.resolve(strict=True)
    issues: list[str] = []
    for relative in launcher_files(paths, policy):
        path = checkout / relative
        if path.is_symlink() or not path.is_file():
            continue
        if not path.resolve(strict=True).is_relative_to(checkout):
            continue
        suffix = relative.suffix.lower()
        if suffix == ".cmd" and is_python_cmd_router(
            path.read_text(encoding="utf-8-sig"), checkout, policy
        ):
            continue
        message = policy.cmd_message if suffix == ".cmd" else policy.launcher_message
        issues.append(f"{relative}: {message}")
    return issues
