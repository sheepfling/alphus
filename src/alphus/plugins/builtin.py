"""Typed first-party check registrations discovered from the Alphus wheel."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from alphus.config import QualityGateConfig
from alphus.contracts.cyclomatic import CyclomaticRuleOperations
from alphus.execution.results import RuleOutput
from alphus.policy.feature_definition import FeatureDefinition
from alphus.policy.morphology import RuleMorphology


class BuiltinRunner(Protocol):
    """Synchronous provider contract shared by registered built-ins."""

    def __call__(
        self, root: Path, files: Sequence[Path], config: QualityGateConfig, /
    ) -> RuleOutput: ...


@dataclass(frozen=True, slots=True)
class BuiltinFeature:
    """One feature's metadata, morphology, and typed execution provider."""

    definition: FeatureDefinition
    morphology: RuleMorphology
    runner: BuiltinRunner
    cyclomatic_operations: CyclomaticRuleOperations | None = None

    def __post_init__(self) -> None:
        if self.definition.selector != self.morphology.selector:
            raise ValueError(
                "built-in feature metadata and morphology selectors differ"
            )
        if not callable(self.runner):
            raise TypeError("built-in feature runner must be callable")
        is_cyclomatic = self.definition.output_shape == "cyclomatic-report"
        if is_cyclomatic != (self.cyclomatic_operations is not None):
            raise ValueError(
                "cyclomatic features require exactly one typed operations contract"
            )


__all__ = ["BuiltinFeature"]
