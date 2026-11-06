"""Keep rule morphology distinct from selection and enforcement policy."""

from __future__ import annotations

from dataclasses import fields, replace

import pytest

from alphus.contracts.rule_tags import RuleTag
from alphus.policy._generated_feature_definitions import FEATURE_DEFINITIONS
from alphus.policy._generated_morphology import MORPHOLOGY_BY_SELECTOR
from alphus.policy.catalog import _LEGACY_RULE_SPECS, RULE_SPECS
from alphus.policy.morphology import (
    ClaimKind,
    DetectionMechanism,
    EvaluationMaturity,
    RuleMorphology,
)


def test_feature_morphology_is_attached_without_changing_rule_contracts() -> None:
    attached_selectors = {
        name for name, spec in RULE_SPECS.items() if spec.morphology is not None
    }
    assert attached_selectors == set(MORPHOLOGY_BY_SELECTOR)
    assert set(RULE_SPECS) == set(_LEGACY_RULE_SPECS) | set(FEATURE_DEFINITIONS)
    for selector, old_spec in _LEGACY_RULE_SPECS.items():
        current = RULE_SPECS[selector]
        assert current.policy_field == old_spec.policy_field
        assert current.output_shape is old_spec.output_shape
        assert current.summary == old_spec.summary
        assert current.applies_to == old_spec.applies_to
        assert current.domains == old_spec.domains
        assert current.requires_files == old_spec.requires_files
        assert current.morphology is MORPHOLOGY_BY_SELECTOR.get(selector)


def test_pilot_covers_exact_heuristic_prose_style_and_native_tool_mechanisms() -> None:
    mechanisms = {
        mechanism
        for morphology in MORPHOLOGY_BY_SELECTOR.values()
        for mechanism in morphology.mechanisms
    }
    assert mechanisms == {
        DetectionMechanism.EXACT_RULE,
        DetectionMechanism.BOUNDED_HEURISTIC,
        DetectionMechanism.NATIVE_TOOL,
    }
    assert MORPHOLOGY_BY_SELECTOR["benchmark-docs"].claim_kind is ClaimKind.RISK
    assert (
        MORPHOLOGY_BY_SELECTOR["document-style"].claim_kind
        is ClaimKind.STYLE_PREFERENCE
    )
    assert (
        MORPHOLOGY_BY_SELECTOR["positional-semantic-overrides"].evaluation_maturity
        is EvaluationMaturity.PUBLIC_SAMPLE_REVIEWED
    )
    assert MORPHOLOGY_BY_SELECTOR["source-test-coverage"].evidence_kinds == (
        "declared-relationship",
        "revision-matched-execution-status",
        "tracked-paths",
    )


def test_shared_numeric_complaint_contract_preserves_selector_specific_tags() -> None:
    numeric = MORPHOLOGY_BY_SELECTOR["numeric-literals"]
    scipy = MORPHOLOGY_BY_SELECTOR["scipy-constants"]

    assert numeric.concern == scipy.concern == "scientific-constant-reuse"
    assert numeric.finding_ids == (
        RuleTag.parse("alphus/python/none/style/inline-constant"),
        RuleTag.parse("alphus/python/none/style/inline-conversion"),
    )
    assert scipy.finding_ids == (
        RuleTag.parse("alphus/python/scipy/style/inline-constant"),
        RuleTag.parse("alphus/python/scipy/style/inline-conversion"),
    )


def test_morphology_does_not_absorb_policy_or_run_state() -> None:
    morphology_fields = {
        field.name for field in fields(next(iter(MORPHOLOGY_BY_SELECTOR.values())))
    }
    assert morphology_fields.isdisjoint(
        {
            "severity",
            "priority",
            "rollout",
            "confidence",
            "applicability",
            "selection",
            "coverage",
        }
    )


@pytest.mark.parametrize(
    "field_name",
    ("finding_ids", "inspected_scope", "languages_formats", "evidence_kinds"),
)
def test_morphology_rejects_mutable_sequence_inputs(field_name: str) -> None:
    morphology = next(iter(MORPHOLOGY_BY_SELECTOR.values()))
    values = getattr(morphology, field_name)

    with pytest.raises(TypeError, match="immutable tuple"):
        replace(morphology, **{field_name: list(values)})


def test_morphology_requires_rule_tags_and_slug_values() -> None:
    morphology: RuleMorphology = next(iter(MORPHOLOGY_BY_SELECTOR.values()))

    with pytest.raises(TypeError, match="RuleTag values"):
        replace(morphology, finding_ids=("alphus/any/none/style/not-a-tag",))
    with pytest.raises(ValueError, match="lowercase slugs"):
        replace(morphology, inspected_scope=("Selected-files",))
