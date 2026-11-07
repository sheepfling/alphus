"""Small experiment for typed, metadata-only built-in check registration.

This is design-spike code, not the production registry. It tests standard
entry-point discovery, typed feature-owned metadata, and deferred providers.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from importlib.metadata import EntryPoint, distribution
from inspect import signature
from pathlib import Path
from types import MappingProxyType
from typing import Generic, Protocol, TypeVar, cast, runtime_checkable

from alphus.contracts.model import StrictModel
from alphus.contracts.rule_tags import RuleTag
from alphus.plugins.api import PluginFinding
from alphus.plugins.registry import PluginRuleBinding, load_enabled_plugins
from alphus.policy.morphology import RuleMorphology
from scripts.registry_spike.contracts import CheckProvider

BUILTIN_SPIKE_ENTRY_POINT_GROUP = "alphus.builtin_checks.spike.v1"
_SELECTOR = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*\Z")

SettingsT = TypeVar("SettingsT", bound=StrictModel)
EvidenceT = TypeVar("EvidenceT")
OutputT = TypeVar("OutputT")


@dataclass(frozen=True, slots=True)
class ComplaintTag:
    """A finding tag and the check that may emit it."""

    emitter: str
    tag: RuleTag


@dataclass(frozen=True, slots=True)
class ComplaintContract:
    """Named, typed complaint ownership shared by one or more emitters."""

    name: str
    emitters: tuple[str, ...]
    tags: tuple[ComplaintTag, ...]

    def __post_init__(self) -> None:
        if not self.name or not self.emitters or not self.tags:
            raise ValueError("complaint contracts need a name, emitters, and tags")
        if len(self.emitters) != len(set(self.emitters)):
            raise ValueError("complaint contract emitters must be unique")
        if any(tag.emitter not in self.emitters for tag in self.tags):
            raise ValueError("complaint tags must name a declared emitter")
        if set(self.emitters) != {tag.emitter for tag in self.tags}:
            raise ValueError("every complaint emitter must own at least one tag")
        if len(self.tags) != len(set(self.tags)):
            raise ValueError("complaint tags must be unique")


@dataclass(frozen=True, slots=True)
class BuiltinCheckDefinition(Generic[SettingsT, EvidenceT, OutputT]):
    """Typed check metadata with a typed, deferred provider factory."""

    selector: str
    settings_model: type[SettingsT]
    validate_settings: Callable[[StrictModel | None], SettingsT]
    summary: str
    morphology: RuleMorphology
    complaint_contract: ComplaintContract
    provider_factory: Callable[[], CheckProvider[SettingsT, EvidenceT]]
    adapt_result: Callable[[EvidenceT], OutputT]
    requires_files: bool = True

    def __post_init__(self) -> None:
        if _SELECTOR.fullmatch(self.selector) is None:
            raise ValueError("built-in selectors must be lowercase slugs")
        if self.morphology.selector != self.selector:
            raise ValueError("check and morphology selectors must match")
        if self.selector not in self.complaint_contract.emitters:
            raise ValueError("check must own an emitter in its complaint contract")
        owned_tags = tuple(
            entry.tag
            for entry in self.complaint_contract.tags
            if entry.emitter == self.selector
        )
        if owned_tags != self.morphology.finding_ids:
            raise ValueError("morphology finding tags must match complaint ownership")
        if not self.summary.strip():
            raise ValueError("built-in checks need a non-empty summary")

    def execute(
        self, root: Path, files: Sequence[Path], settings: StrictModel | None
    ) -> object:
        """Validate dynamic registry input and preserve the adapted object."""
        validated_settings = self.validate_settings(settings)
        evidence = self.provider_factory().analyze(root, files, validated_settings)
        return self.adapt_result(evidence)

    def execute_typed(
        self, root: Path, files: Sequence[Path], settings: SettingsT
    ) -> OutputT:
        """Run a typed provider for direct callers with a known settings model."""
        evidence = self.provider_factory().analyze(root, files, settings)
        return self.adapt_result(evidence)


@dataclass(frozen=True, slots=True)
class PluginCheckEntry:
    """Adapt a validated API v1 plugin binding to the shared registry shape."""

    binding: PluginRuleBinding

    @property
    def selector(self) -> str:
        return self.binding.selector

    def execute(self, root: Path, files: Sequence[Path], settings: object) -> object:
        validated_settings = self.binding.rule.config_model.model_validate(
            settings, strict=True
        )
        return _validated_plugin_findings(
            self.binding.rule.check(root, files, validated_settings)
        )


@runtime_checkable
class CheckRegistryEntry(Protocol):
    """Shared executable contract for built-in and API v1 plugin entries."""

    @property
    def selector(self) -> str: ...

    def execute(
        self, root: Path, files: Sequence[Path], settings: StrictModel | None
    ) -> object: ...


class _DefinitionFactory(Protocol):
    def __call__(self) -> object: ...


def _distribution_entry_points(group: str) -> tuple[EntryPoint, ...]:
    """Read first-party registrations only from the installed Alphus dist."""
    return tuple(
        point for point in distribution("alphus").entry_points if point.group == group
    )


def _require_registry_entry(value: object, selector: str) -> CheckRegistryEntry:
    match value:
        case CheckRegistryEntry() as entry if callable(entry.execute):
            try:
                signature(entry.execute).bind(Path("."), (), None)
            except (TypeError, ValueError) as error:
                raise TypeError(
                    f"registration factory for {selector!r} must return an "
                    "executable check accepting root, files, and settings"
                ) from error
            return entry
        case _:
            raise TypeError(
                f"registration factory for {selector!r} must return an executable check"
            )


def _validated_plugin_findings(value: object) -> list[PluginFinding]:
    """Mirror the API v1 result boundary for a heterogeneous registry entry."""
    findings: list[PluginFinding] = []
    match value:
        case Sequence():
            items = cast(Sequence[object], value)
            for item in items:
                match item:
                    case PluginFinding() as finding:
                        findings.append(finding)
                    case _:
                        raise TypeError(
                            "plugin checkers must return PluginFinding records"
                        )
            return findings
        case _:
            raise TypeError("plugin checkers must return a sequence of PluginFinding")


class CheckRegistry:
    """Combine first-party metadata with explicitly enabled plugin v1 rules."""

    def __init__(self, definitions: Mapping[str, CheckRegistryEntry]) -> None:
        if any(selector != entry.selector for selector, entry in definitions.items()):
            raise ValueError("registry keys must match each check's selector")
        self._definitions = MappingProxyType(dict(definitions))

    @classmethod
    def discover(
        cls,
        enabled_plugins: tuple[str, ...] = (),
        group: str = BUILTIN_SPIKE_ENTRY_POINT_GROUP,
    ) -> CheckRegistry:
        """Load metadata factories, then reuse the production plugin loader."""
        candidates = _distribution_entry_points(group)
        ordered = tuple(sorted(candidates, key=lambda point: (point.name, point.value)))
        names: set[str] = set()
        duplicates: set[str] = set()
        for point in ordered:
            if point.name in names:
                duplicates.add(point.name)
            names.add(point.name)
        if duplicates:
            raise ValueError(
                "duplicate built-in check entry points: "
                f"{', '.join(sorted(duplicates))}"
            )

        definitions: dict[str, CheckRegistryEntry] = {}
        for point in ordered:
            factory: _DefinitionFactory = point.load()
            definition = _require_registry_entry(factory(), point.name)
            if definition.selector != point.name:
                raise ValueError("entry point name must match its check selector")
            definitions[point.name] = definition

        plugin_definitions = load_enabled_plugins(enabled_plugins)
        duplicate_selectors = set(definitions).intersection(plugin_definitions)
        if duplicate_selectors:
            raise ValueError(
                "duplicate check selectors across registration sources: "
                f"{', '.join(sorted(duplicate_selectors))}"
            )
        definitions.update(
            {
                selector: PluginCheckEntry(binding)
                for selector, binding in plugin_definitions.items()
            }
        )
        return cls(definitions)

    @property
    def definitions(self) -> Mapping[str, CheckRegistryEntry]:
        """Return the deterministic, immutable executable index."""
        return self._definitions


__all__ = [
    "BuiltinCheckDefinition",
    "CheckRegistry",
    "CheckRegistryEntry",
    "ComplaintContract",
    "ComplaintTag",
    "PluginCheckEntry",
]
