"""Explicit checker/target identities and isolated child-process environments."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from alphus.support.tool_probe import probe_command


class PythonRuntime(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    executable: str
    version: tuple[int, int, int]
    prefix: str
    tool_versions: tuple[tuple[str, str], ...]
    platform: str = "unknown"
    architecture: str = "unknown"
    distribution_versions: tuple[tuple[str, str], ...] = ()
    missing_distributions: tuple[str, ...] = ()

    @property
    def minor(self) -> str:
        return ".".join(str(part) for part in self.version[:2])


_PROBE = """
import importlib.metadata as metadata
import json, platform, sys
versions = []
for name in ('alphus', 'pip', 'build', 'setuptools', 'setuptools-scm', 'wheel',
             'mypy', 'pyright', 'ty', 'twine', 'typing_extensions', 'snakemd', 'mdutils',
             'snakemd-stubs', 'mdutils-stubs'):
    try:
        versions.append((name, metadata.version(name)))
    except metadata.PackageNotFoundError:
        pass
requested = sys.argv[1:]
distribution_versions = []
missing_distributions = []
for name in requested:
    try:
        distribution_versions.append((name, metadata.version(name)))
    except metadata.PackageNotFoundError:
        missing_distributions.append(name)
print(json.dumps(dict(executable=sys.executable, version=list(sys.version_info[:3]),
                     prefix=sys.prefix, tool_versions=versions,
                     platform=sys.platform, architecture=platform.machine(),
                     distribution_versions=distribution_versions,
                     missing_distributions=missing_distributions)))
"""


def probe_python(
    executable: str, *, requested_distributions: tuple[str, ...] = ()
) -> PythonRuntime:
    """Preserve virtualenv executable paths; resolving symlinks loses the venv."""
    command = probe_command(executable).resolved
    if command is None:
        raise ValueError(f"Python executable not found: {executable}")
    try:
        result = subprocess.run(
            [command, "-I", "-c", _PROBE, *requested_distributions],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        return PythonRuntime.model_validate_json(result.stdout)
    except (OSError, subprocess.SubprocessError, ValidationError) as error:
        raise ValueError(
            f"Could not inspect Python executable {executable}: {error}"
        ) from error


def child_environment(
    base: Mapping[str, str], executable: str, *, shared_root: Path | None = None
) -> dict[str, str]:
    """Expose only the selected interpreter and explicitly copied shared helpers."""
    env = dict(base)
    for key in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "MYPYPATH"):
        env.pop(key, None)
    env["PYTHONNOUSERSITE"] = "1"
    env["PATH"] = (
        str(Path(executable).absolute().parent) + os.pathsep + env.get("PATH", "")
    )
    if shared_root is not None:
        env["PYTHONPATH"] = str(shared_root)
    return env
