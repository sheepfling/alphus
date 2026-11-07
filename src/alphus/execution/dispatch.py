"""Compose gate-theme runners without mixing selection into CLI rendering."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Protocol, cast

from alphus.config import QualityGateConfig, QualityRuleName
from alphus.contracts.findings import Diagnostic
from alphus.execution._generated_dispatch import RULE_RUNNERS
from alphus.execution.results import RuleOutput
from alphus.plugins.api import PluginFinding
from alphus.plugins.registry import PluginRuleBinding, enabled_plugin_registry
from alphus.policy.base import RuleSelector
from alphus.policy.catalog import RULE_SPECS, RuleSpec

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


if set(RULE_SPECS) != set(RULE_RUNNERS):
    raise RuntimeError("built-in rule metadata and runner registries differ")

BUILTIN_RULES: Mapping[str, BuiltinRuleBinding] = MappingProxyType(
    {
        selector: BuiltinRuleBinding(
            cast(QualityRuleName, selector),
            spec,
            RULE_RUNNERS[cast(QualityRuleName, selector)],
        )
        for selector, spec in RULE_SPECS.items()
    }
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
