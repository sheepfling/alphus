"""Runtime invariants for generated built-in feature metadata."""

from dataclasses import FrozenInstanceError

import pytest

from alphus.policy._generated_feature_definitions import FEATURE_DEFINITIONS
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
