"""Keep the documented consumer profile valid and tool ownership explicit."""

from __future__ import annotations

import tomllib
from pathlib import Path

from alphus.config import CommandRunStep, RuleRunStep, load_config

_POLICY = Path("examples/consumer/quality-gates.toml")


def test_starter_policy_has_one_scoped_command_and_no_global_inventory() -> None:
    config = load_config(Path("examples/starter/quality-gates.toml"))
    assert config.files is None
    orchestration = config.orchestration
    assert orchestration is not None
    plan = orchestration.resolve_profile("check")
    assert plan is not None
    assert plan.steps == ("Markdown style",)
    step = orchestration.steps[0]
    assert isinstance(step, CommandRunStep)
    assert step.files is not None
    assert step.fix_argv == ("rumdl", "fmt", "{files}")


def test_markdown_example_pairs_two_fixers_without_duplicate_missing_links() -> None:
    config = load_config(Path("examples/markdown/quality-gates.toml"))
    assert config.files is None
    orchestration = config.orchestration
    assert orchestration is not None
    plan = orchestration.resolve_profile("check")
    assert plan is not None
    assert plan.steps == ("Markdown style", "Markdown links and graph")
    assert all(
        isinstance(step, CommandRunStep) and step.fix_argv
        for step in orchestration.steps
    )
    mdrepo_config = tomllib.loads(
        Path("examples/markdown/mdrepo.toml").read_text(encoding="utf-8")
    )
    assert mdrepo_config["orphans"]["roots"] == ["README.md"]
    assert not mdrepo_config.get("links", {}).get("check-missing-targets", False)


def test_consumer_example_composes_portable_rules_and_native_tools() -> None:
    config = load_config(_POLICY)
    orchestration = config.orchestration
    assert orchestration is not None
    profile = orchestration.resolve_profile("check")
    assert profile is not None
    steps = {step.name: step for step in orchestration.steps}

    assert len(profile.steps) == 17
    assert [steps[name].kind for name in profile.steps[:7]] == ["rule"] * 7
    assert all(steps[name].kind == "command" for name in profile.steps[7:])
    assert isinstance(steps["Python structure"], RuleRunStep)
    assert isinstance(steps["Markdown links and graph"], CommandRunStep)
    assert steps["Markdown links and graph"].argv == (
        "{python}",
        "-m",
        "mdrepo",
        "--root",
        "{root}",
        "--config",
        "{root}/mdrepo.toml",
        "check",
        "{files}",
    )
    assert steps["Markdown links and graph"].fix_argv is not None
    assert steps["Markdown links and graph"].fix_argv[-2:] == ("fix", "{files}")
    assert steps["Markdown links and graph"].files is not None

    markdown = steps["Markdown style"]
    assert isinstance(markdown, CommandRunStep)
    assert markdown.argv == (
        "rumdl",
        "check",
        "--no-cache",
        "{files}",
    )
    assert markdown.fix_argv == ("rumdl", "fmt", "{files}")
    assert markdown.files is not None
    assert markdown.files.include == ("**/*.[mM][dD]", "*.[mM][dD]")

    assert steps["Python lint"].argv == (
        "{python}",
        "-m",
        "ruff",
        "check",
        "{files}",
    )
    assert steps["Python lint"].fix_argv == (
        "{python}",
        "-m",
        "ruff",
        "check",
        "--fix",
        "{files}",
    )
    assert steps["Python types"].argv == (
        "pyright",
        "--pythonpath",
        "{python}",
        "src",
        "tests",
    )
    assert steps["Python tests"].argv == (
        "{python}",
        "-m",
        "pytest",
        "tests",
        "-q",
    )


def test_consumer_documentation_profile_has_only_native_doc_owners() -> None:
    config = load_config(_POLICY)
    orchestration = config.orchestration
    assert orchestration is not None
    profile = orchestration.resolve_profile("docs")
    assert profile is not None
    assert profile.steps == ("Markdown style", "Markdown links and graph")


def test_consumer_data_formats_have_separate_profiles_with_format_fixers() -> None:
    config = load_config(_POLICY)
    orchestration = config.orchestration
    assert orchestration is not None
    toml = orchestration.resolve_profile("toml")
    json_profile = orchestration.resolve_profile("json")
    check = orchestration.resolve_profile("check")

    assert toml is not None and toml.steps == ("TOML syntax", "TOML format")
    assert json_profile is not None and json_profile.steps == (
        "JSON syntax",
        "JSON format",
    )
    assert check is not None
    assert all(name in check.steps for name in (*toml.steps, *json_profile.steps))
    steps = {step.name: step for step in orchestration.steps}
    assert isinstance(steps["TOML format"], CommandRunStep)
    assert steps["TOML format"].fix_argv == ("taplo", "fmt", "{files}")
    assert isinstance(steps["JSON format"], CommandRunStep)
    assert steps["JSON format"].fix_argv == ("prettier", "--write", "{files}")
    assert steps["TOML syntax"].fix_argv is None
    assert steps["JSON syntax"].fix_argv is None
