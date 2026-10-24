"""The resolved profile plan is inspectable without running native tools."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from alphus.cli import main


def test_plan_shows_native_and_custom_steps_without_running_them(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "README.md").write_text("# Example\n", encoding="utf-8")
    (tmp_path / "quality-gates.toml").write_text(
        'schema_version = 1\ntools = ["rumdl", "prettier"]\n'
        '[[orchestration.steps]]\nkind = "command"\nname = "Local smoke"\n'
        'argv = ["{python}", "-c", "from pathlib import Path; Path(\'ran\').touch()"]\n',
        encoding="utf-8",
    )
    arguments = ["--root", str(tmp_path), "--plan"]
    assert main([*arguments, "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["profile"] == "check"
    assert payload["profiles"] == ["check"]
    assert [step["name"] for step in payload["steps"]] == [
        "Markdown style",
        "JSON format",
        "Local smoke",
    ]
    markdown, json_step, smoke = payload["steps"]
    assert markdown["applicable"] is True
    assert markdown["selected_files"] == ["README.md"]
    assert markdown["expanded_argv"] == ["rumdl", "check", "README.md"]
    assert markdown["fixable"] is True
    assert json_step["applicable"] is False
    assert json_step["selected_files"] == []
    assert "expanded_argv" not in json_step
    assert smoke["applicable"] is True
    assert smoke["fixable"] is False
    assert not (tmp_path / "ran").exists()

    assert main([*arguments, "--output", "plain"]) == 0
    human = capsys.readouterr().out
    assert "MAINLINE COMMAND Markdown style: 1 file(s), fixer available" in human
    assert "NOT APPLICABLE COMMAND JSON format: 0 file(s)" in human
    assert "MAINLINE COMMAND Local smoke: unscoped" in human
    assert not (tmp_path / "ran").exists()


def test_output_option_rejects_unknown_human_format() -> None:
    assert main(["--output", "compact"]) == 2


def test_plan_rejects_missing_selected_rule_policy(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "quality-gates.toml").write_text(
        'schema_version = 1\ntools = ["rumdl"]\n'
        '[[orchestration.steps]]\nkind = "rule"\n'
        'name = "Python structure"\nrule = "python-style"\n',
        encoding="utf-8",
    )
    assert main(["--root", str(tmp_path), "--plan"]) == 2
    assert "top-level [files]" in capsys.readouterr().err


def test_plan_skips_directory_resolution_for_an_empty_file_scope(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "quality-gates.toml").write_text(
        "schema_version = 1\n"
        '[[orchestration.steps]]\nkind = "command"\nname = "Absent source"\n'
        'argv = ["missing-tool", "{files}"]\n'
        'working_directory = "missing-directory"\n'
        'files = { include = ["**/*.cpp"] }\n'
        '[[orchestration.profiles]]\nname = "check"\nsteps = ["Absent source"]\n',
        encoding="utf-8",
    )
    assert main(["--root", str(tmp_path), "--plan", "--json"]) == 0
    step = json.loads(capsys.readouterr().out)["steps"][0]
    assert step["applicable"] is False
    assert step["selected_files"] == []
    assert "expanded_argv" not in step


def test_plan_shows_rule_rollout_and_triage_without_running_rule(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "quality-gates.toml").write_text(
        "schema_version = 1\n"
        '[files]\ninclude = ["*.md"]\n'
        '[checks.line_length.limits]\n".md" = 120\n'
        '[[orchestration.steps]]\nkind = "rule"\n'
        'name = "Line review"\nrule = "line-length"\n'
        'rollout = "provisional"\nseverity = "warning"\npriority = "high"\n'
        '[[orchestration.profiles]]\nname = "check"\nsteps = ["Line review"]\n',
        encoding="utf-8",
    )
    assert main(["--root", str(tmp_path), "--plan", "--json"]) == 0
    step = json.loads(capsys.readouterr().out)["steps"][0]
    assert step["kind"] == "rule"
    assert step["rule"] == "line-length"
    assert step["rollout"] == "provisional"
    assert step["severity"] == "warning"
    assert step["priority"] == "high"
    assert step["fixable"] is False
