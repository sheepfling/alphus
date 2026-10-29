"""Reusable availability probes for Python modules and command-line tools."""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import Literal

_MODULE_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*\Z")
_MODULE_PROBE = (
    "import importlib.util, sys; "
    "raise SystemExit(0 if importlib.util.find_spec(sys.argv[1]) else 1)"
)


@dataclass(frozen=True, slots=True)
class ToolProbe:
    kind: Literal["module", "command"]
    name: str
    available: bool
    resolved: str | None = None
    detail: str | None = None


def probe_command(name: str) -> ToolProbe:
    """Locate one executable without invoking a shell."""
    resolved = shutil.which(name)
    return ToolProbe("command", name, resolved is not None, resolved)


def probe_python_module(python: str, module: str) -> ToolProbe:
    """Check module availability in the selected interpreter, not this process."""
    if not _MODULE_NAME.fullmatch(module):
        raise ValueError(f"invalid Python module name: {module!r}")
    try:
        completed = subprocess.run(
            [python, "-I", "-c", _MODULE_PROBE, module],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return ToolProbe("module", module, False, detail=str(error))
    return ToolProbe(
        "module",
        module,
        completed.returncode == 0,
        resolved=python,
        detail=completed.stderr.strip() or None,
    )
