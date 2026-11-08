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
        "shared-utilities": RuleSpec(
            "shared_utilities",
            RuleOutputShape.SHARED_UTILITIES,
            "Finds duplicated shared-helper implementations and direct Git calls.",
            ("python",),
        ),
        "python-style": RuleSpec(
            "python_style",
            RuleOutputShape.PYTHON_STYLE,
            "Runs configured Python source-style checks.",
            ("python",),
        ),
        "runtime-types": RuleSpec(
            "runtime_types",
            RuleOutputShape.MESSAGES,
            "Reviews configured Python runtime type-checking conventions.",
            ("python",),
        ),
        "cli": RuleSpec(
            "cli",
            RuleOutputShape.MESSAGES,
            "Reviews configured Python command-line interface contracts.",
            ("python",),
        ),
        "script-policy": RuleSpec(
            "script_policy",
            RuleOutputShape.MESSAGES,
            "Checks configured Python and Node launcher/script conventions.",
            ("python", "javascript"),
        ),
        "repeated-numeric-limits": RuleSpec(
            "repeated_numeric_limits",
            RuleOutputShape.FINDINGS,
            "Reviews repeated numeric thresholds in explicitly selected Python analysis paths.",
            ("python",),
        ),
        "source-test-coverage": RuleSpec(
            "source_test_coverage",
            RuleOutputShape.FINDINGS,
            "Audits caller-declared source-to-test relationships against "
            "revision-matched execution evidence; it does not infer relationships "
            "from filenames or assess test correctness.",
            ("repository",),
            requires_files=False,
        ),
        "source-families": RuleSpec(
            "source_families",
            RuleOutputShape.FINDINGS,
            "Flags flat similarly named source families for human architectural review.",
            ("configurable-source",),
        ),
        "typing-stub-suggestions": RuleSpec(
            "typing_stub_suggestions",
            RuleOutputShape.FINDINGS,
            "Suggests compatible typing stub packages for declared dependencies.",
            ("python", "typing"),
        ),
        "suppression-reasons": RuleSpec(
            "suppression_reasons",
            RuleOutputShape.FINDINGS,
            "Reviews selected Ruff suppressions for documented reasons.",
            ("python", "ruff"),
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
