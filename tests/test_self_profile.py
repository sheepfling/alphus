"""Alphus must apply its own policy and package contracts."""

import ast
import re
import tomllib
from importlib.metadata import EntryPoint
from pathlib import Path

from packaging.specifiers import SpecifierSet
from packaging.version import Version

from alphus.config import load_config
from alphus.gates.review.test_quality import python_findings


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
    workflow = Path(".github/workflows/quality.yml").read_text(encoding="utf-8")
    match = re.search(r"^\s+python-version: (\[[^\n]+\])$", workflow, re.MULTILINE)
    assert match is not None

    limits = SpecifierSet(metadata["project"]["requires-python"])
    lower = Version(next(item.version for item in limits if item.operator == ">="))
    upper = Version(next(item.version for item in limits if item.operator == "<"))
    assert lower.major == upper.major == 3
    expected = {f"3.{minor}" for minor in range(lower.minor, upper.minor)}
    assert set(ast.literal_eval(match.group(1))) == expected


def test_hosted_dependency_floor_uses_package_metadata() -> None:
    workflow = Path(".github/workflows/quality.yml").read_text(encoding="utf-8")
    floor_job = workflow.split("  minimum-dependencies:", 1)[1]
    assert "python scripts/ci.py --root . --minimum" in floor_job


def test_stub_checker_extras_are_opt_in() -> None:
    metadata = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    extras = metadata["project"]["optional-dependencies"]
    assert any(requirement.startswith("pyright") for requirement in extras["python"])
    assert not any(requirement.startswith("mypy") for requirement in extras["python"])
    assert not any(requirement.startswith("ty==") for requirement in extras["python"])
    assert len(extras["mypy"]) == 1 and extras["mypy"][0].startswith("mypy")
    assert extras["ty"] == ["ty==0.0.91"]
