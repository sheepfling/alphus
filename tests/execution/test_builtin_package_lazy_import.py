"""Root exports stay compatible without importing gate implementations."""

from __future__ import annotations

import subprocess
import sys


def test_package_import_does_not_load_gate_modules() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import alphus; "
                "assert not any(name.startswith('alphus.gates') "
                "for name in sys.modules); "
                "assert 'check_json_structure' in dir(alphus); "
                "assert 'check_path_discovery' in alphus.__all__; "
                "from alphus import check_json_structure, check_path_discovery; "
                "assert check_json_structure.__module__ == "
                "'alphus.gates.source.json_structure'; "
                "assert check_path_discovery.__module__ == "
                "'alphus.gates.source.path_discovery'"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
