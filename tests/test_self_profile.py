"""Alphus must apply its own review policy in the regular check profile."""

from pathlib import Path

from alphus.config import load_config
from alphus.test_quality import python_findings


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
        "Numeric review",
        "Test review",
        "Input contract review",
    }.issubset(check.steps)

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
