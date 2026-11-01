"""Load only explicitly enabled rule plugins into an immutable registry."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from importlib.metadata import EntryPoint, entry_points
from types import MappingProxyType
from typing import Any

from alphus.plugins.api import (
    PLUGIN_API_VERSION,
    PLUGIN_ENTRY_POINT_GROUP,
    PluginRuleSpec,
    RulePlugin,
)
from alphus.policy.catalog import RULE_SPECS
from alphus.policy.plugins import PluginPolicy


@dataclass(frozen=True, slots=True)
class PluginRuleBinding:
    """One validated plugin rule and the package that owns it."""

    selector: str
    plugin: RulePlugin
    rule: PluginRuleSpec[Any]
    distribution: str | None = None
    distribution_version: str | None = None


def installed_plugin_names() -> tuple[str, ...]:
    """List entry point names without importing plugin code."""
    try:
        return tuple(
            sorted(
                {
                    candidate.name
                    for candidate in entry_points(group=PLUGIN_ENTRY_POINT_GROUP)
                }
            )
        )
    except Exception as error:
        raise ValueError(f"could not discover Alphus rule plugins: {error}") from error


@lru_cache(maxsize=32)
def load_enabled_plugins(
    enabled: tuple[str, ...],
) -> Mapping[str, PluginRuleBinding]:
    """Discover selected entry points in stable order and validate their contract."""
    if not enabled:
        return MappingProxyType({})
    selected = tuple(sorted(enabled))
    if len(selected) != len(set(selected)):
        raise ValueError("enabled plugin names must be unique")
    try:
        candidates = tuple(entry_points(group=PLUGIN_ENTRY_POINT_GROUP))
    except Exception as error:
        raise ValueError(f"could not discover Alphus rule plugins: {error}") from error
    by_name: dict[str, list[EntryPoint]] = {}
    for candidate in candidates:
        if candidate.name in selected:
            by_name.setdefault(candidate.name, []).append(candidate)

    missing = set(selected).difference(by_name)
    if missing:
        raise ValueError(
            "enabled Alphus rule plugin entry point(s) are not installed: "
            f"{', '.join(sorted(missing))}"
        )

    bindings: dict[str, PluginRuleBinding] = {}
    for name in selected:
        matches = by_name[name]
        if len(matches) != 1:
            raise ValueError(
                f"multiple Alphus rule plugins use entry point name {name!r}"
            )
        entry_point = matches[0]
        try:
            factory = entry_point.load()
            plugin = factory()
        except Exception as error:
            raise ValueError(
                f"could not load enabled rule plugin {name!r}: {error}"
            ) from error
        if not isinstance(plugin, RulePlugin):
            raise TypeError(
                f"entry point {name!r} must return an alphus.plugins.RulePlugin"
            )
        if plugin.api_version != PLUGIN_API_VERSION:
            raise ValueError(
                f"plugin {name!r} uses API version {plugin.api_version}; "
                f"this Alphus supports version {PLUGIN_API_VERSION}"
            )
        if plugin.name != name:
            raise ValueError(
                f"plugin name {plugin.name!r} does not match entry point {name!r}"
            )
        for rule in plugin.rules:
            config_model = rule.config_model
            model_config = config_model.model_config
            if (
                model_config.get("extra") != "forbid"
                or model_config.get("strict") is not True
                or model_config.get("frozen") is not True
            ):
                raise ValueError(
                    f"plugin rule {name}:{rule.name} config must be strict, "
                    "frozen, and forbid extra fields"
                )
            selector = f"{name}:{rule.name}"
            if selector in RULE_SPECS or selector in bindings:
                raise ValueError(f"duplicate Alphus rule selector {selector!r}")
            distribution = getattr(entry_point, "dist", None)
            distribution_name = (
                distribution.metadata.get("Name") if distribution is not None else None
            )
            distribution_version = (
                distribution.version if distribution is not None else None
            )
            bindings[selector] = PluginRuleBinding(
                selector,
                plugin,
                rule,
                distribution_name,
                distribution_version,
            )
    return MappingProxyType(bindings)


def enabled_plugin_registry(policy: PluginPolicy) -> Mapping[str, PluginRuleBinding]:
    """Resolve one validated plugin policy through the process-local registry."""
    return load_enabled_plugins(policy.enabled)


def validate_plugin_settings(policy: PluginPolicy) -> None:
    """Validate selectors and typed settings for every enabled plugin rule."""
    registry = enabled_plugin_registry(policy)
    for configured in policy.rules:
        binding = registry.get(configured.selector)
        if binding is None:
            raise ValueError(
                f"settings reference unknown or disabled plugin rule "
                f"{configured.selector!r}"
            )
        try:
            binding.rule.config_model.model_validate(
                policy.settings_for(configured.selector), strict=True
            )
        except Exception as error:
            raise ValueError(
                f"invalid settings for plugin rule {configured.selector!r}: {error}"
            ) from error
