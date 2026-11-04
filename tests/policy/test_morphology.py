"""Keep rule morphology distinct from selection and enforcement policy."""

from __future__ import annotations

from dataclasses import fields

from alphus.policy._generated_morphology import MORPHOLOGY_BY_SELECTOR
from alphus.policy.catalog import _LEGACY_RULE_SPECS, RULE_SPECS
from alphus.policy.morphology import DetectionMechanism, EvaluationMaturity

_EXPECTED_SELECTORS = {
    "file-size",
    "source-test-coverage",
    "positional-semantic-overrides",
    "benchmark-docs",
    "document-style",
    "cyclomatic-complexity",
}


def test_feature_morphology_is_attached_without_changing_rule_contracts() -> None:
    assert set(MORPHOLOGY_BY_SELECTOR) == _EXPECTED_SELECTORS
    assert {name for name, spec in RULE_SPECS.items() if spec.morphology} == (
        _EXPECTED_SELECTORS
    )
    assert set(RULE_SPECS) == set(_LEGACY_RULE_SPECS)
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
        DetectionMechanism.PROSE_RISK,
        DetectionMechanism.STYLE_PREFERENCE,
        DetectionMechanism.NATIVE_TOOL,
    }
    assert (
        MORPHOLOGY_BY_SELECTOR["positional-semantic-overrides"].evaluation_maturity
        is EvaluationMaturity.PUBLIC_SAMPLE_REVIEWED
    )
    assert MORPHOLOGY_BY_SELECTOR["source-test-coverage"].evidence_kinds == (
        "declared-relationship",
        "revision-matched-execution-status",
        "tracked-paths",
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
