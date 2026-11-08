"""Typed first-party check registrations discovered from the Alphus wheel."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, TypeAlias, TypeVar

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


def _validate_registration(
    definition: FeatureDefinition,
    morphology: RuleMorphology,
    runner: object,
    cyclomatic_operations: CyclomaticRuleOperations | None,
    expected_shape: str | None,
    form_name: str,
) -> None:
    if definition.selector != morphology.selector:
        raise ValueError("built-in feature metadata and morphology selectors differ")
    if not callable(runner):
        raise TypeError("built-in feature runner must be callable")
    is_cyclomatic = definition.output_shape == "cyclomatic-report"
    if is_cyclomatic != (cyclomatic_operations is not None):
        raise ValueError(
            "cyclomatic features require exactly one typed operations contract"
        )
    if expected_shape is not None and definition.output_shape != expected_shape:
        raise ValueError(f"{form_name} requires output shape {expected_shape!r}")


@dataclass(frozen=True, slots=True)
class BuiltinFeature:
    """Legacy broad-result registration retained during shape migration."""

    definition: FeatureDefinition
    morphology: RuleMorphology
    runner: BuiltinRunner[RuleOutput]
    cyclomatic_operations: CyclomaticRuleOperations | None = None

    def __post_init__(self) -> None:
        _validate_registration(
            self.definition,
            self.morphology,
            self.runner,
            self.cyclomatic_operations,
            None,
            type(self).__name__,
        )


@dataclass(frozen=True, slots=True)
class FindingBuiltinFeature:
    """Feature whose typed runner returns the standard finding list."""

    definition: FeatureDefinition
    morphology: RuleMorphology
    runner: BuiltinRunner[list[Finding]]
    cyclomatic_operations: CyclomaticRuleOperations | None = None

    def __post_init__(self) -> None:
        _validate_registration(
            self.definition,
            self.morphology,
            self.runner,
            self.cyclomatic_operations,
            "findings",
            type(self).__name__,
        )


@dataclass(frozen=True, slots=True)
class MessageBuiltinFeature:
    """Feature whose typed runner preserves the legacy message-list output."""

    definition: FeatureDefinition
    morphology: RuleMorphology
    runner: BuiltinRunner[list[str]]
    cyclomatic_operations: CyclomaticRuleOperations | None = None

    def __post_init__(self) -> None:
        _validate_registration(
            self.definition,
            self.morphology,
            self.runner,
            self.cyclomatic_operations,
            "messages",
            type(self).__name__,
        )


@dataclass(frozen=True, slots=True)
class PythonStyleBuiltinFeature:
    """Feature whose typed runner returns named Python-style categories."""

    definition: FeatureDefinition
    morphology: RuleMorphology
    runner: BuiltinRunner[dict[str, StyleFindings]]
    cyclomatic_operations: CyclomaticRuleOperations | None = None

    def __post_init__(self) -> None:
        _validate_registration(
            self.definition,
            self.morphology,
            self.runner,
            self.cyclomatic_operations,
            "python-style",
            type(self).__name__,
        )


@dataclass(frozen=True, slots=True)
class SharedUtilitiesBuiltinFeature:
    """Feature whose typed runner returns the shared-utilities report."""

    definition: FeatureDefinition
    morphology: RuleMorphology
    runner: BuiltinRunner[SharedUtilitiesReport]
    cyclomatic_operations: CyclomaticRuleOperations | None = None

    def __post_init__(self) -> None:
        _validate_registration(
            self.definition,
            self.morphology,
            self.runner,
            self.cyclomatic_operations,
            "shared-utilities",
            type(self).__name__,
        )


@dataclass(frozen=True, slots=True)
class CyclomaticBuiltinFeature:
    """Native cyclomatic provider and report with its required operations."""

    definition: FeatureDefinition
    morphology: RuleMorphology
    runner: BuiltinRunner[CyclomaticReport]
    cyclomatic_operations: CyclomaticRuleOperations = field()

    def __post_init__(self) -> None:
        _validate_registration(
            self.definition,
            self.morphology,
            self.runner,
            self.cyclomatic_operations,
            "cyclomatic-report",
            type(self).__name__,
        )


BuiltinFeatureRegistration: TypeAlias = (
    BuiltinFeature
    | FindingBuiltinFeature
    | MessageBuiltinFeature
    | PythonStyleBuiltinFeature
    | SharedUtilitiesBuiltinFeature
    | CyclomaticBuiltinFeature
)


__all__ = [
    "BuiltinFeature",
    "BuiltinFeatureRegistration",
    "CyclomaticBuiltinFeature",
    "FindingBuiltinFeature",
    "MessageBuiltinFeature",
    "PythonStyleBuiltinFeature",
    "SharedUtilitiesBuiltinFeature",
]
