"""Capture child processes and stop their process groups on interruption."""

from __future__ import annotations

import os
import signal
import subprocess
from collections.abc import Sequence
from pathlib import Path

from alphus.support.platform_utils import is_windows


def _stop_process(process: subprocess.Popen[str]) -> None:
    if is_windows():
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                check=False,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            process.kill()
        return
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def run_captured_process(
    argv: Sequence[str],
    directory: Path,
    *,
    timeout: int | None = None,
    input_text: str | None = None,
    shell: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Return captured output, cleaning up the child group on timeout."""
    with subprocess.Popen(
        list(argv),
        cwd=directory,
        shell=shell,
        stdin=subprocess.PIPE if input_text is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=not is_windows(),
    ) as process:
        try:
            stdout, stderr = process.communicate(input=input_text, timeout=timeout)
        except BaseException:
            _stop_process(process)
            try:
                process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
            raise
        return subprocess.CompletedProcess(
            list(argv), process.returncode, stdout, stderr
        )
