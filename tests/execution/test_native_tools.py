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
        "--no",
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
    assert lint.argv == ("npm", "exec", "--no", "--", "eslint", "{files}")
    assert lint.fix_argv == ("npm", "exec", "--no", "--", "eslint", "--fix", "{files}")
    assert isinstance(format_step, CommandRunStep)
    assert format_step.argv == (
        "npm",
        "exec",
        "--no",
        "--",
        "prettier",
        "--check",
        "{files}",
    )
    assert format_step.fix_argv == (
        "npm",
        "exec",
        "--no",
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


def test_plain_web_language_bundles_share_check_and_language_profiles() -> None:
    config = load_config_stream(
        StringIO('schema_version = 1\nlanguages = ["typescript", "html", "css"]\n')
    )
    policy = config.orchestration
    assert policy is not None
    check = policy.resolve_profile("check")
    assert check is not None
    assert check.steps == (
        "TypeScript lint",
        "TypeScript format",
        "HTML validation",
        "HTML format",
        "CSS lint",
        "CSS format",
    )
    for language in ("typescript", "html", "css"):
        assert policy.resolve_profile(language) is not None
    for step in policy.steps:
        assert isinstance(step, CommandRunStep)
        assert step.argv[:4] == ("npm", "exec", "--no", "--")
        if step.fix_argv is not None:
            assert step.fix_argv[:4] == ("npm", "exec", "--no", "--")


def test_yaml_bundle_uses_yamllint_without_rewriting_native_diagnostics() -> None:
    config = load_config_stream(StringIO('schema_version = 1\nlanguages = ["yaml"]\n'))
    policy = config.orchestration
    assert policy is not None
    check = policy.resolve_profile("check")
    yaml_profile = policy.resolve_profile("yaml")
    assert check is not None and yaml_profile is not None
    assert check.steps == yaml_profile.steps == ("YAML lint",)

    step = policy.steps[0]
    assert isinstance(step, CommandRunStep)
    assert step.argv == ("yamllint", "--", "{files}")
    assert step.fix_argv is None
    assert step.files is not None
    assert step.files.include == ("**/*.yaml", "**/*.yml")
    assert step.files.exclude == ()


def test_language_bundles_and_extra_tools_compose_in_order() -> None:
    config = load_config_stream(
        StringIO(
            'schema_version = 1\nlanguages = ["python", "markdown"]\n'
            'tools = ["eslint-typescript"]\n'
        )
    )
    policy = config.orchestration
    assert policy is not None
    check = policy.resolve_profile("check")
    assert check is not None
    assert check.steps == (
        "Python lint",
        "Python format",
        "Python types",
        "Python tests",
        "Markdown style",
        "Markdown links and graph",
        "TypeScript lint",
    )
    typescript = policy.resolve_profile("typescript")
    assert typescript is not None and typescript.steps == ("TypeScript lint",)


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


def test_yaml_consumer_example_selects_the_yaml_bundle() -> None:
    config = load_config(Path("examples/yaml/quality-gates.toml"))
    policy = config.orchestration
    assert policy is not None
    check = policy.resolve_profile("check")
    yaml_profile = policy.resolve_profile("yaml")
    assert check is not None and yaml_profile is not None
    assert check.steps == yaml_profile.steps == ("YAML lint",)


def test_framework_shortcuts_keep_typescript_and_templates_scoped() -> None:
    config = load_config_stream(
        StringIO(
            'schema_version = 1\ntools = ["eslint-typescript", '
            '"prettier-typescript", "eslint-angular-template"]\n'
        )
    )
    policy = config.orchestration
    assert policy is not None
    typescript = policy.resolve_profile("typescript")
    html = policy.resolve_profile("html")
    assert typescript is not None
    assert typescript.steps == ("TypeScript lint", "TypeScript format")
    assert html is not None and html.steps == ("Angular template lint",)
    lint, format_step, template = policy.steps
    assert isinstance(lint, CommandRunStep)
    assert isinstance(format_step, CommandRunStep)
    assert isinstance(template, CommandRunStep)
    typescript_scope = ("**/*.ts", "**/*.tsx", "**/*.mts", "**/*.cts")
    assert lint.files is not None and lint.files.include == typescript_scope
    assert (
        format_step.files is not None and format_step.files.include == typescript_scope
    )
    assert template.files is not None and template.files.include == ("**/*.html",)


def test_html_and_css_shortcuts_keep_plain_markup_separate_from_angular() -> None:
    config = load_config_stream(
        StringIO(
            'schema_version = 1\ntools = ["html-validate", "prettier-html", '
            '"stylelint", "prettier-css"]\n'
        )
    )
    policy = config.orchestration
    assert policy is not None
    html = policy.resolve_profile("html")
    css = policy.resolve_profile("css")
    assert html is not None and html.steps == ("HTML validation", "HTML format")
    assert css is not None and css.steps == ("CSS lint", "CSS format")
    validation, html_format, css_lint, css_format = policy.steps
    assert all(
        isinstance(step, CommandRunStep)
        for step in (validation, html_format, css_lint, css_format)
    )
    assert validation.files is not None
    assert validation.files.include == ("**/*.html",)
    assert validation.fix_argv is None
    assert css_lint.files is not None
    assert css_lint.files.include == ("**/*.css",)
    assert css_lint.fix_argv == (
        "npm",
        "exec",
        "--no",
        "--",
        "stylelint",
        "--fix",
        "{files}",
    )


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
            'schema_version = 1\nlanguages = ["javascript"]\ntools = ["eslint"]\n',
            "must not repeat a native tool",
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


def test_pylint_recipe_is_explicit_and_not_part_of_the_python_bundle() -> None:
    optional = load_config_stream(
        StringIO('schema_version = 1\ntools = ["pylint"]\n')
    ).orchestration
    python = load_config_stream(
        StringIO('schema_version = 1\nlanguages = ["python"]\n')
    ).orchestration

    assert optional is not None and python is not None
    optional_check = optional.resolve_profile("check")
    python_check = python.resolve_profile("check")
    assert optional_check is not None
    assert optional_check.steps == ("Python Pylint diagnostics",)
    pylint = optional.steps[0]
    assert isinstance(pylint, CommandRunStep)
    assert pylint.argv == ("pylint", "{files}")
    assert pylint.files is not None and pylint.files.include == ("**/*.py",)
    assert python_check is not None
    assert "Python Pylint diagnostics" not in python_check.steps


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
        'tools = ["eslint-typescript"]\n'
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
        "TypeScript lint",
        "C++ build",
    )
