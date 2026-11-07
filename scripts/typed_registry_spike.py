"""Small experiment for typed, metadata-only built-in check registration.

This is design-spike code, not the production registry. It tests standard
entry-point discovery, typed feature-owned metadata, and deferred providers.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from importlib.metadata import EntryPoint, entry_points
from pathlib import Path
from types import MappingProxyType
from typing import Generic, Protocol, TypeVar, runtime_checkable

from alphus.contracts.model import StrictModel
from alphus.contracts.rule_tags import RuleTag
from alphus.plugins.registry import load_enabled_plugins
from alphus.policy.morphology import RuleMorphology

BUILTIN_SPIKE_ENTRY_POINT_GROUP = "alphus.builtin_checks.spike.v1"
PROVIDER_SPIKE_ENTRY_POINT_GROUP = "alphus.check_providers.spike.v1"
_SELECTOR = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*\Z")

SettingsT_contra = TypeVar("SettingsT_contra", bound=StrictModel, contravariant=True)
EvidenceT_co = TypeVar("EvidenceT_co", covariant=True)
SettingsT = TypeVar("SettingsT", bound=StrictModel)
EvidenceT = TypeVar("EvidenceT")
OutputT = TypeVar("OutputT")


class CheckProvider(Protocol[SettingsT_contra, EvidenceT_co]):
    """A provider's typed analysis boundary."""

    def analyze(
        self, root: Path, files: Sequence[Path], settings: SettingsT_contra
    ) -> EvidenceT_co: ...


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
    """Typed check metadata with a deferred provider factory and result adapter."""

    selector: str
    settings_model: type[SettingsT]
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
        self, root: Path, files: Sequence[Path], settings: SettingsT
    ) -> OutputT:
        """Run the selected provider and preserve its declared output type."""
        evidence = self.provider_factory().analyze(root, files, settings)
        return self.adapt_result(evidence)


@dataclass(frozen=True, slots=True)
class EntryPointProviderFactory(Generic[SettingsT, EvidenceT]):
    """Resolve the selected provider through a standard provider entry point."""

    selector: str

    def __call__(self) -> CheckProvider[SettingsT, EvidenceT]:
        candidates = tuple(
            point
            for point in entry_points(group=PROVIDER_SPIKE_ENTRY_POINT_GROUP)
            if point.name == self.selector
        )
        if len(candidates) != 1:
            raise ValueError(
                f"expected one provider entry point for {self.selector!r}; "
                f"found {len(candidates)}"
            )
        factory: Callable[[], CheckProvider[SettingsT, EvidenceT]] = candidates[
            0
        ].load()
        return factory()


class CheckRegistryEntry(Protocol):
    """Shared identity view over built-in and plugin registration records."""

    @property
    def selector(self) -> str: ...


@runtime_checkable
class _DefinitionFactory(Protocol):
    def __call__(self) -> CheckRegistryEntry: ...


class CheckRegistry:
    """Combine first-party metadata with explicitly enabled plugin v1 rules."""

    def __init__(self, definitions: Mapping[str, CheckRegistryEntry]) -> None:
        self._definitions = MappingProxyType(dict(definitions))

    @classmethod
    def discover(
        cls,
        enabled_plugins: tuple[str, ...] = (),
        group: str = BUILTIN_SPIKE_ENTRY_POINT_GROUP,
    ) -> CheckRegistry:
        """Load metadata factories, then reuse the production plugin loader."""
        candidates: tuple[EntryPoint, ...] = tuple(entry_points(group=group))
        ordered = tuple(sorted(candidates, key=lambda point: (point.name, point.value)))
        definitions: dict[str, CheckRegistryEntry] = {}
        for point in ordered:
            if point.name in definitions:
                raise ValueError(f"duplicate built-in check entry point {point.name!r}")
            factory: _DefinitionFactory = point.load()
            definition = factory()
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
        definitions.update(plugin_definitions)
        return cls(definitions)

    @property
    def definitions(self) -> Mapping[str, CheckRegistryEntry]:
        """Return the deterministic, immutable metadata index."""
        return self._definitions


__all__ = [
    "BuiltinCheckDefinition",
    "CheckProvider",
    "CheckRegistry",
    "CheckRegistryEntry",
    "ComplaintContract",
    "ComplaintTag",
    "EntryPointProviderFactory",
]
