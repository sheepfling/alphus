"""Native ty fixture boundaries retain explicit files and consumer policy."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

from alphus.gates.stubs.typing_fixtures import Checker, build_command, run_case

TY = Checker("ty", "ty")


def test_ty_fixture_argv_overrides_exclusion_without_discarding_config(
    tmp_path: Path,
) -> None:
    command = build_command(TY, tmp_path / "consumer.py", None)
    assert "--no-respect-ignore-files" in command
    assert "--no-force-exclude" in command
    assert "--isolated" not in command
    assert "--config-file" not in command


@pytest.mark.skipif(
    importlib.util.find_spec("ty") is None, reason="native ty is not installed"
)
@pytest.mark.parametrize("boundary", ["configured-exclude", "gitignore", "both"])
def test_native_ty_checks_explicit_fixtures_despite_exclusions(
    tmp_path: Path, boundary: str
) -> None:
    (tmp_path / ".git").mkdir()
    config = '[rules]\ndeprecated = "error"\n'
    if boundary in {"configured-exclude", "both"}:
        config += '[src]\nexclude = ["*.py"]\n'
    if boundary in {"gitignore", "both"}:
        (tmp_path / ".gitignore").write_text("*.py\n", encoding="utf-8")
    (tmp_path / "ty.toml").write_text(config, encoding="utf-8")
    positive = tmp_path / "positive.py"
    positive.write_text("value: int = 1\n", encoding="utf-8")
    negative = tmp_path / "negative.py"
    negative.write_text('value: int = "wrong"  # expect-error\n', encoding="utf-8")
    # A real forced-exclusion control establishes that this environment can skip
    # the invalid file. The gate must override that policy for explicit fixtures.
    control = build_command(TY, negative, None)
    control.remove("--no-respect-ignore-files")
    control.remove("--no-force-exclude")
    control.insert(-1, "--force-exclude")
    result = subprocess.run(
        control, cwd=tmp_path, capture_output=True, text=True, check=False
    )
    expected_control_exit = 1 if boundary == "gitignore" else 0
    assert result.returncode == expected_control_exit, result.stdout + result.stderr
    assert run_case(TY, positive, root=tmp_path, expect_errors=False)
    assert run_case(TY, negative, root=tmp_path, expect_errors=True)
    assert not run_case(TY, negative, root=tmp_path, expect_errors=False)
    deprecated = tmp_path / "deprecated.py"
    deprecated.write_text(
        "from typing_extensions import deprecated\n"
        '@deprecated("old API")\n'
        "def old() -> int:\n    return 1\n"
        "old()  # expect-error\n",
        encoding="utf-8",
    )
    assert run_case(
        TY,
        deprecated,
        root=tmp_path,
        expect_errors=True,
        required_diagnostics=("deprecated",),
    )
