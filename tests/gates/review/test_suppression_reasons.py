"""Tests for consumer-selected reasons on Ruff suppression comments."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from alphus.config import SuppressionReasonPolicy, load_config
from alphus.gates.review.suppression_reasons import (
    check_suppression_reasons,
    suppression_reason_findings,
)


def test_selected_inline_suppression_without_reason_is_reported_at_comment_line() -> (
    None
):
    findings = suppression_reason_findings(
        "import optional_runtime  # noqa: E402\n",
        SuppressionReasonPolicy(extensions=(".py",)),
        path="src/package.py",
    )

    assert len(findings) == 1
    assert findings[0].rule_id == "alphus/python/none/style/missing-suppression-reason"
    assert findings[0].line == 1
    assert findings[0].severity == "info"
    assert "Ruff still owns" in findings[0].message


def test_reason_and_unselected_directives_are_accepted() -> None:
    source = """import optional_runtime  # noqa: E402 -- configure plugins first
import unused  # noqa: F401
# noqa: E402
"""
    assert (
        suppression_reason_findings(
            source,
            SuppressionReasonPolicy(extensions=(".py",), rule_codes=("E402",)),
        )
        == []
    )


def test_string_docstring_and_file_level_lookalikes_are_not_inline_directives() -> None:
    source = '''"""Example: # noqa: E402"""
text = "# noqa: E402"
# ruff: noqa: E402
'''
    assert (
        suppression_reason_findings(
            source, SuppressionReasonPolicy(extensions=(".py",))
        )
        == []
    )


def test_selected_code_in_a_multi_code_directive_requires_a_reason() -> None:
    findings = suppression_reason_findings(
        "import optional_runtime  # noqa: F401, E402\n",
        SuppressionReasonPolicy(extensions=(".py",)),
    )
    assert len(findings) == 1
    assert "E402" in findings[0].message
    assert "F401" not in findings[0].message


def test_file_scope_and_exclusions_are_respected(tmp_path: Path) -> None:
    (tmp_path / "included.py").write_text(
        "import local  # noqa: E402\n", encoding="utf-8"
    )
    (tmp_path / "generated.py").write_text(
        "import local  # noqa: E402\n", encoding="utf-8"
    )
    findings = check_suppression_reasons(
        tmp_path,
        [Path("included.py"), Path("generated.py"), Path("included.txt")],
        SuppressionReasonPolicy(extensions=(".py",), exclude=("generated.py",)),
    )
    assert [finding.path for finding in findings] == ["included.py"]


def test_suppression_policy_rejects_duplicates_and_invalid_codes() -> None:
    with pytest.raises(ValidationError):
        SuppressionReasonPolicy(extensions=(".py",), rule_codes=("E402", "E402"))
    with pytest.raises(ValidationError):
        SuppressionReasonPolicy(extensions=(".py",), rule_codes=("all",))


def test_sample_profile_is_opt_in_and_selects_only_suppression_reasons() -> None:
    config = load_config(Path("examples/consumer/lint-suppressions.toml"))
    plan = config.orchestration.resolve_profile("suppression-review")
    assert plan is not None
    assert plan.steps == ("Suppression reasons",)
