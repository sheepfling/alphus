"""Keep the documented consumer profile valid and tool ownership explicit."""

from __future__ import annotations

from pathlib import Path

from alphus.config import CommandRunStep, RuleRunStep, load_config

_POLICY = Path("examples/consumer/quality-gates.toml")


def test_consumer_example_composes_portable_rules_and_native_tools() -> None:
    config = load_config(_POLICY)
    orchestration = config.orchestration
    assert orchestration is not None
    profile = orchestration.profile("check")
    assert profile is not None
    steps = {step.name: step for step in orchestration.steps}

    assert [steps[name].kind for name in profile.steps] == [
        "rule",
        "rule",
        "rule",
        "rule",
        "rule",
        "rule",
        "rule",
        "command",
        "command",
        "command",
        "command",
        "command",
    ]
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
    )

    markdown = steps["Markdown format"]
    assert isinstance(markdown, CommandRunStep)
    assert markdown.argv == (
        "rumdl",
        "fmt",
        "--check",
        "--no-cache",
        "{files}",
    )
    assert markdown.files is not None
    assert markdown.files.include == ("**/*.[mM][dD]", "*.[mM][dD]")

    assert steps["Python lint"].argv == (
        "{python}",
        "-m",
        "ruff",
        "check",
        "src",
        "tests",
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
    profile = orchestration.profile("docs")
    assert profile is not None
    assert profile.steps == ("Markdown links and graph", "Markdown format")
