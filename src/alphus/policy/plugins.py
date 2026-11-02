"""Explicit opt-in settings for third-party rule plugins."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any, Self, cast

from pydantic import model_validator

from alphus.policy.base import StrictModel, require_unique

_PLUGIN_NAME = r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*"
_SELECTOR = re.compile(rf"{_PLUGIN_NAME}:{_PLUGIN_NAME}\Z")


def _string_keyed_mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError("plugin rule settings must be a TOML table")
    mapping = cast(Mapping[object, object], value)
    if any(not isinstance(key, str) for key in mapping):
        raise TypeError("plugin rule setting keys must be strings")
    return cast(Mapping[str, object], mapping)


class PluginRuleSettings(StrictModel):
    """JSON-valued TOML settings for one namespaced plugin rule."""

    selector: str
    settings_json: str = "{}"

    @model_validator(mode="after")
    def validate_settings(self) -> Self:
        if _SELECTOR.fullmatch(self.selector) is None:
            raise ValueError("plugin rule settings need a plugin:rule selector")
        decoded = json.loads(self.settings_json)
        if not isinstance(decoded, dict):
            raise TypeError("plugin rule settings must be a TOML table")
        return self


class PluginPolicy(StrictModel):
    """Installed plugins load only when named in this explicit allowlist."""

    enabled: tuple[str, ...] = ()
    rules: tuple[PluginRuleSettings, ...] = ()

    @model_validator(mode="before")
    @classmethod
    def normalize_rule_settings(cls, value: object) -> object:
        if not isinstance(value, Mapping):
            return value
        document: dict[str, object] = dict(cast(Mapping[str, object], value))
        rules = document.get("rules", {})
        if isinstance(rules, Mapping):
            normalized: list[dict[str, str]] = []
            rule_mapping = cast(Mapping[object, object], rules)
            for selector, settings in sorted(
                rule_mapping.items(), key=lambda item: str(item[0])
            ):
                if not isinstance(selector, str) or not isinstance(settings, Mapping):
                    raise TypeError("plugin rules must map selectors to TOML tables")
                setting_mapping = _string_keyed_mapping(cast(object, settings))
                try:
                    encoded = json.dumps(
                        setting_mapping,
                        allow_nan=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                except (TypeError, ValueError) as error:
                    raise ValueError(
                        "plugin rule settings must contain JSON-compatible TOML values"
                    ) from error
                normalized.append({"selector": selector, "settings_json": encoded})
            document["rules"] = tuple(normalized)
        return document

    @model_validator(mode="after")
    def validate_plugins(self) -> Self:
        if any(re.fullmatch(_PLUGIN_NAME, name) is None for name in self.enabled):
            raise ValueError("enabled plugin names must be lowercase slugs")
        require_unique(self.enabled, "enabled plugin names must be unique")
        selectors = tuple(rule.selector for rule in self.rules)
        require_unique(selectors, "plugin rule settings selectors must be unique")
        enabled = set(self.enabled)
        unenabled = {
            rule.selector.split(":", maxsplit=1)[0]
            for rule in self.rules
            if rule.selector.split(":", maxsplit=1)[0] not in enabled
        }
        if unenabled:
            raise ValueError(
                "plugin rule settings require enabled plugins: "
                f"{', '.join(sorted(unenabled))}"
            )
        return self

    def settings_for(self, selector: str) -> dict[str, Any]:
        """Decode validated settings for one plugin selector."""
        for rule in self.rules:
            if rule.selector == selector:
                value = json.loads(rule.settings_json)
                if isinstance(value, dict):
                    return cast(dict[str, Any], value)
        return {}
