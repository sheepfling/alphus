"""Semantic complaint totals are comparable across language scopes."""

from alphus.contracts.findings import Diagnostic, FindingRollups


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
