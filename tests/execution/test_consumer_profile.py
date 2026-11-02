"""Keep the documented consumer profile valid and tool ownership explicit."""

from __future__ import annotations

import tomllib
from collections.abc import Sequence
from pathlib import Path

import pytest

from alphus.config import (
    CommandRunStep,
    ProseAsControlPolicy,
    RuleRunStep,
    load_config,
)
from alphus.gates.review import runners as review_runners


@pytest.fixture
def examples_root(request: pytest.FixtureRequest) -> Path:
    """Locate published examples from pytest's repository context."""
    return Path(request.config.rootpath) / "examples"


def test_prose_as_control_example_is_scoped_and_provisional(
    examples_root: Path,
) -> None:
    config = load_config(examples_root / "review" / "prose-as-control.toml")
    assert config.files is not None
    assert config.files.include == ("src/render/*.py",)
    policy = config.checks.prose_as_control
    assert policy is not None
    assert policy.source_paths == ("src/render/*.py",)
    orchestration = config.orchestration
    assert orchestration is not None
    plan = orchestration.resolve_profile("semantic-review")
    assert plan is not None
    step = orchestration.steps[0]
    assert isinstance(step, RuleRunStep)
    assert step.rule == "prose-as-control"
    assert step.rollout == "provisional"
    consumption = config.checks.heuristic_total_consumption
    assert consumption is not None
    assert consumption.function_names == ("preserve_text",)
    assert consumption.output_contract == "preserve-unmatched-spans"
    ownership = config.checks.provenance_ownership
    assert ownership is not None
    assert ownership.ownership_basis == "exact-source-span"
    presentation = config.checks.semantic_work_presentation
    assert presentation is not None
    assert presentation.module_role == "presentation"
    normalization = config.checks.parallel_normalization
    assert normalization is not None
    assert normalization.pairs[0].output_contract == "same-output-for-same-input"


def test_rendered_feedback_is_dispatched_only_by_its_dedicated_rule(
    monkeypatch: pytest.MonkeyPatch,
    examples_root: Path,
) -> None:
    config = load_config(examples_root / "review" / "prose-as-control.toml")
    calls: list[str] = []

    def rendered_result(
        root: Path, files: Sequence[Path], policy: ProseAsControlPolicy
    ) -> list[str]:
        calls.append("rendered")
        return ["rendered finding"]

    monkeypatch.setattr(
        review_runners, "check_rendered_value_reparsed", rendered_result
    )

    prose_findings = review_runners.REVIEW_RULE_RUNNERS["prose-as-control"](
        Path("."), (), config
    )
    assert prose_findings == []
    assert calls == []

    rendered_findings = review_runners.REVIEW_RULE_RUNNERS["rendered-value-reparsed"](
        Path("."), (), config
    )
    assert rendered_findings == ["rendered finding"]
    assert calls == ["rendered"]


def test_starter_policy_has_one_scoped_command_and_no_global_inventory(
    examples_root: Path,
) -> None:
    config = load_config(examples_root / "starter" / "quality-gates.toml")
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


def test_markdown_example_pairs_two_fixers_without_duplicate_missing_links(
    examples_root: Path,
) -> None:
    config = load_config(examples_root / "markdown" / "quality-gates.toml")
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
        (examples_root / "markdown" / "mdrepo.toml").read_text(encoding="utf-8")
    )
    assert mdrepo_config["orphans"]["roots"] == ["README.md"]
    assert not mdrepo_config.get("links", {}).get("check-missing-targets", False)


def test_consumer_example_composes_portable_rules_and_native_tools(
    examples_root: Path,
) -> None:
    config = load_config(examples_root / "consumer" / "quality-gates.toml")
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
        "--force-exclude",
        "{files}",
    )
    assert steps["Python lint"].fix_argv == (
        "{python}",
        "-m",
        "ruff",
        "check",
        "--fix",
        "--force-exclude",
        "{files}",
    )
    assert "--force-exclude" in steps["Python format"].argv
    assert "--force-exclude" in steps["Python format"].fix_argv
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


def test_consumer_documentation_profile_has_only_native_doc_owners(
    examples_root: Path,
) -> None:
    config = load_config(examples_root / "consumer" / "quality-gates.toml")
    orchestration = config.orchestration
    assert orchestration is not None
    profile = orchestration.resolve_profile("docs")
    assert profile is not None
    assert profile.steps == ("Markdown style", "Markdown links and graph")


def test_consumer_data_formats_have_separate_profiles_with_format_fixers(
    examples_root: Path,
) -> None:
    config = load_config(examples_root / "consumer" / "quality-gates.toml")
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
    assert steps["JSON format"].fix_argv == (
        "npm",
        "exec",
        "--no",
        "--",
        "prettier",
        "--write",
        "{files}",
    )
    assert steps["TOML syntax"].fix_argv is None
    assert steps["JSON syntax"].fix_argv is None


def test_consumer_policy_path_is_independent_of_working_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, examples_root: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    assert (
        load_config(examples_root / "consumer" / "quality-gates.toml").orchestration
        is not None
    )
