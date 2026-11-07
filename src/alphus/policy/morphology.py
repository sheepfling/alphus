"""Rule-level detector morphology, kept separate from enforcement policy."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import cast

from alphus.contracts.rule_tags import RuleTag

_SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")


def _slug_text(field_name: str, value: object) -> str:
    candidate: str | bytes = cast(str | bytes, value)
    if type(candidate) is not str or not _SLUG.fullmatch(candidate):
        raise ValueError(f"morphology {field_name} must be a lowercase slug")
    return candidate


def _immutable_slug_tuple(field_name: str, value: object) -> tuple[str, ...]:
    candidate: tuple[object, ...] | list[object] = cast(
        tuple[object, ...] | list[object], value
    )
    if type(candidate) is not tuple:
        raise TypeError(f"morphology {field_name} must be an immutable tuple")
    result: list[str] = []
    for raw_value in candidate:
        string_value: str | bytes = cast(str | bytes, raw_value)
        if type(string_value) is not str:
            raise TypeError(f"morphology {field_name} must contain strings")
        if not _SLUG.fullmatch(string_value):
            raise ValueError(f"morphology {field_name} must contain lowercase slugs")
        result.append(string_value)
    values = tuple(result)
    if not values or len(values) != len(set(values)):
        raise ValueError(f"morphology {field_name} must be non-empty and unique")
    return values


def _immutable_rule_tags(value: object) -> tuple[RuleTag, ...]:
    candidate: tuple[object, ...] | list[object] = cast(
        tuple[object, ...] | list[object], value
    )
    if type(candidate) is not tuple:
        raise TypeError("morphology finding_ids must be an immutable tuple")
    result: list[RuleTag] = []
    for raw_value in candidate:
        tag: RuleTag | str = cast(RuleTag | str, raw_value)
        if type(tag) is not RuleTag:
            raise TypeError("morphology finding_ids must contain RuleTag values")
        result.append(tag)
    values = tuple(result)
    if not values or len(values) != len(set(values)):
        raise ValueError("morphology finding_ids must be non-empty and unique")
    return values


def _immutable_contract_names(value: object) -> tuple[str, ...]:
    candidate: tuple[object, ...] | list[object] = cast(
        tuple[object, ...] | list[object], value
    )
    if type(candidate) is not tuple:
        raise TypeError("morphology finding_contracts must be an immutable tuple")
    names: list[str] = []
    for raw_value in candidate:
        name = _slug_text("finding_contracts", raw_value)
        names.append(name)
    result = tuple(names)
    if len(result) != len(set(result)):
        raise ValueError("morphology finding_contracts must be unique")
    return result


def _immutable_mechanisms(value: object) -> tuple[DetectionMechanism, ...]:
    candidate: tuple[object, ...] | list[object] = cast(
        tuple[object, ...] | list[object], value
    )
    if type(candidate) is not tuple:
        raise TypeError("morphology mechanisms must be an immutable tuple")
    result: list[DetectionMechanism] = []
    for raw_value in candidate:
        match raw_value:
            case DetectionMechanism() as mechanism:
                result.append(mechanism)
            case _:
                raise TypeError(
                    "morphology mechanisms must contain DetectionMechanism values"
                )
    values = tuple(result)
    if not values or len(values) != len(set(values)):
        raise ValueError("morphology mechanisms must be non-empty and unique")
    return values


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
    finding_contracts: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _slug_text("selector", self.selector)
        _slug_text("concern", self.concern)
        object.__setattr__(self, "claim_kind", ClaimKind(self.claim_kind))
        claim: str | bytes = cast(str | bytes, self.claim)
        if type(claim) is not str or not claim.strip():
            raise ValueError("morphology claims must not be empty")
        _immutable_rule_tags(self.finding_ids)
        _immutable_contract_names(self.finding_contracts)
        _immutable_slug_tuple("inspected_scope", self.inspected_scope)
        _immutable_slug_tuple("languages_formats", self.languages_formats)
        _immutable_slug_tuple("evidence_kinds", self.evidence_kinds)
        _immutable_mechanisms(self.mechanisms)
        object.__setattr__(
            self,
            "evaluation_maturity",
            EvaluationMaturity(self.evaluation_maturity),
        )


__all__ = ["ClaimKind", "DetectionMechanism", "EvaluationMaturity", "RuleMorphology"]
