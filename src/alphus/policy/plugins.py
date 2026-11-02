"""Explicit opt-in settings for third-party rule plugins."""

from __future__ import annotations

import json
import math
import re
from typing import Any, Self, TypeAlias, cast

from pydantic import JsonValue as PydanticJsonValue
from pydantic import TypeAdapter, ValidationError, model_validator

from alphus.policy.base import StrictModel, require_unique

JsonValue: TypeAlias = (
    None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
)
_JSON_VALUE_ADAPTER: TypeAdapter[PydanticJsonValue] = TypeAdapter(
    cast(Any, PydanticJsonValue)
)
_PLUGIN_NAME = r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*"
_SELECTOR = re.compile(rf"{_PLUGIN_NAME}:{_PLUGIN_NAME}\Z")
_PLUGIN_TABLE_ADAPTER: TypeAdapter[dict[str, JsonValue]] = TypeAdapter(
    cast(Any, dict[str, PydanticJsonValue])
)


class PluginRuleSettings(StrictModel):
    """JSON-valued TOML settings for one namespaced plugin rule."""

    selector: str
    settings_json: str = "{}"

    @model_validator(mode="after")
    def validate_settings(self) -> Self:
        if _SELECTOR.fullmatch(self.selector) is None:
            raise ValueError("plugin rule settings need a plugin:rule selector")
        decoded = _validate_json_value(self.settings_json)
        _require_json_object(decoded)
        return self


_PluginConfigValue: TypeAlias = JsonValue | tuple[PluginRuleSettings, ...]


class PluginPolicy(StrictModel):
    """Installed plugins load only when named in this explicit allowlist."""

    enabled: tuple[str, ...] = ()
    rules: tuple[PluginRuleSettings, ...] = ()

    @model_validator(mode="before")
    @classmethod
    def normalize_rule_settings(cls, value: object) -> object:
        try:
            document = _PLUGIN_TABLE_ADAPTER.validate_python(value, strict=True)
        except ValidationError:
            return value
        raw_rules = document.get("rules")
        if raw_rules is None:
            return document
        try:
            rule_mapping = _PLUGIN_TABLE_ADAPTER.validate_python(raw_rules, strict=True)
        except ValidationError as error:
            raise TypeError("plugin rules must map selectors to TOML tables") from error
        normalized: list[PluginRuleSettings] = []
        for selector, raw_settings in sorted(rule_mapping.items()):
            try:
                settings = _PLUGIN_TABLE_ADAPTER.validate_python(
                    raw_settings, strict=True
                )
            except ValidationError as error:
                raise TypeError(
                    "plugin rules must map selectors to TOML tables"
                ) from error
            try:
                encoded = json.dumps(
                    settings,
                    allow_nan=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            except (TypeError, ValueError) as error:
                raise ValueError(
                    "plugin rule settings must contain JSON-compatible TOML values"
                ) from error
            normalized.append(
                PluginRuleSettings(selector=selector, settings_json=encoded)
            )
        normalized_document = cast(dict[str, _PluginConfigValue], document.copy())
        normalized_document["rules"] = tuple(normalized)
        return normalized_document

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

    def settings_for(self, selector: str) -> dict[str, JsonValue]:
        """Decode validated settings for one plugin selector."""
        for rule in self.rules:
            if rule.selector == selector:
                value = _validate_json_value(rule.settings_json)
                return _require_json_object(value)
        return {}


def _validate_json_value(source: str) -> JsonValue:
    """Decode standard JSON values without importing runtime support code."""
    value = cast(JsonValue, _JSON_VALUE_ADAPTER.validate_json(source))
    match value:
        case float() as number if not math.isfinite(number):
            raise ValueError("JSON numbers must be finite")
        case dict():
            for nested in value.values():
                _validate_nested_json_value(nested)
        case list():
            for nested in value:
                _validate_nested_json_value(nested)
        case _:
            pass
    return value


def _validate_nested_json_value(value: JsonValue) -> None:
    match value:
        case float() as number if not math.isfinite(number):
            raise ValueError("JSON numbers must be finite")
        case dict():
            for nested in value.values():
                _validate_nested_json_value(nested)
        case list():
            for nested in value:
                _validate_nested_json_value(nested)
        case _:
            return


def _require_json_object(value: JsonValue) -> dict[str, JsonValue]:
    match value:
        case dict():
            return value
        case _:
            raise TypeError("plugin rule settings must be a TOML table")
