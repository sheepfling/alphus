"""Compose gate-theme runners without mixing selection into CLI rendering."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Protocol, TypeVar, assert_never, cast

from alphus.config import QualityGateConfig, QualityRuleName
from alphus.contracts.cyclomatic import (
    CyclomaticRuleOperations,
)
from alphus.contracts.findings import Diagnostic
from alphus.execution._generated_dispatch import RULE_RUNNERS
from alphus.execution.results import RuleOutput, diagnostics_from_output
from alphus.plugins.api import PluginFinding
from alphus.plugins.builtin import (
    BuiltinFeature,
    BuiltinFeatureRegistration,
    CompositeFindingBuiltinFeature,
    CyclomaticBuiltinFeature,
    FindingBuiltinFeature,
    MessageBuiltinFeature,
    PolicyResolver,
    PythonStyleBuiltinFeature,
    SharedUtilitiesBuiltinFeature,
)
from alphus.plugins.builtin_registry import (
    builtin_check_entry_points,
    load_builtin_feature,
)
from alphus.plugins.registry import PluginRuleBinding, enabled_plugin_registry
from alphus.policy._generated_feature_definitions import FEATURE_DEFINITIONS
from alphus.policy.base import RuleSelector, StrictModel
from alphus.policy.catalog import RULE_SPECS, RuleOutputShape, RuleSpec
from alphus.policy.feature_definition import FeatureDefinition

RuleRunner = Callable[[Path, Sequence[Path], QualityGateConfig], RuleOutput]


class RuleBinding(Protocol):
    """Shared execution contract for selected built-in and plugin rules."""

    @property
    def selector(self) -> RuleSelector: ...

    @property
    def requires_files(self) -> bool: ...

    def run(
        self, root: Path, files: Sequence[Path], config: QualityGateConfig
    ) -> RuleOutput: ...


@dataclass(frozen=True, slots=True)
class BuiltinRuleBinding:
    """One built-in selector with its metadata and executable checker."""

    selector: QualityRuleName
    spec: RuleSpec
    runner: RuleRunner

    @property
    def requires_files(self) -> bool:
        return self.spec.requires_files

    def run(
        self, root: Path, files: Sequence[Path], config: QualityGateConfig
    ) -> RuleOutput:
        config.checks.require_rule(self.selector)
        return self.runner(root, files, config)


_FeaturePolicy = TypeVar("_FeaturePolicy", bound=StrictModel)


def _resolve_feature_policy(
    resolver: PolicyResolver[_FeaturePolicy],
    definition: FeatureDefinition,
    config: QualityGateConfig,
) -> _FeaturePolicy:
    """Resolve and verify the configured value against its declared model."""
    policy = resolver(config)
    if type(policy) is not definition.policy_model:
        raise TypeError(
            f"feature {definition.selector!r} policy resolver returned "
            f"{type(policy).__name__}, expected {definition.policy_model.__name__}"
        )
    return policy


def _run_registered_feature(
    feature: BuiltinFeatureRegistration,
    root: Path,
    files: Sequence[Path],
    config: QualityGateConfig,
) -> RuleOutput:
    """Run a selected provider while retaining its output type until adaptation."""
    match feature:
        case CompositeFindingBuiltinFeature() as composite_feature:
            policy = _resolve_feature_policy(
                composite_feature.policy_resolver,
                composite_feature.definition,
                config,
            )
            return composite_feature.runner(root, files, config, policy)
        case FindingBuiltinFeature() as findings_feature:
            policy = _resolve_feature_policy(
                findings_feature.policy_resolver, findings_feature.definition, config
            )
            return findings_feature.runner(root, files, policy)
        case MessageBuiltinFeature() as message_feature:
            policy = _resolve_feature_policy(
                message_feature.policy_resolver, message_feature.definition, config
            )
            return message_feature.runner(root, files, policy)
        case PythonStyleBuiltinFeature() as style_feature:
            policy = _resolve_feature_policy(
                style_feature.policy_resolver, style_feature.definition, config
            )
            return style_feature.runner(root, files, policy)
        case SharedUtilitiesBuiltinFeature() as utilities_feature:
            policy = _resolve_feature_policy(
                utilities_feature.policy_resolver, utilities_feature.definition, config
            )
            return utilities_feature.runner(root, files, policy)
        case CyclomaticBuiltinFeature() as cyclomatic_feature:
            policy = _resolve_feature_policy(
                cyclomatic_feature.policy_resolver,
                cyclomatic_feature.definition,
                config,
            )
            return cyclomatic_feature.runner(root, files, policy)
        case BuiltinFeature() as legacy_feature:
            return legacy_feature.runner(root, files, config)
    return assert_never(feature)


@dataclass(frozen=True, slots=True)
class EntryPointBuiltinRuleBinding:
    """One selected feature rule resolved through standard package metadata."""

    selector: QualityRuleName
    spec: RuleSpec

    @property
    def requires_files(self) -> bool:
        return self.spec.requires_files

    def run(
        self, root: Path, files: Sequence[Path], config: QualityGateConfig
    ) -> RuleOutput:
        config.checks.require_rule(self.selector)
        feature = load_builtin_feature(self.selector)
        output = _run_registered_feature(feature, root, files, config)
        diagnostics_from_output(self.selector, output)
        return output


@dataclass(frozen=True, slots=True)
class PluginRuleExecution:
    """Adapt an explicitly enabled plugin rule to the common execution shape."""

    binding: PluginRuleBinding

    @property
    def selector(self) -> RuleSelector:
        return self.binding.selector

    @property
    def requires_files(self) -> bool:
        return self.binding.rule.requires_files

    def run(
        self, root: Path, files: Sequence[Path], config: QualityGateConfig
    ) -> RuleOutput:
        if config.files is None and self.binding.rule.requires_files:
            raise ValueError(
                f"plugin rule {self.selector!r} requires a top-level [files] inventory"
            )
        settings = self.binding.rule.config_model.model_validate(
            config.plugins.settings_for(self.selector), strict=True
        )
        raw_findings = _plugin_findings(self.binding.rule.check(root, files, settings))
        return [
            Diagnostic(
                source=f"plugin:{self.binding.plugin.name}",
                rule_id=f"{self.selector}/{finding.rule_id}",
                message=finding.message,
                severity=finding.severity,
                path=finding.path,
                line=finding.line,
                priority=finding.priority,
            )
            for finding in raw_findings
        ]


builtin_check_entry_points()
_FEATURE_SELECTORS = frozenset(FEATURE_DEFINITIONS)
_LEGACY_SELECTORS = frozenset(RULE_SPECS) - _FEATURE_SELECTORS
if _LEGACY_SELECTORS != frozenset(RULE_RUNNERS):
    raise RuntimeError("legacy built-in rule metadata and runner registries differ")

BUILTIN_RULES: Mapping[str, BuiltinRuleBinding | EntryPointBuiltinRuleBinding] = (
    MappingProxyType(
        {
            selector: (
                EntryPointBuiltinRuleBinding(cast(QualityRuleName, selector), spec)
                if selector in _FEATURE_SELECTORS
                else BuiltinRuleBinding(
                    cast(QualityRuleName, selector),
                    spec,
                    RULE_RUNNERS[cast(QualityRuleName, selector)],
                )
            )
            for selector, spec in RULE_SPECS.items()
        }
    )
)


def run_builtin_rule(
    rule: QualityRuleName,
    root: Path,
    files: Sequence[Path],
    config: QualityGateConfig,
) -> RuleOutput:
    """Run one selected checker after validating its required policy."""
    return BUILTIN_RULES[rule].run(root, files, config)


def resolve_rule(selector: RuleSelector, config: QualityGateConfig) -> RuleBinding:
    """Resolve one explicitly selected rule to its typed execution adapter."""
    builtin = BUILTIN_RULES.get(selector)
    if builtin is not None:
        return builtin
    plugin = enabled_plugin_registry(config.plugins).get(selector)
    if plugin is None:
        raise ValueError(f"unknown or disabled rule selector {selector!r}")
    return PluginRuleExecution(plugin)


@lru_cache(maxsize=1)
def cyclomatic_rule_operations() -> CyclomaticRuleOperations:
    """Load the registered native-report operations only for that result shape."""
    matches = tuple(
        binding
        for binding in BUILTIN_RULES.values()
        if binding.spec.output_shape is RuleOutputShape.CYCLOMATIC_REPORT
    )
    if len(matches) != 1:
        raise RuntimeError(
            "the built-in registry must provide exactly one cyclomatic-report binding"
        )
    feature = load_builtin_feature("cyclomatic-complexity")
    return feature.cyclomatic_operations


def run_rule(
    selector: RuleSelector,
    root: Path,
    files: Sequence[Path],
    config: QualityGateConfig,
) -> RuleOutput:
    """Run a validated built-in rule or one explicitly enabled plugin rule."""
    return resolve_rule(selector, config).run(root, files, config)


def _plugin_findings(value: object) -> Sequence[PluginFinding]:
    """Reject malformed values returned across the third-party callback boundary."""
    match value:
        case str() | bytes():
            raise TypeError("plugin checkers must return a sequence of PluginFinding")
        case Sequence():
            findings = cast(Sequence[object], value)
        case _:
            raise TypeError("plugin checkers must return a sequence of PluginFinding")
    for finding in findings:
        match finding:
            case PluginFinding():
                continue
            case _:
                raise TypeError("plugin checkers must return PluginFinding records")
    return cast(Sequence[PluginFinding], findings)


def rule_requires_files(selector: RuleSelector, config: QualityGateConfig) -> bool:
    """Return the inventory requirement declared by a selected rule."""
    return resolve_rule(selector, config).requires_files
