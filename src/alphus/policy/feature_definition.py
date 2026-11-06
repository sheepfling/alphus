"""Immutable metadata for statically registered built-in check features."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, TypeAlias, cast

FeatureOutputShape = Literal[
    "findings",
    "messages",
    "python-style",
    "shared-utilities",
    "cyclomatic-report",
]

_SELECTOR = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*\Z")
_POLICY_FIELD = re.compile(r"[a-z][a-z0-9_]*\Z")
_POLICY_MODEL = re.compile(r"alphus\.policy(?:\.[a-z][a-z0-9_]*)+\.[A-Z][A-Za-z0-9]*\Z")
_PYTHON_MODULE = re.compile(r"alphus\.gates(?:\.[a-z][a-z0-9_]*)+\Z")
_FUNCTION = re.compile(r"[a-z_][a-z0-9_]*\Z")
_TAG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_StringLabels: TypeAlias = tuple[str, ...] | list[str]


@dataclass(frozen=True, slots=True)
class FeatureDefinition:
    """Static selector, strict policy, reporting, and provider registration data."""

    selector: str
    policy_field: str
    policy_model: str
    output_shape: FeatureOutputShape
    summary: str
    applies_to: tuple[str, ...]
    domains: tuple[str, ...]
    requires_files: bool
    runner_module: str
    runner_name: str
    policy_inputs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if _SELECTOR.fullmatch(self.selector) is None:
            raise ValueError("feature selectors must be lowercase slugs")
        if _POLICY_FIELD.fullmatch(self.policy_field) is None:
            raise ValueError("feature policy fields must be lowercase identifiers")
        policy_values: _StringLabels = cast(_StringLabels, self.policy_inputs)
        policy_inputs = _require_tuple(policy_values, "feature policy inputs")
        if not policy_inputs:
            policy_inputs = (self.policy_field,)
            object.__setattr__(self, "policy_inputs", policy_inputs)
        if (
            len(policy_inputs) != len(set(policy_inputs))
            or self.policy_field not in policy_inputs
            or any(_POLICY_FIELD.fullmatch(item) is None for item in policy_inputs)
        ):
            raise ValueError(
                "feature policy inputs must uniquely include the primary policy field"
            )
        if _POLICY_MODEL.fullmatch(self.policy_model) is None:
            raise ValueError("feature policy models must name a built-in policy class")
        if not self.summary.strip():
            raise ValueError("feature definitions need a summary")
        if self.output_shape not in {
            "findings",
            "messages",
            "python-style",
            "shared-utilities",
            "cyclomatic-report",
        }:
            raise ValueError("feature definitions need a supported output shape")
        applies_to_values: _StringLabels = cast(_StringLabels, self.applies_to)
        domain_values: _StringLabels = cast(_StringLabels, self.domains)
        applies_to_tuple = _require_tuple(applies_to_values, "feature applicability")
        domain_tuple = _require_tuple(domain_values, "feature domains")
        if not _valid_labels(applies_to_tuple, allow_empty=False):
            raise ValueError("feature definitions need valid applicability labels")
        if not _valid_labels(domain_tuple, allow_empty=True):
            raise ValueError("feature domain labels must be unique lowercase slugs")
        if _PYTHON_MODULE.fullmatch(self.runner_module) is None:
            raise ValueError("feature runner must use a built-in Alphus module")
        if _FUNCTION.fullmatch(self.runner_name) is None:
            raise ValueError("feature runner must name a top-level function")


def _valid_labels(values: tuple[str, ...], *, allow_empty: bool) -> bool:
    if not values:
        return allow_empty
    normalized: list[str] = []
    for value in values:
        match value:
            case str(label) if _TAG.fullmatch(label) is not None:
                normalized.append(label)
            case _:
                return False
    return len(normalized) == len(set(normalized))


def _require_tuple(values: _StringLabels, description: str) -> tuple[str, ...]:
    match values:
        case tuple() as immutable_values:
            return immutable_values
        case _:
            raise TypeError(f"{description} must be an immutable tuple")
