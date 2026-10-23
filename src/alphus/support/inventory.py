"""Explicit-root source inventory for Git-backed repository checks."""

from __future__ import annotations

from fnmatch import fnmatchcase
from functools import cache
from pathlib import Path, PurePosixPath

from alphus.config import FileInventoryPolicy
from alphus.support.git import run_git


def _git_ls_files(checkout: Path, *options: str) -> bytes:
    """Read Git's inventory or explain why it cannot be read."""
    try:
        result = run_git(checkout, "ls-files", *options, "-z")
    except OSError as error:
        raise OSError(
            "Git is required for Alphus file inventory; install Git or use a "
            "profile without Git-backed rules"
        ) from error
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise OSError(f"Git file inventory failed for {checkout}: {detail}")
    return result.stdout


def matches_path(path: str, pattern: str) -> bool:
    """Match POSIX path segments with recursive ** and root-safe globs."""
    candidate = PurePosixPath(path)
    path_parts = candidate.parts
    pattern_parts = PurePosixPath(pattern).parts

    @cache
    def matches(path_index: int, pattern_index: int) -> bool:
        if pattern_index == len(pattern_parts):
            return path_index == len(path_parts)
        if pattern_parts[pattern_index] == "**":
            return matches(path_index, pattern_index + 1) or (
                path_index < len(path_parts) and matches(path_index + 1, pattern_index)
            )
        return (
            path_index < len(path_parts)
            and fnmatchcase(path_parts[path_index], pattern_parts[pattern_index])
            and matches(path_index + 1, pattern_index + 1)
        )

    return matches(0, 0)


def _selected(path: str, policy: FileInventoryPolicy) -> bool:
    """Apply configured include and exclude patterns to one repository path."""
    return any(matches_path(path, pattern) for pattern in policy.include) and not any(
        matches_path(path, pattern) for pattern in policy.exclude
    )


def git_files(root: Path) -> list[Path]:
    """Return tracked and non-ignored files beneath an explicit Git root."""
    checkout = root.resolve(strict=True)
    if not checkout.is_dir():
        raise ValueError(f"repository root is not a directory: {checkout}")
    output = _git_ls_files(checkout, "--cached", "--others", "--exclude-standard")
    selected: list[Path] = []
    for raw in output.split(b"\0"):
        if not raw:
            continue
        name = raw.decode("utf-8")
        relative = PurePosixPath(name)
        if relative.is_absolute() or ".." in relative.parts or "\\" in name:
            continue
        relative_path = Path(*relative.parts)
        path = checkout / relative_path
        if path.is_symlink() or not path.is_file():
            continue
        resolved = path.resolve(strict=True)
        if resolved.is_relative_to(checkout):
            selected.append(relative_path)
    return sorted(selected)


def tracked_files(root: Path) -> list[Path]:
    """Return safe Git-index paths beneath the caller-provided checkout root."""
    checkout = root.resolve(strict=True)
    if not checkout.is_dir():
        raise ValueError(f"repository root is not a directory: {checkout}")
    output = _git_ls_files(checkout, "--cached")
    selected: list[Path] = []
    for raw in output.split(b"\0"):
        if not raw:
            continue
        name = raw.decode("utf-8")
        relative = PurePosixPath(name)
        if relative.is_absolute() or ".." in relative.parts or "\\" in name:
            continue
        selected.append(Path(*relative.parts))
    return sorted(selected)


def candidate_files(root: Path, policy: FileInventoryPolicy) -> list[Path]:
    """Return the configured subset of a safe Git file inventory."""
    return [path for path in git_files(root) if _selected(path.as_posix(), policy)]
