"""Tests for consumer-selected reasons on Ruff suppression comments."""

import json
import shutil
import subprocess
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


def test_inline_noqa_after_type_ignore_is_audited() -> None:
    findings = suppression_reason_findings(
        "import optional_runtime  # type: ignore[import-not-found]  # noqa: E402\n",
        SuppressionReasonPolicy(extensions=(".py",), rule_codes=("E402",)),
        path="src/package.py",
    )

    assert len(findings) == 1
    assert findings[0].line == 1
    assert "E402" in findings[0].message


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


def test_file_suppression_prefix_case_and_flake8_forms_match_ruff() -> None:
    source = (
        "# RUFF: noqa: E402\n"
        "# ruff: NOQA: E402\n"
        "# Flake8: noqa: E402\n"
        "# flake8: noqa: E402\n"
        "# ruff: file-ignore[E402]\n"
        "# RUFF: file-ignore[E402]\n"
    )
    findings = suppression_reason_findings(
        source,
        SuppressionReasonPolicy(extensions=(".py",), rule_codes=("E402",)),
        path="src/package.py",
    )

    assert [finding.line for finding in findings] == [2, 4, 5]


def test_file_level_flake8_blanket_is_reported_as_unknown() -> None:
    findings = suppression_reason_findings(
        "# RUFF: noqa\n# ruff: NOQA\n# flake8: noqa\n",
        SuppressionReasonPolicy(extensions=(".py",), rule_codes=("E402",)),
    )

    assert [finding.line for finding in findings] == [2, 3]
    assert all("unknown to this audit" in finding.message for finding in findings)


def test_file_ignore_reason_is_scoped_to_selected_codes() -> None:
    policy = SuppressionReasonPolicy(extensions=(".py",), rule_codes=("E402", "F401"))
    missing = suppression_reason_findings("# ruff: file-ignore[E402, F401]\n", policy)
    documented = suppression_reason_findings(
        "# ruff: file-ignore[E402, F401] -- plugin bootstrap\n", policy
    )

    assert len(missing) == 1
    assert "E402, F401" in missing[0].message
    assert documented == []


