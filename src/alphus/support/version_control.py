"""Optional source revision provenance for quality-run records."""

from __future__ import annotations

import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from alphus.support.git import git_value


@dataclass(frozen=True, slots=True)
class VersionControlIdentity:
    """The VCS, current branch or path, and revision at run start."""

    kind: str
    branch: str | None
    revision: str | None


class VersionControlProvider(Protocol):
    """Let a consumer supply provenance from another source-control system."""

    def identify(self, root: Path) -> VersionControlIdentity | None: ...


class GitVersionControlProvider:
    """Read optional revision metadata from a Git working tree."""

    def identify(self, root: Path) -> VersionControlIdentity | None:
        if git_value(root, "rev-parse", "--is-inside-work-tree") != "true":
            return None
        return VersionControlIdentity(
            kind="git",
            branch=git_value(root, "symbolic-ref", "--quiet", "--short", "HEAD"),
            revision=git_value(root, "rev-parse", "HEAD"),
        )


class SvnVersionControlProvider:
    """Read local Subversion information without requiring network access."""

    def identify(self, root: Path) -> VersionControlIdentity | None:
        try:
            result = subprocess.run(
                ["svn", "info", "--xml", "."],
                cwd=root,
                capture_output=True,
                check=False,
                timeout=5,
            )
            if result.returncode:
                return None
            entry = ET.fromstring(result.stdout).find("entry")
        except (OSError, subprocess.TimeoutExpired, ET.ParseError):
            return None
        if entry is None:
            return None
        return VersionControlIdentity(
            kind="svn",
            branch=entry.findtext("relative-url"),
            revision=entry.get("revision"),
        )


def capture_version_control(
    root: Path, *, provider: VersionControlProvider | None = None
) -> VersionControlIdentity | None:
    """Probe Git then SVN, or use one explicit consumer-provided adapter."""
    if provider is not None:
        return provider.identify(root)
    for candidate in (GitVersionControlProvider(), SvnVersionControlProvider()):
        identity = candidate.identify(root)
        if identity is not None:
            return identity
    return None
