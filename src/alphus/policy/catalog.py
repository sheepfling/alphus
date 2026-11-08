"""Built-in rule contracts shared by policy validation and profile decoding."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from types import MappingProxyType

from alphus.policy._generated_feature_definitions import FEATURE_DEFINITIONS
from alphus.policy._generated_morphology import MORPHOLOGY_BY_SELECTOR
from alphus.policy.morphology import RuleMorphology


class RuleOutputShape(StrEnum):
    FINDINGS = "findings"
    MESSAGES = "messages"
    PYTHON_STYLE = "python-style"
    SHARED_UTILITIES = "shared-utilities"
    CYCLOMATIC_REPORT = "cyclomatic-report"


@dataclass(frozen=True, slots=True)
class RuleSpec:
    """Configuration, output, and discovery metadata for one built-in rule."""

    policy_field: str
    output_shape: RuleOutputShape
    summary: str
    applies_to: tuple[str, ...]
    domains: tuple[str, ...] = ()
    requires_files: bool = True
    morphology: RuleMorphology | None = None

    def __post_init__(self) -> None:
        """Reject incomplete or malformed metadata used by agent discovery."""
        if not self.summary.strip():
            raise ValueError("built-in rules need a non-empty summary")
        if not self.applies_to or any(not label.strip() for label in self.applies_to):
            raise ValueError("built-in rules need applicability labels")
        for labels, description in (
            (self.applies_to, "applicability labels"),
            (self.domains, "domain tags"),
        ):
            if len(labels) != len(set(labels)) or any(
                label != label.casefold()
                or not label
                or any(
                    not (character.isalnum() or character == "-") for character in label
                )
                for label in labels
            ):
                raise ValueError(
                    f"built-in rule {description} must be unique lowercase slugs"
                )


_LEGACY_RULE_SPECS: Mapping[str, RuleSpec] = MappingProxyType(
    {
        "python-style": RuleSpec(
            "python_style",
            RuleOutputShape.PYTHON_STYLE,
            "Runs configured Python source-style checks.",
            ("python",),
        ),
        "cli": RuleSpec(
            "cli",
            RuleOutputShape.MESSAGES,
            "Reviews configured Python command-line interface contracts.",
            ("python",),
        ),
    }
)


_FEATURE_RULE_SPECS: Mapping[str, RuleSpec] = MappingProxyType(
    {
        selector: RuleSpec(
            definition.policy_field,
            RuleOutputShape(definition.output_shape),
            definition.summary,
            definition.applies_to,
            definition.domains,
            requires_files=definition.requires_files,
        )
        for selector, definition in FEATURE_DEFINITIONS.items()
    }
)

if set(_LEGACY_RULE_SPECS) & set(_FEATURE_RULE_SPECS):
    raise RuntimeError("built-in rule has both legacy and feature-owned metadata")

_ALL_RULE_SPECS: Mapping[str, RuleSpec] = MappingProxyType(
    {**_LEGACY_RULE_SPECS, **_FEATURE_RULE_SPECS}
)

RULE_SPECS: Mapping[str, RuleSpec] = MappingProxyType(
    {
        selector: replace(
            spec,
            morphology=MORPHOLOGY_BY_SELECTOR.get(selector),
        )
        for selector, spec in _ALL_RULE_SPECS.items()
    }
)
