"""Compose gate-theme runners without mixing selection into CLI rendering."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import cast

from alphus.config import QualityGateConfig, QualityRuleName
from alphus.contracts.findings import Diagnostic
from alphus.execution._generated_dispatch import RULE_RUNNERS
from alphus.execution.results import RuleOutput
from alphus.plugins.api import PluginFinding
from alphus.plugins.registry import enabled_plugin_registry
from alphus.policy.base import RuleSelector
from alphus.policy.catalog import RULE_SPECS, RuleSpec

RuleRunner = Callable[[Path, Sequence[Path], QualityGateConfig], RuleOutput]


@dataclass(frozen=True, slots=True)
class BuiltinRuleBinding:
    """One built-in selector with its metadata and executable checker."""

    selector: QualityRuleName
    spec: RuleSpec
    runner: RuleRunner


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
    config.checks.require_rule(rule)
    return BUILTIN_RULES[rule].runner(root, files, config)


def run_rule(
    selector: RuleSelector,
    root: Path,
    files: Sequence[Path],
    config: QualityGateConfig,
) -> RuleOutput:
    """Run a validated built-in rule or one explicitly enabled plugin rule."""
    if selector in RULE_SPECS:
        return run_builtin_rule(cast(QualityRuleName, selector), root, files, config)
    binding = enabled_plugin_registry(config.plugins).get(selector)
    if binding is None:
        raise ValueError(f"unknown or disabled rule selector {selector!r}")
    if config.files is None and binding.rule.requires_files:
        raise ValueError(
            f"plugin rule {selector!r} requires a top-level [files] inventory"
        )
    settings = binding.rule.config_model.model_validate(
        config.plugins.settings_for(selector), strict=True
    )
    raw_findings = _plugin_findings(binding.rule.check(root, files, settings))
    findings: list[Diagnostic] = []
    for finding in raw_findings:
        findings.append(
            Diagnostic(
                source=f"plugin:{binding.plugin.name}",
                rule_id=f"{selector}/{finding.rule_id}",
                message=finding.message,
                severity=finding.severity,
                path=finding.path,
                line=finding.line,
                priority=finding.priority,
            )
        )
    return findings


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
    builtin = BUILTIN_RULES.get(selector)
    if builtin is not None:
        return builtin.spec.requires_files
    binding = enabled_plugin_registry(config.plugins).get(selector)
    if binding is None:
        raise ValueError(f"unknown or disabled rule selector {selector!r}")
    return binding.rule.requires_files
