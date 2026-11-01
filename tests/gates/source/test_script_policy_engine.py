"""Portable launcher-policy checks for shell and Windows command files."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from alphus.config import ScriptPolicy
from alphus.gates.languages.python.script_policy import (
    is_python_cmd_router,
    policy_issues,
)

POLICY = ScriptPolicy(
    extensions=[".sh", ".ps1", ".cmd", ".bat"],
    exclude=[],
    cmd_router_line_limit=12,
    python_module_prefix="scripts",
    launcher_message="use a Python module for operational scripts",
    cmd_message="CMD must route to a Python module",
)


@pytest.mark.parametrize("suffix", [".sh", ".ps1", ".bat"])
def test_non_python_launchers_fail(tmp_path: Path, suffix: str) -> None:
    relative = Path(f"scripts/legacy{suffix}")
    (tmp_path / relative).parent.mkdir()
    (tmp_path / relative).write_text("echo legacy\n", encoding="utf-8")

    assert policy_issues(tmp_path, [relative], POLICY) == [
        f"{relative}: use a Python module for operational scripts"
    ]


def test_short_cmd_router_passes(tmp_path: Path) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "runner.py").write_text("", encoding="utf-8")
    source = (
        '@echo off\ncd /d "%~dp0.."\npy -3 -m scripts.runner %*\nexit /b %errorlevel%\n'
    )
    relative = Path("scripts/run.cmd")
    (tmp_path / relative).write_text(source, encoding="utf-8")

    assert is_python_cmd_router(source, tmp_path, POLICY)
    assert policy_issues(tmp_path, [relative], POLICY) == []


@pytest.mark.parametrize("command", ["powershell -File runner.ps1", "echo work"])
def test_cmd_logic_fails(tmp_path: Path, command: str) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "runner.py").write_text("", encoding="utf-8")
    relative = Path("scripts/run.cmd")
    (tmp_path / relative).write_text(
        f'@echo off\ncd /d "%~dp0.."\n{command}\n'
        "py -3 -m scripts.runner %*\nexit /b %errorlevel%\n",
        encoding="utf-8",
    )

    assert policy_issues(tmp_path, [relative], POLICY) == [
        f"{relative}: CMD must route to a Python module"
    ]


def test_cmd_router_requires_a_real_module_under_the_policy_prefix(
    tmp_path: Path,
) -> None:
    source = (
        '@echo off\ncd /d "%~dp0.."\n'
        "py -3 -m external.runner %*\nexit /b %errorlevel%\n"
    )

    assert not is_python_cmd_router(source, tmp_path, POLICY)


def test_cmd_router_respects_the_configured_line_limit(tmp_path: Path) -> None:
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/runner.py").write_text("", encoding="utf-8")
    source = (
        '@echo off\ncd /d "%~dp0.."\n'
        "py -3 -m scripts.runner %*\nexit /b %errorlevel%\n" + "\n" * 9
    )

    assert not is_python_cmd_router(source, tmp_path, POLICY)


def test_cmd_router_rejects_a_symlinked_module_outside_the_root(
    tmp_path: Path,
) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    outside = tmp_path.parent / "external_runner.py"
    outside.write_text("", encoding="utf-8")
    try:
        (scripts / "runner.py").symlink_to(outside)
    except OSError:
        pytest.skip("the host does not support symlinks")
    source = (
        '@echo off\ncd /d "%~dp0.."\npy -3 -m scripts.runner %*\nexit /b %errorlevel%\n'
    )

    assert not is_python_cmd_router(source, tmp_path, POLICY)


def test_module_prefix_must_be_a_dotted_python_identifier() -> None:
    with pytest.raises(ValidationError):
        ScriptPolicy(
            extensions=[".cmd"],
            exclude=[],
            cmd_router_line_limit=12,
            python_module_prefix="scripts/../outside",
            launcher_message="use Python",
            cmd_message="route to Python",
        )
