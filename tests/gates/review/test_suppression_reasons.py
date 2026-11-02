"""Tests for consumer-selected reasons on Ruff suppression comments."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from alphus.config import (
    SuppressionReasonException,
    SuppressionReasonPolicy,
    load_config,
)
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


def test_string_and_docstring_lookalikes_are_not_inline_directives() -> None:
    source = '''"""Example: # noqa: E402"""
text = "# noqa: E402"
'''
    assert (
        suppression_reason_findings(
            source, SuppressionReasonPolicy(extensions=(".py",))
        )
        == []
    )


def test_named_file_level_ruff_directives_are_audited_and_blankets_are_unknown() -> (
    None
):
    findings = suppression_reason_findings(
        "# ruff: noqa: E402, F401\n# noqa\n",
        SuppressionReasonPolicy(extensions=(".py",), rule_codes=("E402", "F401")),
        path="src/package.py",
    )
    assert len(findings) == 2
    assert findings[0].line == 1
    assert "E402, F401" in findings[0].message
    assert findings[1].line == 2
    assert "unknown to this audit" in findings[1].message


def test_scoped_exception_satisfies_reason_and_stale_site_is_reported() -> None:
    exception = SuppressionReasonException(
        path="src/package.py",
        rule_code="E402",
        line=1,
        reason="Plugin bootstrap must precede this optional runtime import.",
    )
    policy = SuppressionReasonPolicy(extensions=(".py",), exceptions=(exception,))
    assert (
        suppression_reason_findings(
            "import optional_runtime  # noqa: E402\n",
            policy,
            path="src/package.py",
        )
        == []
    )

    findings = suppression_reason_findings(
        "\nimport optional_runtime  # noqa: E402\n",
        policy,
        path="src/package.py",
    )
    assert len(findings) == 2
    assert findings[0].line == 2
    assert findings[1].line == 1
    assert "stale exception" in findings[1].message


def test_selected_code_in_a_multi_code_directive_requires_a_reason() -> None:
    findings = suppression_reason_findings(
        "import optional_runtime  # noqa: F401, E402\n",
        SuppressionReasonPolicy(extensions=(".py",)),
    )
    assert len(findings) == 1
    assert "E402" in findings[0].message
    assert "F401" not in findings[0].message


def test_code_case_matches_ruff_native_noqa_syntax() -> None:
    policy = SuppressionReasonPolicy(extensions=(".py",), rule_codes=("E402",))

    # Ruff accepts case-insensitive `noqa`, but rule codes remain uppercase.
    uppercase_code = suppression_reason_findings(
        "value = 1\nimport optional_runtime  # NOQA: E402\n",
        policy,
        path="src/package.py",
    )
    lowercase_code = suppression_reason_findings(
        "value = 1\nimport optional_runtime  # noqa: e402\n",
        policy,
        path="src/package.py",
    )

    assert len(uppercase_code) == 1
    assert uppercase_code[0].line == 2
    assert lowercase_code == []


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


def test_source_encoding_cookie_preserves_suppression_comments(tmp_path: Path) -> None:
    path = tmp_path / "encoded.py"
    path.write_bytes(
        "# coding: latin-1\n"
        "value = 'café'\n"
        "import optional_runtime  # noqa: E402\n".encode("latin-1")
    )

    findings = check_suppression_reasons(
        tmp_path,
        [Path("encoded.py")],
        SuppressionReasonPolicy(extensions=(".py",), rule_codes=("E402",)),
    )

    assert len(findings) == 1
    assert findings[0].path == "encoded.py"
    assert findings[0].line == 3
    assert "E402" in findings[0].message


def test_ruff_per_file_ignores_require_reasons_for_selected_codes(
    tmp_path: Path,
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src/app.py").write_text("value = 1\n", encoding="utf-8")
    (tmp_path / "tests/test_app.py").write_text("value = 1\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[tool.ruff.lint.per-file-ignores]\n"
        '"src/**" = ["E402", "F401"]\n'
        '"tests/**" = ["F401"]\n',
        encoding="utf-8",
    )
    policy = SuppressionReasonPolicy(
        extensions=(".py",), rule_codes=("E402",), reason_delimiter="--"
    )

    findings = check_suppression_reasons(
        tmp_path,
        [Path("src/app.py"), Path("tests/test_app.py")],
        policy,
    )

    assert len(findings) == 1
    assert findings[0].path == "pyproject.toml"
    assert findings[0].line == 2
    assert "E402" in findings[0].message
    assert "src/app.py" in findings[0].message


def test_ruff_per_file_ignore_comment_rationale_and_unselected_codes_are_accepted(
    tmp_path: Path,
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src/app.py").write_text("value = 1\n", encoding="utf-8")
    (tmp_path / "tests/test_app.py").write_text("value = 1\n", encoding="utf-8")
    (tmp_path / "ruff.toml").write_text(
        "[lint.per-file-ignores]\n"
        '"src/**" = ["E402"] # -- plugin bootstrap order\n'
        '"tests/**" = ["F401"]\n',
        encoding="utf-8",
    )

    findings = check_suppression_reasons(
        tmp_path,
        [Path("src/app.py"), Path("tests/test_app.py")],
        SuppressionReasonPolicy(
            extensions=(".py",), rule_codes=("E402",), reason_delimiter="--"
        ),
    )

    assert findings == []


def test_inherited_ruff_config_is_scanned_within_the_repository_root(
    tmp_path: Path,
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src/app.py").write_text("value = 1\n", encoding="utf-8")
    (tmp_path / "base.toml").write_text(
        '[lint.per-file-ignores]\n"src/**" = ["E402"]\n', encoding="utf-8"
    )
    (tmp_path / "ruff.toml").write_text('extend = "base.toml"\n', encoding="utf-8")

    findings = check_suppression_reasons(
        tmp_path,
        [Path("src/app.py")],
        SuppressionReasonPolicy(extensions=(".py",), rule_codes=("E402",)),
    )

    assert len(findings) == 1
    assert findings[0].path == "base.toml"
    assert "no rationale" in findings[0].message


def test_inherited_ruff_config_outside_root_is_not_evaluated(tmp_path: Path) -> None:
    (tmp_path / "ruff.toml").write_text(
        'extend = "../outside.toml"\n', encoding="utf-8"
    )

    findings = check_suppression_reasons(
        tmp_path,
        [],
        SuppressionReasonPolicy(extensions=(".py",), rule_codes=("E402",)),
    )

    assert len(findings) == 1
    assert "missing or outside the repository root" in findings[0].message


def test_inherited_ruff_config_cycle_is_bounded(tmp_path: Path) -> None:
    (tmp_path / "ruff.toml").write_text('extend = "base.toml"\n', encoding="utf-8")
    (tmp_path / "base.toml").write_text('extend = "ruff.toml"\n', encoding="utf-8")

    findings = check_suppression_reasons(
        tmp_path,
        [],
        SuppressionReasonPolicy(extensions=(".py",), rule_codes=("E402",)),
    )

    assert len(findings) == 1
    assert "cyclic or exceeds the depth limit" in findings[0].message


def test_ruff_extend_per_file_ignores_are_audited_and_accept_exact_exceptions(
    tmp_path: Path,
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src/app.py").write_text("value = 1\n", encoding="utf-8")
    (tmp_path / "ruff.toml").write_text(
        '[lint.extend-per-file-ignores]\n"src/**" = ["E402"]\n',
        encoding="utf-8",
    )
    exception = SuppressionReasonException(
        path="ruff.toml",
        rule_code="E402",
        line=2,
        reason="Bootstrap module imports before plugin registration.",
    )

    findings = check_suppression_reasons(
        tmp_path,
        [Path("src/app.py")],
        SuppressionReasonPolicy(
            extensions=(".py",), rule_codes=("E402",), exceptions=(exception,)
        ),
    )

    assert findings == []


def test_moved_config_exception_is_reported_stale(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src/app.py").write_text("value = 1\n", encoding="utf-8")
    (tmp_path / "ruff.toml").write_text(
        '[lint.per-file-ignores]\n"src/**" = ["E402"]\n',
        encoding="utf-8",
    )
    exception = SuppressionReasonException(
        path="ruff.toml",
        rule_code="E402",
        line=3,
        reason="Bootstrap module imports before plugin registration.",
    )

    findings = check_suppression_reasons(
        tmp_path,
        [Path("src/app.py")],
        SuppressionReasonPolicy(
            extensions=(".py",), rule_codes=("E402",), exceptions=(exception,)
        ),
    )

    assert len(findings) == 2
    assert any("no rationale" in finding.message for finding in findings)
    assert any("stale exception" in finding.message for finding in findings)


def test_unreadable_selected_file_is_not_reported_as_an_empty_audit(
    tmp_path: Path,
) -> None:
    findings = check_suppression_reasons(
        tmp_path,
        [Path("missing.py")],
        SuppressionReasonPolicy(extensions=(".py",)),
    )
    assert len(findings) == 1
    assert "not evaluated" in findings[0].message


def test_tokenization_failure_is_not_reported_as_an_empty_audit() -> None:
    findings = suppression_reason_findings(
        "text = '''unterminated", SuppressionReasonPolicy(extensions=(".py",))
    )
    assert len(findings) == 1
    assert "tokenization failed" in findings[0].message


def test_suppression_policy_rejects_duplicates_and_invalid_codes() -> None:
    with pytest.raises(ValidationError):
        SuppressionReasonPolicy(extensions=(".py",), rule_codes=("E402", "E402"))
    with pytest.raises(ValidationError):
        SuppressionReasonPolicy(extensions=(".py",), rule_codes=("all",))
    with pytest.raises(ValidationError):
        SuppressionReasonPolicy(
            extensions=(".py",),
            exceptions=(
                SuppressionReasonException(
                    path="src/package.py",
                    rule_code="F401",
                    line=1,
                    reason="This exception belongs to a different selected rule.",
                ),
            ),
        )


def test_sample_profile_is_opt_in_and_selects_only_suppression_reasons() -> None:
    config = load_config(Path("examples/consumer/lint-suppressions.toml"))
    plan = config.orchestration.resolve_profile("suppression-review")
    assert plan is not None
    assert plan.steps == ("Suppression reasons",)
