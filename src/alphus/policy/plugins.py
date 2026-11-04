"""Explicit opt-in settings for third-party rule plugins."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from typing import Self, TypeAlias, cast

from pydantic import model_validator

from alphus.policy.base import StrictModel, require_unique

JsonValue: TypeAlias = (
    None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
)
_PLUGIN_NAME = r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*"
_SELECTOR = re.compile(rf"{_PLUGIN_NAME}:{_PLUGIN_NAME}\Z")


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
        match value:
            case Mapping():
                document = _json_object(cast(object, value))
            case _:
                return value
        raw_rules = document.get("rules")
        if raw_rules is None:
            return document
        try:
            rule_mapping = _json_object(raw_rules)
        except TypeError as error:
            raise TypeError("plugin rules must map selectors to TOML tables") from error
        normalized: list[PluginRuleSettings] = []
        for selector, raw_settings in sorted(rule_mapping.items()):
            try:
                settings = _json_object(raw_settings)
            except TypeError as error:
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
    try:
        decoded: object = json.JSONDecoder(parse_constant=_reject_json_constant).decode(
            source
        )
    except json.JSONDecodeError as error:
        raise ValueError("plugin rule settings must contain valid JSON") from error
    return _normalize_json_value(decoded)


def _normalize_json_value(value: object) -> JsonValue:
    match value:
        case float() as number if math.isfinite(number):
            return number
        case float():
            raise ValueError("JSON numbers must be finite")
        case list() | tuple():
            return [
                _normalize_json_value(item) for item in cast(Sequence[object], value)
            ]
        case dict():
            normalized: dict[str, JsonValue] = {}
            for key, nested in cast(Mapping[object, object], value).items():
                match key:
                    case str() as string_key:
                        normalized[string_key] = _normalize_json_value(nested)
                    case _:
                        raise TypeError("plugin rule setting keys must be strings")
            return normalized
        case None | bool() | int() | str():
            return value
        case _:
            raise TypeError("plugin rule settings must contain JSON values")


def _json_object(value: object) -> dict[str, JsonValue]:
    match _normalize_json_value(value):
        case dict() as mapping:
            return mapping
        case _:
            raise TypeError("plugin rule settings must be a TOML table")


def _require_json_object(value: JsonValue) -> dict[str, JsonValue]:
    return _json_object(value)


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"JSON constant {value} is not permitted")
