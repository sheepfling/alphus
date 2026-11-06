"""Feature-owned shared numeric checks stay unloaded until selected."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    ("selector", "module", "other_module", "policy", "source"),
    (
        (
            "numeric-literals",
            "alphus.gates.review.numeric_literals",
            "alphus.gates.review.scipy_constants",
            '[checks.numeric_literals]\nextensions = [".py"]\n',
            "def area(radius: float) -> float:\n    return 3.14 * radius**2\n",
        ),
        (
            "scipy-constants",
            "alphus.gates.review.scipy_constants",
            "alphus.gates.review.numeric_literals",
            '[checks.scipy_constants]\nextensions = [".py"]\nphysical_constants = true\n',
            "def travel_time(distance: float) -> float:\n    return distance / 299792458\n",
        ),
    ),
)
def test_numeric_feature_module_is_imported_only_when_selected(
    tmp_path: Path,
    selector: str,
    module: str,
    other_module: str,
    policy: str,
    source: str,
) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "example.py").write_text(source, encoding="utf-8")
    (tmp_path / "quality.toml").write_text(
        'schema_version = 1\n\n[files]\ninclude = ["src/**/*.py"]\nexclude = []\n\n'
        + policy,
        encoding="utf-8",
    )
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; from pathlib import Path; "
                "from alphus.cli import main; import alphus.execution.dispatch; "
                "module, other, root, selector = sys.argv[1:]; "
                "assert module not in sys.modules; "
                "assert other not in sys.modules; "
                "assert main(['--root', root, '--config', 'quality.toml', "
                "'--rule', selector, '--report', '--json']) == 0; "
                "assert module in sys.modules; "
                "assert other not in sys.modules"
            ),
            module,
            other_module,
            str(tmp_path),
            selector,
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