@pytest.mark.parametrize(
    ("directive", "suppresses"),
    [
        ("# ruff: file-ignore[E402]", True),
        ("# RUFF: file-ignore[E402]", False),
        ("# flake8: noqa: E402", True),
        ("# ruff: noqa: E402", True),
        ("# RUFF: noqa: E402", False),
    ],
)
def test_file_directives_match_native_ruff(
    tmp_path: Path, directive: str, suppresses: bool
) -> None:
    ruff = shutil.which("ruff")
    if ruff is None:
        pytest.skip("Ruff executable is not installed in this test environment")
    source = f"{directive}\nvalue = 1\nimport os\n"
    (tmp_path / "app.py").write_text(source, encoding="utf-8")
    native = subprocess.run(
        [ruff, "check", "--isolated", "--select", "E402", "app.py"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    findings = suppression_reason_findings(
        source,
        SuppressionReasonPolicy(extensions=(".py",), rule_codes=("E402",)),
        path="app.py",
    )

    assert (native.returncode == 0) is suppresses
    assert bool(findings) is suppresses


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


def test_deleted_source_exception_site_is_reported_stale(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src/new_name.py").write_text("value = 1\n", encoding="utf-8")
    exception = SuppressionReasonException(
        path="src/old_name.py",
        rule_code="E402",
        line=4,
        reason="Bootstrap import must precede plugin registration.",
    )

    findings = check_suppression_reasons(
        tmp_path,
        [Path("src/new_name.py")],
        SuppressionReasonPolicy(extensions=(".py",), exceptions=(exception,)),
    )

    assert len(findings) == 1
    assert findings[0].path == "src/old_name.py"
    assert findings[0].line == 4
    assert "stale after a move or deletion" in findings[0].message


def test_existing_unselected_source_exception_is_not_called_stale(
    tmp_path: Path,
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src/other.py").write_text(
        "import optional_runtime  # noqa: E402\n", encoding="utf-8"
    )
    exception = SuppressionReasonException(
        path="src/other.py",
        rule_code="E402",
        line=1,
        reason="Bootstrap import must precede plugin registration.",
    )

    findings = check_suppression_reasons(
        tmp_path,
        [],
        SuppressionReasonPolicy(extensions=(".py",), exceptions=(exception,)),
    )

    assert len(findings) == 1
    assert findings[0].path == "."
    assert "no selected Python source files" in findings[0].message


def test_deleted_ruff_config_exception_site_is_reported_stale(tmp_path: Path) -> None:
    exception = SuppressionReasonException(
        path="ruff.toml",
        rule_code="E402",
        line=2,
        reason="Bootstrap import must precede plugin registration.",
    )

    findings = check_suppression_reasons(
        tmp_path,
        [],
        SuppressionReasonPolicy(extensions=(".py",), exceptions=(exception,)),
    )

    assert len(findings) == 2
    stale = next(item for item in findings if item.path == "ruff.toml")
    scope = next(item for item in findings if item.path == ".")
    assert stale.line == 2
    assert "stale after a move or deletion" in stale.message
    assert "no selected Python source files" in scope.message


def test_existing_inactive_ruff_config_exception_is_reported_stale(
    tmp_path: Path,
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src/app.py").write_text("value = 1\n", encoding="utf-8")
    (tmp_path / "ruff.toml").write_text('[lint]\nselect = ["E"]\n', encoding="utf-8")
    (tmp_path / "extra.toml").write_text(
        '[lint.per-file-ignores]\n"src/**" = ["E402"]\n', encoding="utf-8"
    )
    exception = SuppressionReasonException(
        path="extra.toml",
        rule_code="E402",
        line=2,
        reason="Bootstrap import must precede plugin registration.",
    )

    findings = check_suppression_reasons(
        tmp_path,
        [Path("src/app.py")],
        SuppressionReasonPolicy(
            extensions=(".py",), rule_codes=("E402",), exceptions=(exception,)
        ),
    )

    assert len(findings) == 1
    assert findings[0].path == "extra.toml"
    assert findings[0].line == 2
    assert "not belong to the active Ruff configuration or its extend chain" in (
        findings[0].message
    )


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


def test_commented_per_file_ignore_header_is_audited_with_multiline_array(
    tmp_path: Path,
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src/app.py").write_text("value = 1\n", encoding="utf-8")
    (tmp_path / "ruff.toml").write_text(
        "[lint.per-file-ignores] # bootstrap imports\n"
        '"src/app.py" = [\n    "E402",\n]\n',
        encoding="utf-8",
    )

    findings = check_suppression_reasons(
        tmp_path,
        [Path("src/app.py")],
        SuppressionReasonPolicy(extensions=(".py",), rule_codes=("E402",)),
    )

    assert len(findings) == 1
    assert findings[0].path == "ruff.toml"
    assert "E402" in findings[0].message
    assert "no rationale" in findings[0].message


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


@pytest.mark.parametrize(
    ("parent_key", "child_key", "expected_audit_count", "expected_ruff_code"),
    [
        ("per-file-ignores", "per-file-ignores", 1, "E402"),
        ("extend-per-file-ignores", "per-file-ignores", 2, None),
        ("per-file-ignores", "extend-per-file-ignores", 2, None),
        ("extend-per-file-ignores", "extend-per-file-ignores", 2, None),
    ],
)
def test_inherited_per_file_merge_matches_native_ruff(
    tmp_path: Path,
    parent_key: str,
    child_key: str,
    expected_audit_count: int,
    expected_ruff_code: str | None,
) -> None:
    ruff = shutil.which("ruff")
    if ruff is None:
        pytest.skip("Ruff executable is not installed in this test environment")
    (tmp_path / "app.py").write_text("value = 1\nimport os\n", encoding="utf-8")
    (tmp_path / "base.toml").write_text(
        f'[lint.{parent_key}]\n"app.py" = ["E402"]\n', encoding="utf-8"
    )
    (tmp_path / "ruff.toml").write_text(
        f'extend = "base.toml"\n[lint.{child_key}]\n"app.py" = ["F401"]\n',
        encoding="utf-8",
    )

    native = subprocess.run(
        [ruff, "check", "--select", "E402,F401", "--output-format", "json", "app.py"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert native.returncode in {0, 1}, native.stdout + native.stderr
    diagnostics = json.loads(native.stdout)
    assert tuple(item["code"] for item in diagnostics) == (
        (expected_ruff_code,) if expected_ruff_code is not None else ()
    )

    findings = check_suppression_reasons(
        tmp_path,
        [Path("app.py")],
        SuppressionReasonPolicy(extensions=(".py",), rule_codes=("E402", "F401")),
    )
    assert len(findings) == expected_audit_count
    assert not any(
        "merge semantics are left to Ruff" in item.message for item in findings
    )


def test_inherited_normal_inline_map_is_skipped_when_local_normal_table_replaces_it(
    tmp_path: Path,
) -> None:
    ruff = shutil.which("ruff")
    if ruff is None:
        pytest.skip("Ruff executable is not installed in this test environment")
    (tmp_path / "app.py").write_text("value = 1\nimport os\n", encoding="utf-8")
    (tmp_path / "base.toml").write_text(
        '[lint]\nper-file-ignores = { "app.py" = ["E402"] }\n',
        encoding="utf-8",
    )
    (tmp_path / "ruff.toml").write_text(
        'extend = "base.toml"\n[lint.per-file-ignores]\n"app.py" = ["F401"]\n',
        encoding="utf-8",
    )

    native = subprocess.run(
        [
            ruff,
            "check",
            "--config",
            "ruff.toml",
            "--select",
            "E402",
            "--output-format",
            "json",
            "app.py",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert native.returncode == 1, native.stdout + native.stderr
    assert [item["code"] for item in json.loads(native.stdout)] == ["E402"]

    findings = check_suppression_reasons(
        tmp_path,
        [Path("app.py")],
        SuppressionReasonPolicy(extensions=(".py",), rule_codes=("E402",)),
    )

    assert findings == []


def test_inherited_extend_inline_map_is_retained_beside_local_normal_table(
    tmp_path: Path,
) -> None:
    ruff = shutil.which("ruff")
    if ruff is None:
        pytest.skip("Ruff executable is not installed in this test environment")
    (tmp_path / "app.py").write_text("value = 1\nimport os\n", encoding="utf-8")
    (tmp_path / "base.toml").write_text(
        '[lint]\nextend-per-file-ignores = { "app.py" = ["E402"] }\n',
        encoding="utf-8",
    )
    (tmp_path / "ruff.toml").write_text(
        'extend = "base.toml"\n[lint.per-file-ignores]\n"app.py" = ["F401"]\n',
        encoding="utf-8",
    )

    native = subprocess.run(
        [
            ruff,
            "check",
            "--config",
            "ruff.toml",
            "--select",
            "E402",
            "--output-format",
            "json",
            "app.py",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert native.returncode == 0, native.stdout + native.stderr
    assert json.loads(native.stdout) == []

    findings = check_suppression_reasons(
        tmp_path,
        [Path("app.py")],
        SuppressionReasonPolicy(extensions=(".py",), rule_codes=("E402",)),
    )

    assert len(findings) == 1
    assert findings[0].path == "base.toml"
    assert "no rationale" in findings[0].message


def test_dot_ruff_toml_takes_discovery_precedence_over_ruff_toml(
    tmp_path: Path,
) -> None:
    ruff = shutil.which("ruff")
    if ruff is None:
        pytest.skip("Ruff executable is not installed in this test environment")
    (tmp_path / "app.py").write_text("value = 1\nimport os\n", encoding="utf-8")
    (tmp_path / ".ruff.toml").write_text(
        '[lint.per-file-ignores]\n"app.py" = ["E402"]\n', encoding="utf-8"
    )
    (tmp_path / "ruff.toml").write_text(
        '[lint.per-file-ignores]\n"app.py" = ["F401"]\n', encoding="utf-8"
    )

    native = subprocess.run(
        [ruff, "check", "--output-format", "json", "app.py"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert native.returncode == 1, native.stdout + native.stderr
    assert [item["code"] for item in json.loads(native.stdout)] == ["F401"]

    findings = check_suppression_reasons(
        tmp_path,
        [Path("app.py")],
        SuppressionReasonPolicy(extensions=(".py",), rule_codes=("E402",)),
    )

    assert len(findings) == 1
    assert findings[0].path == ".ruff.toml"
    assert "E402" in findings[0].message


def test_inherited_ruff_config_outside_root_is_not_evaluated(tmp_path: Path) -> None:
    (tmp_path / "ruff.toml").write_text(
        'extend = "../outside.toml"\n', encoding="utf-8"
    )

    findings = check_suppression_reasons(
        tmp_path,
        [],
        SuppressionReasonPolicy(extensions=(".py",), rule_codes=("E402",)),
    )

    assert len(findings) == 2
    assert any("no selected Python source files" in item.message for item in findings)
    assert any(
        "missing or outside the repository root" in item.message for item in findings
    )


def test_inherited_ruff_config_cycle_is_bounded(tmp_path: Path) -> None:
    (tmp_path / "ruff.toml").write_text('extend = "base.toml"\n', encoding="utf-8")
    (tmp_path / "base.toml").write_text('extend = "ruff.toml"\n', encoding="utf-8")

    findings = check_suppression_reasons(
        tmp_path,
        [],
        SuppressionReasonPolicy(extensions=(".py",), rule_codes=("E402",)),
    )

    assert len(findings) == 2
    assert any("no selected Python source files" in item.message for item in findings)
    assert any("cyclic or exceeds the depth limit" in item.message for item in findings)


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


@pytest.mark.parametrize(
    "form",
    ["multiline-table", "inline-map", "flat-map", "inline-extend-map", "multiline-map"],
)
@pytest.mark.parametrize("with_reason", [False, True])
def test_multiline_ruff_per_file_ignore_matches_native_ruff(
    tmp_path: Path, with_reason: bool, form: str
) -> None:
    ruff = shutil.which("ruff")
    if ruff is None:
        pytest.skip("Ruff executable is not installed in this test environment")
    (tmp_path / "app.py").write_text("value = 1\nimport os\n", encoding="utf-8")
    rationale = " # -- bootstrap import order" if with_reason else ""
    if form == "multiline-table":
        config = f'[lint.per-file-ignores]\n"app.py" = [\n "E402",{rationale}\n]\n'
    elif form == "inline-map":
        config = f'[lint]\nper-file-ignores = {{ "app.py" = ["E402"] }}{rationale}\n'
    elif form == "flat-map":
        config = f'per-file-ignores = {{ "app.py" = ["E402"] }}{rationale}\n'
    elif form == "inline-extend-map":
        config = (
            f'[lint]\nextend-per-file-ignores = {{ "app.py" = ["E402"] }}{rationale}\n'
        )
    else:
        config = (
            '[lint]\nper-file-ignores = {\n "app.py" = [\n  "E402",\n ],\n}'
            f"{rationale}\n"
        )
    (tmp_path / "ruff.toml").write_text(config, encoding="utf-8")

    native = subprocess.run(
        [ruff, "check", "--select", "E402", "--config", "ruff.toml", "app.py"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert native.returncode == 0, native.stdout + native.stderr

    findings = check_suppression_reasons(
        tmp_path,
        [Path("app.py")],
        SuppressionReasonPolicy(extensions=(".py",), rule_codes=("E402",)),
    )
    if with_reason and form != "multiline-map":
        assert findings == []
    else:
        assert len(findings) == 1
        assert findings[0].path == "ruff.toml"
        assert findings[0].line == (1 if form == "flat-map" else 2)
        assert "no rationale" in findings[0].message


@pytest.mark.parametrize(
    ("pattern", "path", "applies"),
    [
        ("!src/**/*.py", "tests/app.py", True),
        ("!src/**/*.py", "src/app.py", False),
        ("__init__.py", "pkg/__init__.py", True),
    ],
)
def test_per_file_globs_match_native_ruff_negation_and_basenames(
    tmp_path: Path, pattern: str, path: str, applies: bool
) -> None:
    ruff = shutil.which("ruff")
    if ruff is None:
        pytest.skip("Ruff executable is not installed in this test environment")
    source = tmp_path / path
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("value = 1\nimport os\n", encoding="utf-8")
    (tmp_path / "ruff.toml").write_text(
        f'[lint.per-file-ignores]\n"{pattern}" = ["E402"]\n', encoding="utf-8"
    )
    native = subprocess.run(
        [ruff, "check", "--select", "E402", "--config", "ruff.toml", path],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    findings = check_suppression_reasons(
        tmp_path,
        [Path(path)],
        SuppressionReasonPolicy(extensions=(".py",), rule_codes=("E402",)),
    )

    assert (native.returncode == 0) is applies
    assert bool(findings) is applies


def test_per_file_code_prefix_matches_native_ruff(
    tmp_path: Path,
) -> None:
    ruff = shutil.which("ruff")
    if ruff is None:
        pytest.skip("Ruff executable is not installed in this test environment")
    (tmp_path / "app.py").write_text("value = 1\nimport os\n", encoding="utf-8")
    (tmp_path / "ruff.toml").write_text(
        '[lint.per-file-ignores]\n"app.py" = ["E4"]\n', encoding="utf-8"
    )
    native = subprocess.run(
        [ruff, "check", "--select", "E402", "--config", "ruff.toml", "app.py"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    findings = check_suppression_reasons(
        tmp_path,
        [Path("app.py")],
        SuppressionReasonPolicy(extensions=(".py",), rule_codes=("E402",)),
    )

    assert native.returncode == 0, native.stdout + native.stderr
    assert len(findings) == 1
    assert findings[0].path == "ruff.toml"
    assert "E402" in findings[0].message


def test_legacy_tch_noqa_redirect_policy_matching() -> None:
    policy = SuppressionReasonPolicy(extensions=(".py",), rule_codes=("TC001",))
    missing_reason = suppression_reason_findings(
        "from myapp import Model  # noqa: TCH001\n", policy
    )
    documented = suppression_reason_findings(
        "from myapp import Model  # noqa: TCH001 -- typing-only import\n", policy
    )
    unrelated_code = suppression_reason_findings(
        "from myapp import Model  # noqa: TCH001\n",
        SuppressionReasonPolicy(extensions=(".py",), rule_codes=("TC002",)),
    )

    assert len(missing_reason) == 1
    assert "TC001" in missing_reason[0].message
    assert documented == []
    assert unrelated_code == []


@pytest.mark.parametrize("with_reason", [False, True])
def test_legacy_tch_per_file_ignore_redirect_matches_native_ruff(
    tmp_path: Path, with_reason: bool
) -> None:
    ruff = shutil.which("ruff")
    if ruff is None:
        pytest.skip("Ruff executable is not installed in this test environment")
    (tmp_path / "myapp.py").write_text("class Model: ...\n", encoding="utf-8")
    (tmp_path / "app.py").write_text(
        "from __future__ import annotations\n"
        "from myapp import Model\n\n"
        "def use(value: Model) -> None:\n"
        "    pass\n",
        encoding="utf-8",
    )
    rationale = " # -- typing-only import" if with_reason else ""
    (tmp_path / "ruff.toml").write_text(
        '[lint]\nselect = ["TC001"]\n'
        '[lint.isort]\nknown-first-party = ["myapp"]\n'
        '[lint.per-file-ignores]\n"app.py" = ["TCH001"]'
        f"{rationale}\n",
        encoding="utf-8",
    )
    native = subprocess.run(
        [ruff, "check", "--config", "ruff.toml", "app.py"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    findings = check_suppression_reasons(
        tmp_path,
        [Path("app.py")],
        SuppressionReasonPolicy(extensions=(".py",), rule_codes=("TC001",)),
    )

    assert native.returncode == 0, native.stdout + native.stderr
    if with_reason:
        assert findings == []
    else:
        assert len(findings) == 1
        assert findings[0].path == "ruff.toml"
        assert "TC001" in findings[0].message


@pytest.mark.parametrize(
    ("pattern", "path", "suppressed"),
    [
        ("{src,tests}/**", "src/app.py", True),
        ("{src,tests}/**", "tests/app.py", True),
        ("{src,tests}/**", "docs/app.py", False),
        ("{src,{tests,docs}}/**", "docs/app.py", True),
    ],
)
def test_per_file_brace_alternation_matches_native_ruff(
    tmp_path: Path, pattern: str, path: str, suppressed: bool
) -> None:
    ruff = shutil.which("ruff")
    if ruff is None:
        pytest.skip("Ruff executable is not installed in this test environment")
    source = tmp_path / path
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("value = 1\nimport os\n", encoding="utf-8")
    (tmp_path / "ruff.toml").write_text(
        f'[lint.per-file-ignores]\n"{pattern}" = ["E402"]\n', encoding="utf-8"
    )
    native = subprocess.run(
        [ruff, "check", "--select", "E402", "--config", "ruff.toml", path],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    findings = check_suppression_reasons(
        tmp_path,
        [Path(path)],
        SuppressionReasonPolicy(extensions=(".py",), rule_codes=("E402",)),
    )

    assert (native.returncode == 0) is suppressed, native.stdout + native.stderr
    assert bool(findings) is suppressed


def test_multiline_inline_map_comments_are_attributed_to_their_entry(
    tmp_path: Path,
) -> None:
    ruff = shutil.which("ruff")
    if ruff is None:
        pytest.skip("Ruff executable is not installed in this test environment")
    for name in ("app.py", "other.py"):
        (tmp_path / name).write_text("value = 1\nimport os\n", encoding="utf-8")
    (tmp_path / "ruff.toml").write_text(
        "[lint]\nper-file-ignores = {\n"
        ' "app.py" = ["E402"],\n'
        ' "other.py" = ["E402"] # -- rationale for other.py only\n'
        "}\n",
        encoding="utf-8",
    )
    native = subprocess.run(
        [
            ruff,
            "check",
            "--select",
            "E402",
            "--config",
            "ruff.toml",
            "app.py",
            "other.py",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    findings = check_suppression_reasons(
        tmp_path,
        [Path("app.py"), Path("other.py")],
        SuppressionReasonPolicy(extensions=(".py",), rule_codes=("E402",)),
    )

    assert native.returncode == 0, native.stdout + native.stderr
    assert len(findings) == 1
    assert findings[0].path == "ruff.toml"
    assert "app.py" in findings[0].message
    assert "other.py" not in findings[0].message


def test_multiline_inline_map_trailing_comment_is_not_attributed_to_entries(
    tmp_path: Path,
) -> None:
    ruff = shutil.which("ruff")
    if ruff is None:
        pytest.skip("Ruff executable is not installed in this test environment")
    for name in ("app.py", "other.py"):
        (tmp_path / name).write_text("value = 1\nimport os\n", encoding="utf-8")
    (tmp_path / "ruff.toml").write_text(
        "[lint]\nper-file-ignores = {\n"
        ' "app.py" = ["E402"],\n'
        ' "other.py" = ["E402"]\n'
        "} # -- broad rationale not attached to either entry\n",
        encoding="utf-8",
    )
    native = subprocess.run(
        [
            ruff,
            "check",
            "--select",
            "E402",
            "--config",
            "ruff.toml",
            "app.py",
            "other.py",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    findings = check_suppression_reasons(
        tmp_path,
        [Path("app.py"), Path("other.py")],
        SuppressionReasonPolicy(extensions=(".py",), rule_codes=("E402",)),
    )

    assert native.returncode == 0, native.stdout + native.stderr
    assert len(findings) == 2
    assert all("no rationale" in finding.message for finding in findings)


def test_non_string_per_file_codes_are_reported_as_not_evaluated(
    tmp_path: Path,
) -> None:
    (tmp_path / "app.py").write_text("value = 1\n", encoding="utf-8")
    (tmp_path / "ruff.toml").write_text(
        '[lint.per-file-ignores]\n"app.py" = ["E402", 7]\n',
        encoding="utf-8",
    )

    findings = check_suppression_reasons(
        tmp_path,
        [Path("app.py")],
        SuppressionReasonPolicy(extensions=(".py",), rule_codes=("E402",)),
    )

    assert len(findings) == 1
    assert "not evaluated" in findings[0].message
    assert "unsupported" in findings[0].message


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


def test_config_exception_with_documented_matching_entry_is_not_stale(
    tmp_path: Path,
) -> None:
    (tmp_path / "app.py").write_text("value = 1\n", encoding="utf-8")
    config = tmp_path / "ruff.toml"
    config.write_text(
        '[lint.per-file-ignores]\n"app.py" = ["E402"] # -- plugin bootstrap\n',
        encoding="utf-8",
    )
    exception = SuppressionReasonException(
        path="ruff.toml",
        rule_code="E402",
        line=2,
        reason="Reviewed bootstrap exception.",
    )
    policy = SuppressionReasonPolicy(
        extensions=(".py",), rule_codes=("E402",), exceptions=(exception,)
    )

    assert check_suppression_reasons(tmp_path, [Path("app.py")], policy) == []

    config.write_text(
        '[lint.per-file-ignores]\n"app.py" = ["F401"] # -- unrelated rule\n',
        encoding="utf-8",
    )
    stale = check_suppression_reasons(tmp_path, [Path("app.py")], policy)

    assert len(stale) == 1
    assert stale[0].line == 2
    assert "stale exception" in stale[0].message


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
