"""Compatibility imports for shared Git-backed file inventory utilities."""

import subprocess

from alphus.support.inventory import (
    candidate_files,
    git_files,
    matches_path,
    tracked_files,
)

__all__ = [
    "candidate_files",
    "git_files",
    "matches_path",
    "subprocess",
    "tracked_files",
]
