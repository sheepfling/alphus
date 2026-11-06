"""Runtime invariants for generated built-in feature metadata."""

from dataclasses import FrozenInstanceError

import pytest

from alphus.policy._generated_feature_definitions import FEATURE_DEFINITIONS
from alphus.policy._generated_morphology import MORPHOLOGY_BY_SELECTOR
from alphus.policy.catalog import RULE_SPECS, RuleOutputShape
from alphus.policy.feature_definition import FeatureDefinition


def test_generated_feature_definitions_are_immutable() -> None:
    definition = FEATURE_DEFINITIONS["file-size"]

    with pytest.raises(FrozenInstanceError):
        definition.selector = "changed"  # type: ignore[misc]

    with pytest.raises(TypeError, match="immutable tuple"):
        FeatureDefinition(
            selector=definition.selector,
            policy_field=definition.policy_field,
            policy_model=definition.policy_model,
            output_shape=definition.output_shape,
            summary=definition.summary,
            applies_to=["configurable-source"],  # type: ignore[arg-type]
            domains=definition.domains,
            requires_files=definition.requires_files,
            runner_module=definition.runner_module,
            runner_name=definition.runner_name,
        )

    default_inputs = FeatureDefinition(
        selector=definition.selector,
        policy_field=definition.policy_field,
        policy_model=definition.policy_model,
        output_shape=definition.output_shape,
        summary=definition.summary,
        applies_to=definition.applies_to,
        domains=definition.domains,
        requires_files=definition.requires_files,
        runner_module=definition.runner_module,
        runner_name=definition.runner_name,
    )
    assert default_inputs.policy_inputs == (definition.policy_field,)

    with pytest.raises(TypeError, match="immutable tuple"):
        FeatureDefinition(
            selector=definition.selector,
            policy_field=definition.policy_field,
            policy_model=definition.policy_model,
            output_shape=definition.output_shape,
            summary=definition.summary,
            applies_to=definition.applies_to,
            domains=definition.domains,
            requires_files=definition.requires_files,
            runner_module=definition.runner_module,
            runner_name=definition.runner_name,
            policy_inputs=[definition.policy_field],  # type: ignore[arg-type]
        )


def test_polyglot_cyclomatic_gate_uses_feature_owned_registration() -> None:
    definition = FEATURE_DEFINITIONS["cyclomatic-complexity"]
    spec = RULE_SPECS["cyclomatic-complexity"]

    assert definition.policy_field == "cyclomatic_complexity"
    assert definition.policy_model == "alphus.policy.metrics.CyclomaticComplexityPolicy"
    assert definition.output_shape == "cyclomatic-report"
    assert definition.applies_to == ("python", "javascript", "cpp")
    assert definition.runner_module == "alphus.gates.source.cyclomatic_complexity"
    assert definition.runner_name == "run_cyclomatic_rule"
    assert spec.policy_field == definition.policy_field
    assert spec.output_shape is RuleOutputShape.CYCLOMATIC_REPORT
    assert spec.requires_files is False


def test_output_escaping_registration_owns_both_language_tags() -> None:
    definition = FEATURE_DEFINITIONS["output-escaping"]
    spec = RULE_SPECS["output-escaping"]
    morphology = MORPHOLOGY_BY_SELECTOR["output-escaping"]

    assert definition.policy_field == "output_escaping"
    assert definition.policy_model == "alphus.policy.sources.SourceScanPolicy"
    assert definition.runner_name == "run_output_escaping_rule"
    assert definition.applies_to == ("python", "javascript")
    assert spec.policy_field == definition.policy_field
    assert spec.output_shape is RuleOutputShape.FINDINGS
    assert tuple(tag.rule_id for tag in morphology.finding_ids) == (
        "alphus/python/none/security/manual-output-escaping",
        "alphus/javascript/none/security/manual-output-escaping",
    )


def test_feature_definition_rejects_malformed_labels() -> None:
    definition = FEATURE_DEFINITIONS["file-size"]

    with pytest.raises(ValueError, match="valid applicability labels"):
        FeatureDefinition(
            selector=definition.selector,
            policy_field=definition.policy_field,
            policy_model=definition.policy_model,
            output_shape=definition.output_shape,
            summary=definition.summary,
            applies_to=("configurable-source", "configurable-source"),
            domains=definition.domains,
            requires_files=definition.requires_files,
            runner_module=definition.runner_module,
            runner_name=definition.runner_name,
        )


def test_feature_definition_rejects_malformed_policy_model() -> None:
    definition = FEATURE_DEFINITIONS["file-size"]

    with pytest.raises(ValueError, match="built-in policy class"):
        FeatureDefinition(
            selector=definition.selector,
            policy_field=definition.policy_field,
            policy_model="alphus.policy.not-a-class",
            output_shape=definition.output_shape,
            summary=definition.summary,
            applies_to=definition.applies_to,
            domains=definition.domains,
            requires_files=definition.requires_files,
            runner_module=definition.runner_module,
            runner_name=definition.runner_name,
        )
