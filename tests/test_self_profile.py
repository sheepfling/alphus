"""Alphus must apply its own policy and package contracts."""

import ast
import os
import re
import subprocess
import tomllib
from importlib.metadata import EntryPoint
from pathlib import Path

import pytest
import yaml
from packaging.specifiers import SpecifierSet
from packaging.version import Version

from alphus.config import load_config
from alphus.gates.review.test_quality import python_findings
from alphus.gates.source.runners import SOURCE_RULE_RUNNERS


def test_self_check_enforces_review_and_repository_toml() -> None:
    config = load_config(Path("quality-gates.toml"))
    orchestration = config.orchestration
    assert orchestration is not None
    check = orchestration.resolve_profile("check")
    assert check is not None
    assert orchestration.failure_threshold == "warning"
    assert {
        "TOML syntax",
        "Python format",
        "Python types",
        "Python package imports",
        "Python compatibility imports",
        "Comment markers",
        "CLI contracts",
        "Numeric review",
        "Test review",
        "Input contract review",
    }.issubset(check.steps)
    assert "Markdown shell fences" not in check.steps
    markdown_review = orchestration.resolve_profile("markdown-shell-review")
    assert markdown_review is not None
    assert markdown_review.steps == ("Markdown shell fences",)
    steps = {step.name: step for step in orchestration.steps}
    for name in ("Python lint", "Python format"):
        command = steps[name]
        assert command.kind == "command"
        assert command.fix_argv is not None
        assert command.files is not None
        assert "--force-exclude" in command.argv
        assert "--force-exclude" in command.fix_argv

    policy = config.checks.test_quality
    assert policy is not None
    source = (
        "from pathlib import Path\n"
        "def test_docs():\n"
        "    Path('docs/SELF-CHECK.md').read_text()\n"
    )
    findings = python_findings(source, "tests/test_docs.py", policy)
    assert [item.rule_id for item in findings] == [
        "alphus/python/none/testing/ephemeral-plan-dependency"
    ]


def test_self_check_scopes_semantic_result_rules_to_review_detectors() -> None:
    config = load_config(Path("quality-gates.toml"))
    policy = config.checks.python_style
    assert policy is not None
    assert {
        "src/alphus/gates/review/provenance_ownership.py",
        "src/alphus/gates/review/rendered_value_reparsed.py",
        "src/alphus/gates/review/unexplained_empty_results.py",
    }.issubset(policy.semantic_result_paths)


def test_self_profile_python_style_requires_exact_result_api_scope(
    tmp_path: Path, pytestconfig: pytest.Config
) -> None:
    config = load_config(Path("quality-gates.toml"))
    files = [Path("src/alphus/gates/review/provenance_ownership.py")]
    target = tmp_path / files[0]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "def candidate() -> tuple[str, str, int]:\n    return 'path', 'owner', 1\n",
        encoding="utf-8",
    )

    policy = config.checks.python_style
    assert policy is not None
    assert not policy.semantic_result_apis
    runner = SOURCE_RULE_RUNNERS["python-style"]
    assert runner(tmp_path, files, config) == {}
    assert runner(Path(pytestconfig.rootpath), files, config) == {}


def test_self_profile_excludes_only_the_lazy_provider_spike_file() -> None:
    config = load_config(Path("quality-gates.toml"))
    policy = config.checks.python_style
    assert policy is not None
    assert "scripts/registry_spike/provider_factory.py" in policy.exclude
    assert "scripts/registry_spike/**" not in policy.exclude


def test_declared_script_entry_points_resolve_to_callables() -> None:
    metadata = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    project = metadata["project"]
    assert project["scripts"]
    for table, group in (
        ("scripts", "console_scripts"),
        ("gui-scripts", "gui_scripts"),
    ):
        for name, reference in project.get(table, {}).items():
            target = EntryPoint(name=name, value=reference, group=group).load()
            assert callable(target), f"{group} entry point {name!r} is not callable"


def test_checker_python_range_matches_hosted_matrix() -> None:
    metadata = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    workflow = Path(".github/workflows/self-quality.yml").read_text(encoding="utf-8")
    match = re.search(r"^\s+python-version: (\[[^\n]+\])$", workflow, re.MULTILINE)
    assert match is not None

    limits = SpecifierSet(metadata["project"]["requires-python"])
    lower = Version(next(item.version for item in limits if item.operator == ">="))
    upper = Version(next(item.version for item in limits if item.operator == "<"))
    assert lower.major == upper.major == 3
    expected = {f"3.{minor}" for minor in range(lower.minor, upper.minor)}
    assert set(ast.literal_eval(match.group(1))) == expected


def test_hosted_dependency_floor_uses_package_metadata() -> None:
    workflow = Path(".github/workflows/self-quality.yml").read_text(encoding="utf-8")
    floor_job = workflow.split("  minimum-dependencies:", 1)[1]
    assert "python scripts/ci.py --root . --minimum" in floor_job


def test_source_family_self_review_propagates_pipeline_errors_without_blocking_advisories(
    tmp_path: Path,
) -> None:
    workflow = yaml.safe_load(
        Path(".github/workflows/self-source-family-import-review.yml").read_text(
            encoding="utf-8"
        )
    )
    review_step = next(
        step
        for step in workflow["jobs"]["review"]["steps"]
        if step.get("name")
        == "Review Alphus source families and retain the complete report"
    )
    assert review_step["shell"] == "bash"
    assert review_step["run"].startswith("set -o pipefail\n")
    assert (
        '| tee "$RUNNER_TEMP/alphus-source-family-import-review.json"'
        in (review_step["run"])
    )

    policy = tomllib.loads(
        Path(".github/alphus-self-source-families.toml").read_text(encoding="utf-8")
    )
    orchestration = policy["orchestration"]
    assert orchestration["failure_threshold"] == "warning"
    assert orchestration["steps"][0]["rollout"] == "provisional"

    failing_command = review_step["run"].replace("alphus --root .", "false --root .", 1)
    environment = {**os.environ, "RUNNER_TEMP": str(tmp_path)}
    result = subprocess.run(
        ["bash", "-e", "-c", failing_command],
        check=False,
        capture_output=True,
        cwd=tmp_path,
        env=environment,
        text=True,
    )
    assert result.returncode != 0
    assert (tmp_path / "alphus-source-family-import-review.json").is_file()


def test_stub_checker_extras_are_opt_in() -> None:
    metadata = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    extras = metadata["project"]["optional-dependencies"]
    assert any(requirement.startswith("pyright") for requirement in extras["python"])
    assert not any(requirement.startswith("mypy") for requirement in extras["python"])
    assert not any(requirement.startswith("ty==") for requirement in extras["python"])
    assert len(extras["mypy"]) == 1 and extras["mypy"][0].startswith("mypy")
    assert extras["ty"] == ["ty==0.0.91"]
