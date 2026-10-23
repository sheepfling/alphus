"""Explicit-root Git subprocess access shared by repository gates."""

from __future__ import annotations

import subprocess
from pathlib import Path


def run_git(
    root: Path, *arguments: str, input_data: bytes | None = None
) -> subprocess.CompletedProcess[bytes]:
    """Run Git without a shell and preserve the exit code for callers."""
    try:
        return subprocess.run(
            ["git", *arguments],
            cwd=root,
            input=input_data,
            capture_output=True,
            check=False,
        )
    except FileNotFoundError as error:
        raise OSError("Git is required for this quality gate") from error


def git_output(root: Path, *arguments: str, input_data: bytes | None = None) -> bytes:
    """Return Git output or raise a useful error from a failed command."""
    result = run_git(root, *arguments, input_data=input_data)
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise OSError(f"git {' '.join(arguments)} failed: {detail}")
    return result.stdout
