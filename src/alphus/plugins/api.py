"""Stable public contracts for independently packaged Alphus rules."""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Generic, TypeVar, cast

from alphus.contracts.findings import RemediationPriority, Severity
from alphus.contracts.model import StrictModel

PLUGIN_API_VERSION = 1
PLUGIN_ENTRY_POINT_GROUP = "alphus.rules.v1"
_SLUG = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*\Z")

ConfigT = TypeVar("ConfigT", bound=StrictModel)


def _immutable_sequence(value: object, description: str) -> tuple[object, ...]:
    if isinstance(value, tuple):
        return cast(tuple[object, ...], value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return tuple(cast(Sequence[object], value))
    raise TypeError(f"{description} must be a sequence")


def _require_config_model(value: object) -> None:
    if not isinstance(value, type) or not issubclass(value, StrictModel):
        raise TypeError("plugin rule config models must extend StrictModel")


@dataclass(frozen=True, slots=True)
class PluginFinding:
    """A plugin-owned finding before Alphus adds plugin provenance."""

    rule_id: str
    message: str
    path: str | None = None
    line: int | None = None
    severity: Severity = "error"
    priority: RemediationPriority | None = None

    def __post_init__(self) -> None:
        if _SLUG.fullmatch(self.rule_id) is None:
            raise ValueError("plugin finding IDs must be lowercase slugs")
        if (
            not self.message
            or self.message != self.message.strip()
            or "\x00" in self.message
        ):
            raise ValueError("plugin finding messages must be non-empty and trimmed")
        if self.path is not None:
            path = PurePosixPath(self.path)
            if (
                not self.path
                or path.is_absolute()
                or "\\" in self.path
                or "\x00" in self.path
                or ".." in path.parts
            ):
                raise ValueError("plugin finding paths must be repository-relative")
        if self.line is not None and self.line < 1:
            raise ValueError("plugin finding lines must be positive")
        if self.severity not in {"error", "warning", "info"}:
            raise ValueError(f"unsupported plugin finding severity: {self.severity!r}")
        if self.priority is not None and self.priority not in {
            "low",
            "normal",
            "high",
            "urgent",
        }:
            raise ValueError(f"unsupported plugin finding priority: {self.priority!r}")


PluginChecker = Callable[[Path, Sequence[Path], ConfigT], Sequence[PluginFinding]]


@dataclass(frozen=True, slots=True)
class PluginRuleSpec(Generic[ConfigT]):
    """One independently implemented checker and its recommendation metadata."""

    name: str
    config_model: type[ConfigT]
    check: PluginChecker[ConfigT]
    summary: str
    applies_to: tuple[str, ...]
    domains: tuple[str, ...] = ()
    requires_files: bool = True

    def __post_init__(self) -> None:
        for field_name in ("applies_to", "domains"):
            labels = _immutable_sequence(getattr(self, field_name), field_name)
            object.__setattr__(self, field_name, labels)
        if _SLUG.fullmatch(self.name) is None:
            raise ValueError("plugin rule names must be lowercase slugs")
        if not self.summary.strip():
            raise ValueError("plugin rules need a non-empty summary")
        _validate_labels(self.applies_to, "applicability labels", required=True)
        _validate_labels(self.domains, "domain tags", required=False)
        _require_config_model(self.config_model)
        if not callable(self.check):
            raise TypeError("plugin rule check must be callable")


@dataclass(frozen=True, slots=True)
class RulePlugin:
    """The object returned by an ``alphus.rules.v1`` entry point."""

    name: str
    rules: tuple[PluginRuleSpec[Any], ...]
    api_version: int = PLUGIN_API_VERSION

    def __post_init__(self) -> None:
        rules = _immutable_sequence(self.rules, "plugin rules")
        object.__setattr__(self, "rules", rules)
        if _SLUG.fullmatch(self.name) is None:
            raise ValueError("plugin names must be lowercase slugs")
        if type(self.api_version) is not int or self.api_version < 1:
            raise ValueError("plugin API version must be a positive integer")
        if not self.rules:
            raise ValueError("a rule plugin must provide at least one rule")
        names = tuple(rule.name for rule in self.rules)
        if len(names) != len(set(names)):
            raise ValueError("plugin rule names must be unique")


def _validate_labels(
    labels: tuple[str, ...], description: str, *, required: bool
) -> None:
    if required and not labels:
        raise ValueError(f"plugin rules need {description}")
    if len(labels) != len(set(labels)) or any(
        _SLUG.fullmatch(label) is None for label in labels
    ):
        raise ValueError(f"plugin rule {description} must be unique lowercase slugs")
