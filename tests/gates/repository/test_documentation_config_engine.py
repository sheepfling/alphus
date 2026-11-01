"""Bounded advisory checks for named Python defaults repeated in Markdown."""

from pathlib import Path
from subprocess import run

from alphus.config import (
    DocumentationConfigPolicy,
    DocumentationConfigSuppression,
    QualityGateConfig,
)
from alphus.contracts.findings import Finding
from alphus.execution.dispatch import run_builtin_rule
from alphus.execution.results import RuleEvaluation
from alphus.gates.repository.documentation_config import check_documentation_config

_DUPLICATED = "alphus/repository/none/maintainability/documented-config-duplicate"
_CONFLICT = "alphus/repository/none/configuration/documented-config-conflict"
_UNKNOWN = "alphus/repository/none/configuration/documented-config-unknown"


def _policy(
    *,
    exclude: tuple[str, ...] = (),
    suppressions: tuple[DocumentationConfigSuppression, ...] = (),
) -> DocumentationConfigPolicy:
    return DocumentationConfigPolicy(
        source_patterns=("src/**/*.py",),
        documentation_patterns=("docs/**/*.md",),
        exclude=exclude,
        suppressions=suppressions,
    )


def _run_documentation_case(
    tmp_path: Path, source_text: str, documentation_text: str
) -> list[Finding]:
    source = tmp_path / "src" / "settings.py"
    guide = tmp_path / "docs" / "guide.md"
    source.parent.mkdir()
    guide.parent.mkdir()
    source.write_text(source_text, encoding="utf-8")
    guide.write_text(documentation_text, encoding="utf-8")
    files = [Path("src/settings.py"), Path("docs/guide.md")]
    return check_documentation_config(tmp_path, _policy(), files)


def test_unknown_qualified_class_does_not_match_other_classes_short_name(
    tmp_path: Path,
) -> None:
    findings = _run_documentation_case(
        tmp_path,
        "class IncludeLimits:\n    max_files: int = 4\n",
        "IncludeLimits.max_files is 4.\nOtherLimits.max_files is 99.\n",
    )

    assert [(item.rule_id, item.line) for item in findings] == [(_DUPLICATED, 1)]


def test_backticked_numeric_value_preserves_explicit_unit(tmp_path: Path) -> None:
    findings = _run_documentation_case(
        tmp_path, "MAX_BYTES = 1048576\n", "MAX_BYTES is `1` MiB.\n"
    )

    assert [(item.rule_id, item.line) for item in findings] == [(_DUPLICATED, 1)]
    assert "normalized explicit byte unit MiB" in findings[0].message


def test_scientific_numeric_notation_is_reported_as_uncertain(tmp_path: Path) -> None:
    findings = _run_documentation_case(
        tmp_path, "MAX_BYTES = 1000\n", "MAX_BYTES is 1.0e3.\n"
    )

    assert [(item.rule_id, item.line) for item in findings] == [(_UNKNOWN, 1)]
    assert "documentation value '1.0e3'" in findings[0].message
    assert "unsupported or uncertain numeric syntax" in findings[0].message


def test_conditional_import_invalidates_earlier_literal_binding(tmp_path: Path) -> None:
    findings = _run_documentation_case(
        tmp_path,
        "MAX_FILES = 64\nif condition:\n    from settings import MAX_FILES\n",
        "MAX_FILES is 64.\n",
    )

    assert [(item.rule_id, item.line) for item in findings] == [(_UNKNOWN, 1)]
    assert "dynamic or outside the literal/alias subset" in findings[0].message


def test_backticked_setting_name_matches_explicit_relation(tmp_path: Path) -> None:
    findings = _run_documentation_case(
        tmp_path, "MAX_RETRIES = 8\n", "`MAX_RETRIES` is 8.\n"
    )

    assert [(item.rule_id, item.line) for item in findings] == [(_DUPLICATED, 1)]


