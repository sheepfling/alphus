"""Configured fix commands are visible before any file is changed."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from alphus.cli import main
from alphus.config import CommandRunStep, FileInventoryPolicy


def _repository(root: Path) -> None:
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / "sample.txt").write_text("original", encoding="utf-8")
    append = (
        "from pathlib import Path; import sys; "
        "p = Path(sys.argv[1]); p.write_text(p.read_text() + sys.argv[2])"
    )
    step_one = (
        "[[orchestration.steps]]\n"
        'kind = "command"\n'
        'name = "First"\n'
        'argv = ["{python}", "-c", "pass", "{files}"]\n'
        f'fix_argv = ["{{python}}", "-c", {json.dumps(append)}, "{{files}}", "A"]\n'
        'files = { include = ["*.txt"] }\n'
    )
    step_two = (
        "[[orchestration.steps]]\n"
        'kind = "command"\n'
        'name = "Second"\n'
        'argv = ["{python}", "-c", "pass", "{files}"]\n'
        f'fix_argv = ["{{python}}", "-c", {json.dumps(append)}, "{{files}}", "B"]\n'
        'files = { include = ["*.txt"] }\n'
    )
    (root / "quality.toml").write_text(
        "schema_version = 1\n"
        "[files]\n"
        'include = ["*.txt"]\n'
        "exclude = []\n"
        "[orchestration]\n"
        'default_profile = "check"\n'
        + step_one
        + step_two
        + "[[orchestration.profiles]]\n"
        'name = "check"\n'
        'steps = ["First", "Second"]\n',
        encoding="utf-8",
    )


def _arguments(root: Path) -> list[str]:
    return ["--root", str(root), "--config", "quality.toml", "--profile", "check"]


def test_fix_plan_is_read_only_and_apply_uses_profile_order(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _repository(tmp_path)
    arguments = _arguments(tmp_path)
    assert main([*arguments, "--fix-plan", "--json"]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert [
        (step["name"], step["fixable"], step["files"]) for step in plan["steps"]
    ] == [
        ("First", True, ["sample.txt"]),
        ("Second", True, ["sample.txt"]),
    ]
    assert (tmp_path / "sample.txt").read_text(encoding="utf-8") == "original"

    assert (
        main(
            [*arguments, "--apply-fixes", "--fix-step", "Second", "--fix-step", "First"]
        )
        == 0
    )
    assert (tmp_path / "sample.txt").read_text(encoding="utf-8") == "originalAB"
    assert "APPLIED First" in capsys.readouterr().out


def test_apply_requires_named_fixers_and_rejects_unknown_steps(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _repository(tmp_path)
    arguments = _arguments(tmp_path)
    assert main([*arguments, "--apply-fixes"]) == 2
    assert "requires at least one --fix-step" in capsys.readouterr().err
    assert main([*arguments, "--apply-fixes", "--fix-step", "Missing"]) == 2
    assert "not in the selected profile" in capsys.readouterr().err
    assert (tmp_path / "sample.txt").read_text(encoding="utf-8") == "original"


def test_fix_command_requires_a_file_scope() -> None:
    with pytest.raises(ValidationError, match="files policy"):
        CommandRunStep(
            kind="command",
            name="Unsafe scope",
            argv=("tool",),
            fix_argv=("tool", "--fix"),
        )
    with pytest.raises(ValidationError, match="one complete fix argument"):
        CommandRunStep(
            kind="command",
            name="Embedded placeholder",
            argv=("tool", "{files}"),
            fix_argv=("tool", "--files={files}", "{files}"),
            files=FileInventoryPolicy(include=("*.py",)),
        )
