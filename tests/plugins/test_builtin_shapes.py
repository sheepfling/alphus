"""Check that first-party registrations use output-specific feature forms."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from alphus.config import QualityGateConfig
from alphus.contracts.findings import Finding
from alphus.execution.dispatch import BUILTIN_RULES, EntryPointBuiltinRuleBinding
from alphus.gates.hygiene.file_size import (
    ALPHUS_FEATURE as FILE_SIZE_FEATURE,
)
from alphus.gates.hygiene.file_size import (
    run_file_size_feature,
)
from alphus.gates.repository.package_boundaries import (
    ALPHUS_FEATURE as PACKAGE_BOUNDARIES_FEATURE,
)
from alphus.gates.source.cli_policy import (
    ALPHUS_FEATURE as CLI_FEATURE,
)
from alphus.gates.source.cli_policy import (
    resolve_cli_policy,
)
from alphus.gates.source.cyclomatic_complexity import (
    ALPHUS_FEATURE as CYCLOMATIC_FEATURE,
)
from alphus.plugins.builtin import (
    BuiltinFeature,
    CompositeFindingBuiltinFeature,
    CyclomaticBuiltinFeature,
    FindingBuiltinFeature,
    MessageBuiltinFeature,
)
from alphus.plugins.builtin_registry import load_builtin_feature
from alphus.policy._generated_feature_definitions import FEATURE_DEFINITIONS
from alphus.policy._generated_morphology import MORPHOLOGY_BY_SELECTOR
from alphus.policy.architecture import PackageBoundaryPolicy
from alphus.policy.metrics import CyclomaticComplexityPolicy
from alphus.policy.sources import CliPolicy, FileSizePolicy


def test_every_current_builtin_uses_a_narrow_typed_registration() -> None:
    assert set(BUILTIN_RULES) == set(FEATURE_DEFINITIONS)
    assert all(
        isinstance(binding, EntryPointBuiltinRuleBinding)
        for binding in BUILTIN_RULES.values()
    )


def test_real_file_local_composite_message_and_native_shapes_are_typed() -> None:
    assert isinstance(FILE_SIZE_FEATURE, FindingBuiltinFeature)
    assert isinstance(PACKAGE_BOUNDARIES_FEATURE, CompositeFindingBuiltinFeature)
    assert isinstance(CLI_FEATURE, MessageBuiltinFeature)
    assert isinstance(CYCLOMATIC_FEATURE, CyclomaticBuiltinFeature)
    assert CYCLOMATIC_FEATURE.cyclomatic_operations is not None
    assert FILE_SIZE_FEATURE.runner is run_file_size_feature
    assert not isinstance(FILE_SIZE_FEATURE, BuiltinFeature)
    assert not isinstance(CLI_FEATURE, BuiltinFeature)
    assert not isinstance(CYCLOMATIC_FEATURE, BuiltinFeature)


def test_file_size_declaration_matches_its_generated_strict_policy() -> None:
    assert FILE_SIZE_FEATURE.definition.policy_field == "file_size"
    assert FILE_SIZE_FEATURE.definition.policy_model is FileSizePolicy
    config = QualityGateConfig.model_validate(
        {
            "schema_version": 1,
            "checks": {
                "file_size": {
                    "code_extensions": [".py"],
                    "code_limit": 100,
                    "hard_limit": 200,
                    "initializer_name": "__init__.py",
                    "initializer_limit": 200,
                }
            },
        },
        strict=True,
    )
    assert type(config.checks.file_size) is FILE_SIZE_FEATURE.definition.policy_model


def test_lazy_loader_preserves_each_migrated_feature_form() -> None:
    assert isinstance(load_builtin_feature("file-size"), FindingBuiltinFeature)
    assert isinstance(
        load_builtin_feature("package-boundaries"), CompositeFindingBuiltinFeature
    )
    assert isinstance(load_builtin_feature("cli"), MessageBuiltinFeature)
    assert isinstance(
        load_builtin_feature("cyclomatic-complexity"), CyclomaticBuiltinFeature
    )


def test_literal_selector_loader_narrows_feature_form() -> None:
    finding_feature: FindingBuiltinFeature[FileSizePolicy] = load_builtin_feature(
        "file-size"
    )
    message_feature: MessageBuiltinFeature[CliPolicy] = load_builtin_feature("cli")
    cyclomatic_feature: CyclomaticBuiltinFeature[CyclomaticComplexityPolicy] = (
        load_builtin_feature("cyclomatic-complexity")
    )
    composite_feature: CompositeFindingBuiltinFeature[PackageBoundaryPolicy] = (
        load_builtin_feature("package-boundaries")
    )

    assert finding_feature.definition.output_shape == "findings"
    assert message_feature.definition.output_shape == "messages"
    assert cyclomatic_feature.definition.output_shape == "cyclomatic-report"
    assert composite_feature.definition.output_shape == "findings"


def test_typed_finding_form_rejects_message_definition() -> None:
    def finding_runner(
        _root: Path,
        _files: Sequence[Path],
        _policy: CliPolicy,
    ) -> list[Finding]:
        return []

    with pytest.raises(ValueError, match="requires output shape 'findings'"):
        FindingBuiltinFeature(
            definition=FEATURE_DEFINITIONS["cli"],
            morphology=MORPHOLOGY_BY_SELECTOR["cli"],
            runner=finding_runner,
            policy_resolver=resolve_cli_policy,
        )
