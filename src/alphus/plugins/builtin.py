"""Typed first-party check registrations discovered from the Alphus wheel."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, TypeVar

from alphus.config import QualityGateConfig
from alphus.contracts.cyclomatic import CyclomaticReport, CyclomaticRuleOperations
from alphus.contracts.findings import Finding
from alphus.contracts.python_style import StyleFindings
from alphus.contracts.shared_utilities import SharedUtilitiesReport
from alphus.execution.results import RuleOutput
from alphus.policy.feature_definition import FeatureDefinition
from alphus.policy.morphology import RuleMorphology

_RunnerOutput_co = TypeVar("_RunnerOutput_co", covariant=True)


class BuiltinRunner(Protocol[_RunnerOutput_co]):
    """Synchronous provider contract shared by registered built-ins."""

    def __call__(
        self, root: Path, files: Sequence[Path], config: QualityGateConfig, /
    ) -> _RunnerOutput_co: ...


@dataclass(frozen=True, slots=True)
class BuiltinFeature:
    """One feature's metadata, morphology, and typed execution provider."""

    definition: FeatureDefinition
    morphology: RuleMorphology
    runner: BuiltinRunner[RuleOutput]
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


def _require_output_shape(feature: BuiltinFeature, expected: str) -> None:
    if feature.definition.output_shape != expected:
        raise ValueError(f"{type(feature).__name__} requires output shape {expected!r}")


@dataclass(frozen=True, slots=True)
class FindingBuiltinFeature(BuiltinFeature):
    """Feature whose typed runner returns the standard finding list."""

    runner: BuiltinRunner[list[Finding]]

    def __post_init__(self) -> None:
        BuiltinFeature.__post_init__(self)
        _require_output_shape(self, "findings")


@dataclass(frozen=True, slots=True)
class MessageBuiltinFeature(BuiltinFeature):
    """Feature whose typed runner preserves the legacy message-list output."""

    runner: BuiltinRunner[list[str]]

    def __post_init__(self) -> None:
        BuiltinFeature.__post_init__(self)
        _require_output_shape(self, "messages")


@dataclass(frozen=True, slots=True)
class PythonStyleBuiltinFeature(BuiltinFeature):
    """Feature whose typed runner returns named Python-style categories."""

    runner: BuiltinRunner[dict[str, StyleFindings]]

    def __post_init__(self) -> None:
        BuiltinFeature.__post_init__(self)
        _require_output_shape(self, "python-style")


@dataclass(frozen=True, slots=True)
class SharedUtilitiesBuiltinFeature(BuiltinFeature):
    """Feature whose typed runner returns the shared-utilities report."""

    runner: BuiltinRunner[SharedUtilitiesReport]

    def __post_init__(self) -> None:
        BuiltinFeature.__post_init__(self)
        _require_output_shape(self, "shared-utilities")


@dataclass(frozen=True, slots=True)
class CyclomaticBuiltinFeature(BuiltinFeature):
    """Native cyclomatic provider and report with its required operations."""

    runner: BuiltinRunner[CyclomaticReport]
    cyclomatic_operations: CyclomaticRuleOperations = field()

    def __post_init__(self) -> None:
        BuiltinFeature.__post_init__(self)
        _require_output_shape(self, "cyclomatic-report")


__all__ = [
    "BuiltinFeature",
    "CyclomaticBuiltinFeature",
    "FindingBuiltinFeature",
    "MessageBuiltinFeature",
    "PythonStyleBuiltinFeature",
    "SharedUtilitiesBuiltinFeature",
]
