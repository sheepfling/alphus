"""The selected cyclomatic backend stays unloaded during general CLI setup."""

from __future__ import annotations

import subprocess
import sys


def test_cli_and_dispatch_import_without_loading_cyclomatic_engine() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import alphus.cli; import alphus.execution.dispatch; "
                "import alphus.execution._worker; "
                "assert 'alphus.gates.source.cyclomatic_complexity' not in sys.modules"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
