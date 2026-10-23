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
    json_step = policy.steps[-1]
    assert isinstance(json_step, CommandRunStep)
    assert json_step.argv == (
        "npm",
        "exec",
        "--",
        "prettier",
        "--check",
        "{files}",
    )


def test_javascript_shortcuts_share_a_scoped_language_profile() -> None:
    config = load_config_stream(
        StringIO('schema_version = 1\ntools = ["eslint", "prettier-javascript"]\n')
    )
    policy = config.orchestration
    assert policy is not None
    check = policy.resolve_profile("check")
    javascript = policy.resolve_profile("javascript")
    assert check is not None and javascript is not None
    expected = ("JavaScript lint", "JavaScript format")
    assert check.steps == javascript.steps == expected
    lint, format_step = policy.steps
    assert isinstance(lint, CommandRunStep)
    assert lint.argv == ("npm", "exec", "--", "eslint", "{files}")
    assert lint.fix_argv == ("npm", "exec", "--", "eslint", "--fix", "{files}")
    assert isinstance(format_step, CommandRunStep)
    assert format_step.argv == (
        "npm",
        "exec",
        "--",
        "prettier",
        "--check",
        "{files}",
    )
    assert format_step.fix_argv == (
        "npm",
        "exec",
        "--",
        "prettier",
        "--write",
        "{files}",
    )
    assert lint.files is not None and format_step.files is not None
    expected_scope = ("**/*.js", "**/*.jsx", "**/*.mjs", "**/*.cjs")
    assert lint.files.include == expected_scope
    assert format_step.files.include == expected_scope


def test_language_bundles_expand_to_ordered_native_profiles() -> None:
    config = load_config_stream(
        StringIO(
            "schema_version = 1\nlanguages = "
            '["javascript", "markdown", "python", "toml", "json"]\n'
        )
    )
    policy = config.orchestration
    assert policy is not None
    check = policy.resolve_profile("check")
    assert check is not None
    assert check.steps == (
        "JavaScript lint",
        "JavaScript format",
        "Markdown style",
        "Markdown links and graph",
        "Python lint",
        "Python format",
        "Python types",
        "Python tests",
        "TOML format",
        "JSON format",
    )
    for language in ("javascript", "markdown", "python", "toml", "json"):
        assert policy.resolve_profile(language) is not None


def test_native_tools_compose_with_named_profiles_and_custom_steps() -> None:
    config = load_config_stream(
        StringIO(
            'schema_version = 1\ntools = ["rumdl"]\n'
            '[[orchestration.steps]]\nkind = "command"\n'
            'name = "C++ build"\nargv = ["cmake", "--build", "build"]\n'
            '[[orchestration.profiles]]\nname = "cpp"\nsteps = ["C++ build"]\n'
            '[[orchestration.profiles]]\nname = "check"\nincludes = ["cpp"]\n'
        )
    )
    policy = config.orchestration
    assert policy is not None
    check = policy.resolve_profile("check")
    assert check is not None
    assert check.steps == ("Markdown style", "C++ build")
    assert check.profiles == ("native", "cpp", "check")


def test_javascript_consumer_example_selects_the_shared_profile() -> None:
    config = load_config(Path("examples/javascript/quality-gates.toml"))
    policy = config.orchestration
    assert policy is not None
    check = policy.resolve_profile("check")
    javascript = policy.resolve_profile("javascript")
    assert check is not None and javascript is not None
    assert check.steps == javascript.steps == ("JavaScript lint", "JavaScript format")


@pytest.mark.parametrize(
    ("source", "message"),
    [
        ("schema_version = 1\ntools = []\n", "at least one native tool"),
        ('schema_version = 1\ntools = ["rumdl", "rumdl"]\n', "must not repeat"),
        ('schema_version = 1\ntools = ["unknown-tool"]\n', "unknown native tools"),
        ('schema_version = 1\ntools = "rumdl"\n', "valid list"),
        (
            (
                'schema_version = 1\ntools = ["rumdl"]\n'
                'orchestration_files = ["languages/python.toml"]\n'
            ),
            "cannot be combined",
        ),
        (
            'schema_version = 1\nlanguages = ["cpp"]\n',
            "unknown languages",
        ),
        (
            'schema_version = 1\nlanguages = ["python"]\ntools = ["rumdl"]\n',
            "choose either languages or tools",
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


def test_python_shortcut_orders_lint_format_types_and_tests() -> None:
    config = load_config(Path("examples/python/quality-gates.toml"))
    policy = config.orchestration
    assert policy is not None
    check = policy.resolve_profile("check")
    python = policy.resolve_profile("python")
    assert check is not None and python is not None
    expected = ("Python lint", "Python format", "Python types", "Python tests")
    assert check.steps == expected
    assert python.steps == expected
    lint, format_step, types, tests = policy.steps
    assert isinstance(lint, CommandRunStep)
    assert isinstance(format_step, CommandRunStep)
    assert isinstance(types, CommandRunStep)
    assert isinstance(tests, CommandRunStep)
    assert lint.argv == (
        "{python}",
        "-m",
        "ruff",
        "check",
        "--force-exclude",
        "{files}",
    )
    assert lint.fix_argv is not None and "--fix" in lint.fix_argv
    assert format_step.argv == (
        "{python}",
        "-m",
        "ruff",
        "format",
        "--force-exclude",
        "--check",
        "{files}",
    )
    assert format_step.fix_argv is not None
    assert "--check" not in format_step.fix_argv
    assert lint.files is not None and format_step.files is not None
    assert lint.files.include == ("**/*.py", "**/*.pyi")
    assert types.argv == ("{python}", "-m", "pyright", "--pythonpath", "{python}")
    assert types.files is None and types.fix_argv is None
    assert tests.argv == ("{python}", "-m", "pytest")
    assert tests.files is None and tests.fix_argv is None


def test_language_bundles_compose_with_split_project_profiles(tmp_path: Path) -> None:
    (tmp_path / "languages").mkdir()
    (tmp_path / "languages/cpp.toml").write_text(
        '[[orchestration.steps]]\nkind = "command"\nname = "C++ build"\n'
        'argv = ["cmake", "--build", "build"]\n'
        '[[orchestration.profiles]]\nname = "cpp"\nsteps = ["C++ build"]\n',
        encoding="utf-8",
    )
    config_path = tmp_path / "quality-gates.toml"
    config_path.write_text(
        'schema_version = 1\nlanguages = ["javascript", "markdown"]\n'
        'orchestration_files = ["languages/cpp.toml"]\n'
        "[orchestration]\n"
        '[[orchestration.profiles]]\nname = "check"\nincludes = ["cpp"]\n',
        encoding="utf-8",
    )
    policy = load_config(config_path).orchestration
    assert policy is not None
    check = policy.resolve_profile("check")
    assert check is not None
    assert check.steps == (
        "JavaScript lint",
        "JavaScript format",
        "Markdown style",
        "Markdown links and graph",
        "C++ build",
    )
