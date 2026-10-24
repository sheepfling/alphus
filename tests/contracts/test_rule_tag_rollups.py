"""Semantic complaint totals are comparable across language scopes."""

import json

import pytest

from alphus.contracts.findings import Diagnostic, Finding, FindingRollups
from alphus.contracts.rule_tags import NAMESPACE, Category, RuleTag, rule_tag


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
    native = Diagnostic(source="eslint", rule_id="eslint/no-undef", message="undefined")
    assert not native.matches_category(Category.STYLE)
    rollups = FindingRollups.from_diagnostics((native,))
    assert rollups.scopes == ()
    assert rollups.categories == ()
    assert rollups.complaints == ()


def test_findings_keep_typed_identity_without_changing_public_shape() -> None:
    finding = Finding(
        "alphus/python/none/style/line-too-long",
        "src/example.py",
        "long line",
        4,
    )
    expected = Finding(
        "alphus/python/none/style/line-too-long",
        "src/example.py",
        "long line",
        4,
    )
    diagnostic = finding.as_diagnostic()

    assert finding.tag == RuleTag.parse(finding.rule_id)
    assert diagnostic.tag == finding.tag
    assert diagnostic.matches_category(Category.STYLE)
    assert not diagnostic.matches_category(Category.CORRECTNESS)
    assert finding == expected
    assert "_rule_tag" not in repr(finding)
    assert finding.to_wire() == {
        "rule_id": finding.rule_id,
        "path": "src/example.py",
        "message": "long line",
        "line": 4,
        "severity": "error",
    }
    assert diagnostic.to_wire() == {
        "source": "alphus",
        "rule_id": finding.rule_id,
        "message": "long line",
        "severity": "error",
        "path": "src/example.py",
        "line": 4,
        "priority": None,
    }
    restored = Diagnostic(**json.loads(json.dumps(diagnostic.to_wire())))
    assert restored == diagnostic
    assert restored.tag == diagnostic.tag


def test_rollups_use_cached_typed_tags_without_reparsing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    diagnostics = (
        Diagnostic(
            source="alphus",
            rule_id="alphus/python/none/style/line-too-long",
            message="long line",
        ),
        Diagnostic(
            source="alphus",
            rule_id="alphus/javascript/none/style/line-too-long",
            message="long line",
        ),
    )

    def fail_parse(*_args: object) -> RuleTag:
        raise AssertionError("rollups must use the cached semantic tag")

    monkeypatch.setattr(RuleTag, "parse", staticmethod(fail_parse))
    rollups = FindingRollups.from_diagnostics(diagnostics)

    assert [(row.key, row.count) for row in rollups.categories] == [("style", 2)]
    assert [(row.key, row.count) for row in rollups.complaints] == [
        ("style/line-too-long", 2)
    ]


@pytest.mark.parametrize(
    "rule_id",
    ["alphus/python/none/style", "alphus/python/unknown/style/line-too-long"],
)
def test_invalid_alphus_rule_ids_are_rejected_at_ingestion(rule_id: str) -> None:
    with pytest.raises(ValueError):
        Finding(rule_id, "src/example.py", "invalid")
    with pytest.raises(ValueError):
        Diagnostic(source="external", rule_id=rule_id, message="invalid")
