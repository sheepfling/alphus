"""Alphus must apply its own policy and package contracts."""

import tomllib
from importlib.metadata import EntryPoint
from pathlib import Path

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

    policy = config.checks.test_quality
    assert policy is not None
    source = (
        "from pathlib import Path\n"
        "def test_docs():\n"
        "    Path('docs/SELF-CHECK.md').read_text()\n"
    )
    findings = python_findings(source, "tests/test_docs.py", policy)
    assert [item.rule_id for item in findings] == [
        "test-quality.ephemeral-plan-dependency"
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
