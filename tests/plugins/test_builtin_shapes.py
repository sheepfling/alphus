"""Check that first-party registrations use output-specific feature forms."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from alphus.config import QualityGateConfig
from alphus.contracts.findings import Finding
from alphus.gates.hygiene.file_size import ALPHUS_FEATURE as FILE_SIZE_FEATURE
from alphus.gates.repository.package_boundaries import (
    ALPHUS_FEATURE as PACKAGE_BOUNDARIES_FEATURE,
)
from alphus.gates.source.cli_policy import ALPHUS_FEATURE as CLI_FEATURE
from alphus.gates.source.cyclomatic_complexity import (
    ALPHUS_FEATURE as CYCLOMATIC_FEATURE,
)
from alphus.plugins.builtin import (
    CyclomaticBuiltinFeature,
    FindingBuiltinFeature,
    MessageBuiltinFeature,
)
from alphus.policy._generated_feature_definitions import FEATURE_DEFINITIONS
from alphus.policy._generated_morphology import MORPHOLOGY_BY_SELECTOR


def test_real_file_local_composite_message_and_native_shapes_are_typed() -> None:
    assert isinstance(FILE_SIZE_FEATURE, FindingBuiltinFeature)
    assert isinstance(PACKAGE_BOUNDARIES_FEATURE, FindingBuiltinFeature)
    assert isinstance(CLI_FEATURE, MessageBuiltinFeature)
    assert isinstance(CYCLOMATIC_FEATURE, CyclomaticBuiltinFeature)
    assert CYCLOMATIC_FEATURE.cyclomatic_operations is not None


def test_typed_finding_form_rejects_message_definition() -> None:
    def finding_runner(
        _root: Path, _files: Sequence[Path], _config: QualityGateConfig
    ) -> list[Finding]:
        return []

    with pytest.raises(ValueError, match="requires output shape 'findings'"):
        FindingBuiltinFeature(
            definition=FEATURE_DEFINITIONS["cli"],
            morphology=MORPHOLOGY_BY_SELECTOR["cli"],
            runner=finding_runner,
        )