def test_matches_explicit_defaults_and_ignores_non_claims_and_unsupported_values(
    tmp_path: Path,
) -> None:
    fixture = Path("tests/fixtures/documentation_config")
    source = tmp_path / "src" / "limits.py"
    source.parent.mkdir()
    source.write_text(
        (fixture / "include_limits.py.txt").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    guide = tmp_path / "docs" / "limits.md"
    guide.parent.mkdir()
    guide.write_text(
        (fixture / "limits.md").read_text(encoding="utf-8"), encoding="utf-8"
    )
    archived = tmp_path / "docs" / "archive.md"
    archived.write_text("max_include_files is 2.\n", encoding="utf-8")

    findings = check_documentation_config(
        tmp_path,
        _policy(exclude=("docs/archive.md",)),
        [Path("src/limits.py"), Path("docs/limits.md"), Path("docs/archive.md")],
    )

    assert [(item.rule_id, item.line) for item in findings] == [
        (_DUPLICATED, 1),
        (_CONFLICT, 2),
        (_DUPLICATED, 3),
        (_CONFLICT, 4),
        (_UNKNOWN, 5),
        (_DUPLICATED, 6),
        (_UNKNOWN, 7),
        (_UNKNOWN, 8),
        (_UNKNOWN, 9),
    ]
    assert all(item.path == "docs/limits.md" for item in findings)
    assert "code value 64 at src/limits.py:7" in findings[1].message
    assert "documentation value '12'" in findings[1].message
    assert "normalized explicit byte unit MiB" in findings[2].message
    assert "normalized explicit byte unit MB" in findings[3].message
    assert "code value 1048576" in findings[3].message
    assert "documentation value '1 MB'" in findings[3].message
    assert "unsupported for comparison" in findings[4].message
    assert "normalized explicit byte unit MiB" in findings[5].message
    assert "dynamic or outside the literal/alias subset" in findings[6].message
    assert "dynamic or outside the literal/alias subset" in findings[7].message
    assert "different types" in findings[8].message
    assert "2048" not in " ".join(item.message for item in findings)


def test_alias_shadowing_and_repeated_symbols_are_handled_conservatively(
    tmp_path: Path,
) -> None:
    first = tmp_path / "src" / "one.py"
    second = tmp_path / "src" / "two.py"
    first.parent.mkdir()
    first.write_text(
        "DEFAULT_LIMIT = 64\n"
        "ALIAS_LIMIT = DEFAULT_LIMIT\n"
        "DEFAULT_LIMIT = 9\n"
        "MAX_RETRIES = 2\n"
        "STALE_LIMIT = 64\n"
        "STALE_LIMIT, other = get_limits()\n"
        "ALIAS_STALE_LIMIT = STALE_LIMIT\n"
        "class IncludeLimits:\n"
        "    DEFAULT_LIMIT = 4\n"
        "    local_limit: int = DEFAULT_LIMIT\n",
        encoding="utf-8",
    )
    second.write_text("MAX_RETRIES = 4\n", encoding="utf-8")
    guide = tmp_path / "docs" / "limits.md"
    guide.parent.mkdir()
    guide.write_text(
        "ALIAS_LIMIT is 64.\nIncludeLimits.local_limit is 4.\n"
        "MAX_RETRIES is 3.\nALIAS_STALE_LIMIT is 64.\n",
        encoding="utf-8",
    )

    findings = check_documentation_config(
        tmp_path,
        _policy(),
        [Path("src/one.py"), Path("src/two.py"), Path("docs/limits.md")],
    )

    assert [(item.rule_id, item.line) for item in findings] == [
        (_DUPLICATED, 1),
        (_DUPLICATED, 2),
        (_UNKNOWN, 3),
        (_UNKNOWN, 4),
    ]
    assert "repeated symbol has multiple code candidates" in findings[2].message
    assert "src/one.py:4" in findings[2].message
    assert "src/two.py:1" in findings[2].message
    assert "dynamic or outside the literal/alias subset" in findings[3].message


def test_dynamic_module_is_never_imported_and_suppression_is_path_scoped(
    tmp_path: Path,
) -> None:
    source = tmp_path / "src" / "unsafe.py"
    source.parent.mkdir()
    source.write_text(
        "from pathlib import Path\n"
        "Path('executed.marker').touch()\n"
        "MAX_DYNAMIC = make_default()\n",
        encoding="utf-8",
    )
    guide = tmp_path / "docs" / "limits.md"
    guide.parent.mkdir()
    guide.write_text("MAX_DYNAMIC is 12.\n", encoding="utf-8")

    files = [Path("src/unsafe.py"), Path("docs/limits.md")]
    findings = check_documentation_config(tmp_path, _policy(), files)
    assert [item.rule_id for item in findings] == [_UNKNOWN]
    assert not (tmp_path / "executed.marker").exists()

    suppressed = _policy(
        suppressions=(
            DocumentationConfigSuppression(
                path="docs/limits.md",
                symbol="MAX_DYNAMIC",
                reason="This page intentionally describes the deployment override.",
            ),
        )
    )
    assert check_documentation_config(tmp_path, suppressed, files) == []


def test_repeated_class_fields_require_qualified_context_or_report_unknown(
    tmp_path: Path,
) -> None:
    source = tmp_path / "src" / "limits.py"
    source.parent.mkdir()
    source.write_text(
        "class IncludeLimits:\n    max_files: int = 4\n"
        "class ExportLimits:\n    max_files: int = 8\n",
        encoding="utf-8",
    )
    guide = tmp_path / "docs" / "limits.md"
    guide.parent.mkdir()
    guide.write_text(
        "IncludeLimits.max_files is 4.\n"
        "ExportLimits.max_files is 8.\n"
        "max_files is 6.\n",
        encoding="utf-8",
    )

    findings = check_documentation_config(
        tmp_path,
        _policy(),
        [Path("src/limits.py"), Path("docs/limits.md")],
    )

    assert [(item.rule_id, item.line) for item in findings] == [
        (_DUPLICATED, 1),
        (_DUPLICATED, 2),
        (_UNKNOWN, 3),
    ]
    assert "multiple code candidates" in findings[2].message


def test_separately_qualified_claims_keep_their_own_comparison_groups(
    tmp_path: Path,
) -> None:
    findings = _run_documentation_case(
        tmp_path,
        "class IncludeLimits:\n    max_files: int = 4\n"
        "class ExportLimits:\n    max_files: int = 8\n",
        "IncludeLimits.max_files is 4; ExportLimits.max_files is 99.\n",
    )

    assert {item.rule_id for item in findings} == {_DUPLICATED, _CONFLICT}
    assert any(
        item.rule_id == _DUPLICATED and "for IncludeLimits.max_files" in item.message
        for item in findings
    )
    assert any(
        item.rule_id == _CONFLICT and "for ExportLimits.max_files" in item.message
        for item in findings
    )


def test_qualified_suppression_does_not_hide_another_field_with_same_short_name(
    tmp_path: Path,
) -> None:
    source = tmp_path / "src" / "settings.py"
    guide = tmp_path / "docs" / "guide.md"
    source.parent.mkdir()
    guide.parent.mkdir()
    source.write_text(
        "class IncludeLimits:\n    max_files: int = 4\n"
        "class ExportLimits:\n    max_files: int = 8\n",
        encoding="utf-8",
    )
    guide.write_text(
        "IncludeLimits.max_files is 4; ExportLimits.max_files is 99.\n",
        encoding="utf-8",
    )
    policy = _policy(
        suppressions=(
            DocumentationConfigSuppression(
                path="docs/guide.md",
                symbol="IncludeLimits.max_files",
                reason="This field is intentionally repeated in this guide.",
            ),
        )
    )

    findings = check_documentation_config(
        tmp_path,
        policy,
        [Path("src/settings.py"), Path("docs/guide.md")],
    )

    assert [item.rule_id for item in findings] == [_CONFLICT]
    assert "for ExportLimits.max_files" in findings[0].message


def test_rule_runs_from_validated_policy_and_warning_is_nonblocking(
    tmp_path: Path,
) -> None:
    source = tmp_path / "src" / "limits.py"
    guide = tmp_path / "docs" / "limits.md"
    source.parent.mkdir()
    guide.parent.mkdir()
    source.write_text("MAX_FILES = 64\n", encoding="utf-8")
    guide.write_text("MAX_FILES is 64.\n", encoding="utf-8")
    run(["git", "init", "--quiet", str(tmp_path)], check=True)
    run(
        ["git", "-C", str(tmp_path), "add", "src/limits.py", "docs/limits.md"],
        check=True,
    )
    config = QualityGateConfig.model_validate(
        {
            "schema_version": 1,
            "checks": {
                "documentation_config": {
                    "source_patterns": ["src/**/*.py"],
                    "documentation_patterns": ["docs/**/*.md"],
                }
            },
        }
    )

    output = run_builtin_rule("documentation-config", tmp_path, [], config)
    evaluation = RuleEvaluation.from_output("documentation-config", output, "error")

    assert isinstance(output, list)
    assert len(output) == 1
    finding = output[0]
    assert isinstance(finding, Finding)
    assert finding.rule_id == _DUPLICATED
    assert finding.severity == "warning"
    assert not evaluation.failed


def test_unsupported_numeric_forms_do_not_compare_as_values(tmp_path: Path) -> None:
    findings = _run_documentation_case(
        tmp_path,
        "DEFAULT_RATE = '1e3'\n"
        "MAX_FILES = 1024\n"
        "MAX_RATIO = 0.5\n"
        "MIN_FILES = 1\n"
        "MAX_PLUS = 1\n",
        "DEFAULT_RATE is 1e4.\n"
        "DEFAULT_RATE is 1e3.\n"
        "DEFAULT_RATE is '1e3'.\n"
        "DEFAULT_RATE is '1e4'.\n"
        "MAX_FILES is 1,024.\n"
        "MAX_RATIO is 1/2.\n"
        "MIN_FILES is 1-2.\n"
        "MIN_FILES is 1 - 2.\n"
        "MAX_PLUS is 1+2.\n"
        "MIN_FILES is 1.\n"
        "MIN_FILES is 1, with additional context.\n",
    )

    assert [(item.rule_id, item.line) for item in findings] == [
        (_UNKNOWN, 1),
        (_UNKNOWN, 2),
        (_DUPLICATED, 3),
        (_CONFLICT, 4),
        (_UNKNOWN, 5),
        (_UNKNOWN, 6),
        (_UNKNOWN, 7),
        (_UNKNOWN, 8),
        (_UNKNOWN, 9),
        (_DUPLICATED, 10),
        (_DUPLICATED, 11),
    ]
    assert [
        (item.line, item.severity) for item in findings if item.rule_id == _UNKNOWN
    ] == [(line, "info") for line in (1, 2, 5, 6, 7, 8, 9)]
    assert "documentation value '1,024'" in findings[4].message
    assert "documentation value '1/2'" in findings[5].message
    assert "documentation value '1-2'" in findings[6].message
    assert "documentation value '1 - 2'" in findings[7].message
    assert "documentation value '1+2'" in findings[8].message


def test_word_and_unicode_dash_ranges_remain_uncertain_numeric_claims(
    tmp_path: Path,
) -> None:
    findings = _run_documentation_case(
        tmp_path,
        "MIN_FILES = 1\n",
        "MIN_FILES is 1–2.\nMIN_FILES is 1 to 2.\n",
    )

    assert [item.rule_id for item in findings] == [_UNKNOWN, _UNKNOWN]
    assert [item.severity for item in findings] == ["info", "info"]
    assert "documentation value '1–2'" in findings[0].message
    assert "documentation value '1 to 2'" in findings[1].message


def test_final_punctuation_and_comma_followed_by_prose_stay_numeric(
    tmp_path: Path,
) -> None:
    findings = _run_documentation_case(
        tmp_path,
        "MAX_FILES = 1\n",
        "MAX_FILES is 1.\nMAX_FILES is 1, with additional context.\n",
    )

    assert [(item.rule_id, item.line) for item in findings] == [
        (_DUPLICATED, 1),
        (_DUPLICATED, 2),
    ]


def test_class_scope_conditional_import_invalidates_fields_and_aliases(
    tmp_path: Path,
) -> None:
    findings = _run_documentation_case(
        tmp_path,
        "class IncludeLimits:\n"
        "    max_files = 4\n"
        "    if condition:\n"
        "        from settings import max_files\n"
        "    field_alias = max_files\n",
        "IncludeLimits.max_files is 8.\nIncludeLimits.field_alias is 4.\n",
    )

    assert [(item.rule_id, item.line) for item in findings] == [
        (_UNKNOWN, 1),
        (_UNKNOWN, 2),
    ]
    assert all(item.severity == "info" for item in findings)


def test_nested_function_imports_do_not_invalidate_outer_defaults(
    tmp_path: Path,
) -> None:
    findings = _run_documentation_case(
        tmp_path,
        "MAX_MODULE_FILES = 8\n"
        "def module_helper():\n"
        "    from settings import MAX_MODULE_FILES\n"
        "class ControlLimits:\n"
        "    max_files = 4\n"
        "    def helper():\n"
        "        from settings import max_files\n",
        "MAX_MODULE_FILES is 8.\nControlLimits.max_files is 4.\n",
    )

    assert [(item.rule_id, item.line) for item in findings] == [
        (_DUPLICATED, 1),
        (_DUPLICATED, 2),
    ]
