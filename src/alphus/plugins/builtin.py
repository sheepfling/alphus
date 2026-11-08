"""Typed first-party check registrations discovered from the Alphus wheel."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Generic, Protocol, TypeAlias, TypeVar

from alphus.config import QualityGateConfig
from alphus.contracts.cyclomatic import CyclomaticReport, CyclomaticRuleOperations
from alphus.contracts.findings import Finding
from alphus.contracts.python_style import StyleFindings
from alphus.contracts.shared_utilities import SharedUtilitiesReport
from alphus.execution.results import RuleOutput
from alphus.policy.base import StrictModel
from alphus.policy.feature_definition import FeatureDefinition
from alphus.policy.morphology import RuleMorphology

_RunnerOutput_co = TypeVar("_RunnerOutput_co", covariant=True)
_PolicyResolver_co = TypeVar("_PolicyResolver_co", bound=StrictModel, covariant=True)
_PolicyRunner_contra = TypeVar(
    "_PolicyRunner_contra", bound=StrictModel, contravariant=True
)
_FeaturePolicy = TypeVar("_FeaturePolicy", bound=StrictModel)


class BuiltinRunner(Protocol[_RunnerOutput_co]):
    """Synchronous provider contract shared by registered built-ins."""

    def __call__(
        self, root: Path, files: Sequence[Path], config: QualityGateConfig, /
    ) -> _RunnerOutput_co: ...


class PolicyResolver(Protocol[_PolicyResolver_co]):
    """Resolve one feature's declared primary policy from validated config."""

    def __call__(self, config: QualityGateConfig, /) -> _PolicyResolver_co: ...


class PolicyBoundBuiltinRunner(Protocol[_PolicyRunner_contra, _RunnerOutput_co]):
    """Run a typed feature using only its resolved primary policy."""

    def __call__(
        self,
        root: Path,
        files: Sequence[Path],
        policy: _PolicyRunner_contra,
        /,
    ) -> _RunnerOutput_co: ...


class CompositePolicyBoundBuiltinRunner(
    Protocol[_PolicyRunner_contra, _RunnerOutput_co]
):
    """Run a composite with its primary policy and named secondary inputs."""

    def __call__(
        self,
        root: Path,
        files: Sequence[Path],
        config: QualityGateConfig,
        policy: _PolicyRunner_contra,
        /,
    ) -> _RunnerOutput_co: ...


def _validate_registration(
    definition: FeatureDefinition,
    morphology: RuleMorphology,
    runner: object,
    cyclomatic_operations: CyclomaticRuleOperations | None,
    policy_resolver: object | None,
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
    if expected_shape is not None and not callable(policy_resolver):
        raise TypeError("typed built-in features require a policy resolver")
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
            None,
            type(self).__name__,
        )


@dataclass(frozen=True, slots=True)
class FindingBuiltinFeature(Generic[_FeaturePolicy]):
    """Feature whose typed runner returns the standard finding list."""

    definition: FeatureDefinition
    morphology: RuleMorphology
    runner: PolicyBoundBuiltinRunner[_FeaturePolicy, list[Finding]]
    policy_resolver: PolicyResolver[_FeaturePolicy]
    cyclomatic_operations: CyclomaticRuleOperations | None = None

    def __post_init__(self) -> None:
        _validate_registration(
            self.definition,
            self.morphology,
            self.runner,
            self.cyclomatic_operations,
            self.policy_resolver,
            "findings",
            type(self).__name__,
        )


@dataclass(frozen=True, slots=True)
class CompositeFindingBuiltinFeature(Generic[_FeaturePolicy]):
    """Finding-producing composite with explicit secondary config inputs."""

    definition: FeatureDefinition
    morphology: RuleMorphology
    runner: CompositePolicyBoundBuiltinRunner[_FeaturePolicy, list[Finding]]
    policy_resolver: PolicyResolver[_FeaturePolicy]
    cyclomatic_operations: CyclomaticRuleOperations | None = None

    def __post_init__(self) -> None:
        _validate_registration(
            self.definition,
            self.morphology,
            self.runner,
            self.cyclomatic_operations,
            self.policy_resolver,
            "findings",
            type(self).__name__,
        )


