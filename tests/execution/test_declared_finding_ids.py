"""Feature output IDs must stay within the declared morphology contract."""

from __future__ import annotations

import json
from dataclasses import replace
from types import MappingProxyType

import pytest

from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import Category, Framework, RuleTag, Scope
from alphus.execution import results
from alphus.policy._generated_morphology import MORPHOLOGY_BY_SELECTOR
from alphus.policy.catalog import RuleOutputShape, RuleSpec


def _spec(selector: str, shared_tag: RuleTag) -> RuleSpec:
    morphology = replace(
        MORPHOLOGY_BY_SELECTOR["line-length"],
        selector=selector,
        finding_ids=(shared_tag,),
    )
    return RuleSpec(
        policy_field="line_length",
        output_shape=RuleOutputShape.FINDINGS,
        summary="Synthetic output identity contract.",
        applies_to=("python",),
        morphology=morphology,
    )


def _finding(rule_id: str) -> Finding:
    return Finding(
        rule_id=rule_id,
        path="src/example.py",
        line=3,
        message="fixture finding",
    )


def _install_shared_specs(monkeypatch: pytest.MonkeyPatch) -> RuleTag:
    shared_tag = RuleTag(
        Scope.REPOSITORY,
        Framework.NONE,
        Category.TESTING,
        "shared-output",
    )
    monkeypatch.setattr(
        results,
        "RULE_SPECS",
        MappingProxyType(
            {
                "first-check": _spec("first-check", shared_tag),
                "second-check": _spec("second-check", shared_tag),
            }
        ),
    )
    return shared_tag


def test_declared_shared_finding_id_is_valid_for_each_contract_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shared_tag = _install_shared_specs(monkeypatch)
    finding = _finding(shared_tag.rule_id)

    for selector in ("first-check", "second-check"):
        diagnostics = results.diagnostics_from_output(selector, [finding])
        assert [item.rule_id for item in diagnostics] == [shared_tag.rule_id]


def test_direct_output_rejects_finding_outside_declared_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shared_tag = _install_shared_specs(monkeypatch)
    undeclared = RuleTag(
        Scope.REPOSITORY,
        Framework.NONE,
        Category.TESTING,
        "undeclared-output",
    )

    with pytest.raises(ValueError, match="emitted undeclared finding ID"):
        results.diagnostics_from_output("first-check", [_finding(undeclared.rule_id)])

    assert shared_tag.rule_id != undeclared.rule_id


def test_json_output_rejects_finding_outside_declared_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shared_tag = _install_shared_specs(monkeypatch)
    undeclared = RuleTag(
        Scope.REPOSITORY,
        Framework.NONE,
        Category.TESTING,
        "undeclared-output",
    )
    encoded = json.dumps([_finding(undeclared.rule_id).to_wire()])

    with pytest.raises(ValueError, match="emitted undeclared finding ID"):
        results.diagnostics_from_json("second-check", encoded)

    assert shared_tag.rule_id != undeclared.rule_id
