"""Unselected output-escaping checkers stay unloaded during CLI setup."""

from __future__ import annotations

import subprocess
import sys


def test_cli_setup_does_not_import_output_escaping_providers() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import alphus.cli; "
                "import alphus.execution.dispatch; "
                "assert 'alphus.gates.source.output_escaping' not in sys.modules; "
                "assert 'alphus.gates.languages.python.output_escaping' "
                "not in sys.modules; "
                "assert 'alphus.gates.languages.javascript.output_escaping' "
                "not in sys.modules"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr


def test_root_package_keeps_lazy_output_escaping_export() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import alphus; "
                "assert 'check_output_escaping' in dir(alphus); "
                "assert 'alphus.gates.source.output_escaping' "
                "not in sys.modules; "
                "from alphus import check_output_escaping; "
                "assert check_output_escaping.__module__ == "
                "'alphus.gates.source.output_escaping'"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
