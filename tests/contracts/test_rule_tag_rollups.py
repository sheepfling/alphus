"""Semantic complaint totals are comparable across language scopes."""

from alphus.contracts.findings import Diagnostic, FindingRollups
from alphus.contracts.rule_tags import NAMESPACE, RuleTag, rule_tag


def test_finding_rollups_group_same_complaint_across_languages() -> None:
    findings = (
        Diagnostic(
            source="alphus",
            rule_id="alphus/python/none/style/line-too-long",
            message="Python line",
        ),
        Diagnostic(
            source="alphus",
            rule_id="alphus/javascript/none/style/line-too-long",
            message="JavaScript line",
            severity="warning",
        ),
    )
    rollups = FindingRollups.from_diagnostics(findings)
    assert [(row.key, row.count) for row in rollups.scopes] == [
        ("javascript", 1),
        ("python", 1),
    ]
    assert [(row.key, row.count) for row in rollups.categories] == [("style", 2)]
    assert [(row.key, row.count) for row in rollups.complaints] == [
        ("style/line-too-long", 2)
    ]
    assert rollups.complaints[0].severity_counts.error == 1
    assert rollups.complaints[0].severity_counts.warning == 1


def test_semantic_tags_cover_c_and_sqlalchemy() -> None:
    tag = RuleTag.parse(rule_tag("c", "none", "correctness", "unsafe-call"))
    assert tag.scope == "c"
    assert tag.framework == "none"
    assert tag.category == "correctness"
    assert tag.complaint == "unsafe-call"
    assert (
        RuleTag.parse(
            rule_tag("python", "sqlalchemy", "correctness", "unsafe-query")
        ).framework
        == "sqlalchemy"
    )
    assert RuleTag.is_alphus_id(f"{NAMESPACE}/python/none/style/line-too-long")
    assert not RuleTag.is_alphus_id("eslint/no-undef")


def test_rollups_ignore_native_diagnostic_ids() -> None:
    rollups = FindingRollups.from_diagnostics(
        (Diagnostic(source="eslint", rule_id="eslint/no-undef", message="undefined"),)
    )
    assert rollups.scopes == ()
    assert rollups.categories == ()
    assert rollups.complaints == ()
