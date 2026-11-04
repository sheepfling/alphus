"""Rule-level detector morphology, kept separate from enforcement policy."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from alphus.contracts.rule_tags import RuleTag

_SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")


class ClaimKind(StrEnum):
    """Kind of claim the detector makes about its subject."""

    CONDITION = "condition"
    RISK = "risk"
    STYLE_PREFERENCE = "style-preference"


class DetectionMechanism(StrEnum):
    """How a rule obtains candidate evidence."""

    EXACT_RULE = "exact-rule"
    BOUNDED_HEURISTIC = "bounded-heuristic"
    NATIVE_TOOL = "native-tool"
    LOCAL_MODEL_ASSISTED = "local-model-assisted"


class EvaluationMaturity(StrEnum):
    """Rule-level evaluation evidence, not per-finding confidence."""

    UNASSESSED = "unassessed"
    SYNTHETIC_ONLY = "synthetic-only"
    PUBLIC_SAMPLE_REVIEWED = "public-sample-reviewed"
    HUMAN_EVALUATED = "human-evaluated"


@dataclass(frozen=True, slots=True)
class RuleMorphology:
    """Static description of one built-in rule's claim and evidence."""

    selector: str
    finding_ids: tuple[RuleTag, ...]
    concern: str
    claim_kind: ClaimKind
    claim: str
    mechanisms: tuple[DetectionMechanism, ...]
    inspected_scope: tuple[str, ...]
    languages_formats: tuple[str, ...]
    evidence_kinds: tuple[str, ...]
    evaluation_maturity: EvaluationMaturity

    def __post_init__(self) -> None:
        if not _SLUG.fullmatch(self.selector):
            raise ValueError("morphology selectors must be lowercase slugs")
        if not _SLUG.fullmatch(self.concern):
            raise ValueError("morphology concerns must be lowercase slugs")
        object.__setattr__(self, "claim_kind", ClaimKind(self.claim_kind))
        if not self.claim.strip():
            raise ValueError("morphology claims must not be empty")
        for field_name in (
            "finding_ids",
            "inspected_scope",
            "languages_formats",
            "evidence_kinds",
        ):
            values = getattr(self, field_name)
            if not values or len(values) != len(set(values)):
                raise ValueError(
                    f"morphology {field_name} must be non-empty and unique"
                )
        if not self.mechanisms or len(self.mechanisms) != len(set(self.mechanisms)):
            raise ValueError("morphology mechanisms must be non-empty and unique")
        object.__setattr__(
            self,
            "mechanisms",
            tuple(DetectionMechanism(value) for value in self.mechanisms),
        )
        object.__setattr__(
            self,
            "evaluation_maturity",
            EvaluationMaturity(self.evaluation_maturity),
        )
        for field_name in ("inspected_scope", "languages_formats", "evidence_kinds"):
            if any(not _SLUG.fullmatch(value) for value in getattr(self, field_name)):
                raise ValueError(
                    f"morphology {field_name} must contain lowercase slugs"
                )


__all__ = ["ClaimKind", "DetectionMechanism", "EvaluationMaturity", "RuleMorphology"]