@dataclass(frozen=True, slots=True)
class MessageBuiltinFeature(Generic[_FeaturePolicy]):
    """Feature whose typed runner preserves the legacy message-list output."""

    definition: FeatureDefinition
    morphology: RuleMorphology
    runner: PolicyBoundBuiltinRunner[_FeaturePolicy, list[str]]
    policy_resolver: PolicyResolver[_FeaturePolicy]
    cyclomatic_operations: CyclomaticRuleOperations | None = None

    def __post_init__(self) -> None:
        _validate_registration(
            self.definition,
            self.morphology,
            self.runner,
            self.cyclomatic_operations,
            self.policy_resolver,
            "messages",
            type(self).__name__,
        )


@dataclass(frozen=True, slots=True)
class PythonStyleBuiltinFeature(Generic[_FeaturePolicy]):
    """Feature whose typed runner returns named Python-style categories."""

    definition: FeatureDefinition
    morphology: RuleMorphology
    runner: PolicyBoundBuiltinRunner[_FeaturePolicy, dict[str, StyleFindings]]
    policy_resolver: PolicyResolver[_FeaturePolicy]
    cyclomatic_operations: CyclomaticRuleOperations | None = None

    def __post_init__(self) -> None:
        _validate_registration(
            self.definition,
            self.morphology,
            self.runner,
            self.cyclomatic_operations,
            self.policy_resolver,
            "python-style",
            type(self).__name__,
        )


@dataclass(frozen=True, slots=True)
class SharedUtilitiesBuiltinFeature(Generic[_FeaturePolicy]):
    """Feature whose typed runner returns the shared-utilities report."""

    definition: FeatureDefinition
    morphology: RuleMorphology
    runner: PolicyBoundBuiltinRunner[_FeaturePolicy, SharedUtilitiesReport]
    policy_resolver: PolicyResolver[_FeaturePolicy]
    cyclomatic_operations: CyclomaticRuleOperations | None = None

    def __post_init__(self) -> None:
        _validate_registration(
            self.definition,
            self.morphology,
            self.runner,
            self.cyclomatic_operations,
            self.policy_resolver,
            "shared-utilities",
            type(self).__name__,
        )


@dataclass(frozen=True, slots=True)
class CyclomaticBuiltinFeature(Generic[_FeaturePolicy]):
    """Native cyclomatic provider and report with its required operations."""

    definition: FeatureDefinition
    morphology: RuleMorphology
    runner: PolicyBoundBuiltinRunner[_FeaturePolicy, CyclomaticReport]
    policy_resolver: PolicyResolver[_FeaturePolicy]
    cyclomatic_operations: CyclomaticRuleOperations = field()

    def __post_init__(self) -> None:
        _validate_registration(
            self.definition,
            self.morphology,
            self.runner,
            self.cyclomatic_operations,
            self.policy_resolver,
            "cyclomatic-report",
            type(self).__name__,
        )


BuiltinFeatureRegistration: TypeAlias = (
    BuiltinFeature
    | FindingBuiltinFeature[Any]
    | CompositeFindingBuiltinFeature[Any]
    | MessageBuiltinFeature[Any]
    | PythonStyleBuiltinFeature[Any]
    | SharedUtilitiesBuiltinFeature[Any]
    | CyclomaticBuiltinFeature[Any]
)


__all__ = [
    "BuiltinFeature",
    "BuiltinFeatureRegistration",
    "CompositeFindingBuiltinFeature",
    "CompositePolicyBoundBuiltinRunner",
    "CyclomaticBuiltinFeature",
    "FindingBuiltinFeature",
    "MessageBuiltinFeature",
    "PolicyBoundBuiltinRunner",
    "PolicyResolver",
    "PythonStyleBuiltinFeature",
    "SharedUtilitiesBuiltinFeature",
]
