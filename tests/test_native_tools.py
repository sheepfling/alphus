"""Common native-tool recipes keep a small consumer policy executable."""

from __future__ import annotations

import subprocess
from io import StringIO
from pathlib import Path

import pytest
from pydantic import ValidationError

from alphus.config import CommandRunStep, load_config, load_config_stream
from alphus.execution.fixes import resolve_fix_plan


def test_native_tool_shortcut_generates_ordered_checks_and_language_profiles() -> None:
    config = load_config_stream(
        StringIO(
            'schema_version = 1\ntools = ["rumdl", "taplo", "mdrepo", "prettier"]\n'
        )
    )
    assert config.files is None
    policy = config.orchestration
    assert policy is not None
    check = policy.resolve_profile("check")
    markdown = policy.resolve_profile("markdown")
    toml = policy.resolve_profile("toml")
    json_profile = policy.resolve_profile("json")
    assert check is not None
    assert check.steps == (
        "Markdown style",
        "TOML format",
        "Markdown links and graph",
        "JSON format",
    )
    assert markdown is not None
    assert markdown.steps == ("Markdown style", "Markdown links and graph")
    assert toml is not None and toml.steps == ("TOML format",)
    assert json_profile is not None and json_profile.steps == ("JSON format",)
    for step in policy.steps:
        assert isinstance(step, CommandRunStep)
        assert step.fix_argv is not None and step.files is not None


@pytest.mark.parametrize(
    ("source", "message"),
    [
        ("schema_version = 1\ntools = []\n", "at least one native tool"),
        ('schema_version = 1\ntools = ["rumdl", "rumdl"]\n', "must not repeat"),
        ('schema_version = 1\ntools = ["eslint"]\n', "unknown native tools"),
        ('schema_version = 1\ntools = "rumdl"\n', "valid list"),
        (
            'schema_version = 1\ntools = ["rumdl"]\n'
            'orchestration_files = ["languages/python.toml"]\n',
            "cannot be combined",
        ),
        (
            'schema_version = 1\ntools = ["rumdl"]\n'
            '[[orchestration.profiles]]\nname = "check"\nsteps = ["Markdown style"]\n',
            "named profiles require explicit orchestration",
        ),
    ],
)
def test_native_tool_shortcut_rejects_ambiguous_configuration(
    source: str, message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        load_config_stream(StringIO(source))


def test_native_tool_fix_plan_uses_git_files_without_running_tools(
    tmp_path: Path,
) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "README.md").write_text("# Example\n", encoding="utf-8")
    (tmp_path / "settings.toml").write_text("value = 1\n", encoding="utf-8")
    (tmp_path / "data.json").write_text("{}\n", encoding="utf-8")
    path = tmp_path / "quality-gates.toml"
    path.write_text(
        'schema_version = 1\ntools = ["rumdl", "mdrepo", "taplo", "prettier"]\n',
        encoding="utf-8",
    )
    policy = load_config(path).orchestration
    assert policy is not None
    entries = resolve_fix_plan(tmp_path, path, policy, "check")
    assert [(entry.name, entry.files) for entry in entries] == [
        ("Markdown style", ("README.md",)),
        ("Markdown links and graph", ("README.md",)),
        ("TOML format", ("quality-gates.toml", "settings.toml")),
        ("JSON format", ("data.json",)),
    ]
    assert all(entry.fixable for entry in entries)
    assert entries[1].expanded_argv is not None
    assert entries[1].expanded_argv[-2:] == ("fix", "README.md")
    assert entries[2].expanded_argv == (
        "taplo",
        "fmt",
        "quality-gates.toml",
        "settings.toml",
    )


def test_native_tools_compose_with_custom_steps_without_repeating_commands() -> None:
    config = load_config_stream(
        StringIO(
            'schema_version = 1\ntools = ["rumdl"]\n'
            '[orchestration]\nfailure_threshold = "warning"\n'
            '[[orchestration.steps]]\nkind = "command"\n'
            'name = "Python tests"\nargv = ["{python}", "-m", "pytest"]\n'
        )
    )
    policy = config.orchestration
    assert policy is not None
    assert policy.failure_threshold == "warning"
    check = policy.resolve_profile("check")
    assert check is not None
    assert check.steps == ("Markdown style", "Python tests")
    markdown = policy.resolve_profile("markdown")
    assert markdown is not None and markdown.steps == ("Markdown style",)
