"""Opt-in native checks against provisioned, distinct checker/target environments."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from alphus.gates.stubs.environments import child_environment, probe_python
from alphus.gates.stubs.typing_fixtures import CHECKERS, build_command

CHECKER = os.environ.get("ALPHUS_TEST_CHECKER_PYTHON")
TARGETS = tuple(
    filter(None, os.environ.get("ALPHUS_TEST_TARGET_PYTHONS", "").split(os.pathsep))
)


@pytest.mark.skipif(
    not CHECKER or not TARGETS,
    reason="provision distinct native environments explicitly",
)
@pytest.mark.parametrize("target_python", TARGETS)
def test_native_checkers_use_target_packages_and_language(
    tmp_path: Path, target_python: str
) -> None:
    assert CHECKER is not None
    checker = probe_python(CHECKER)
    target = probe_python(target_python)
    assert checker.version[:2] >= (3, 11)
    assert checker.prefix != target.prefix
    env = child_environment(os.environ, checker.executable)
    package_probe = (
        "import importlib.util; "
        "assert importlib.util.find_spec('snakemd') is None; "
        "assert importlib.util.find_spec('mdutils') is None"
    )
    subprocess.run([checker.executable, "-I", "-c", package_probe], check=True)
    target_probe = (
        "import snakemd, mdutils; import importlib.metadata as m; "
        "assert not any(d.metadata['Name'].lower() == 'alphus' for d in m.distributions())"
    )
    subprocess.run([target.executable, "-I", "-c", target_probe], check=True)
    # Explicit target flags must override this deliberately conflicting language setting.
    (tmp_path / "pyproject.toml").write_text(
        '[tool.mypy]\npython_version = "3.14"\n[tool.pyright]\npythonVersion = "3.14"\n',
        encoding="utf-8",
    )
    packages = tmp_path / "packages.py"
    packages.write_text(
        "from snakemd import Document\nfrom mdutils import MdUtils\n"
        'Document().add_paragraph("target-only package")\n'
        'MdUtils("target").new_line("target")\n',
        encoding="utf-8",
    )
    versioned = tmp_path / "versioned.py"
    versioned.write_text(
        """from typing import Self
class Fluent:
    def same(self) -> Self:
        return self
""",
        encoding="utf-8",
    )
    for tool in CHECKERS:
        for fixture in (packages, versioned):
            command = build_command(
                tool,
                fixture,
                tmp_path,
                target_python=target.executable,
                python_version=target.minor,
            )
            command[0] = checker.executable
            result = subprocess.run(
                command, cwd=tmp_path, env=env, capture_output=True, text=True
            )
            output = result.stdout + result.stderr
            expect_failure = fixture == versioned and target.version[:2] == (3, 10)
            assert (result.returncode != 0) == expect_failure, output
            if expect_failure:
                assert "Self" in output
