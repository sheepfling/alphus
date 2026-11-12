"""Typed complaint-level extensions owned by one built-in feature."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Generic, Protocol, TypeVar

from alphus.contracts.findings import Finding
from alphus.policy.base import StrictModel
from alphus.policy.morphology import RuleMorphology

_Policy = TypeVar("_Policy", bound=StrictModel)
_Policy_contra = TypeVar("_Policy_contra", bound=StrictModel, contravariant=True)
_SELECTOR = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*\Z")
_POLICY_FIELD = re.compile(r"[a-z][a-z0-9_]*\Z")


def _is_strict_model(value: object) -> bool:
    match value:
        case type() as model:
            try:
                return issubclass(model, StrictModel)
            except TypeError:
                return False
        case _:
            return False


class ComplaintRunner(Protocol[_Policy_contra]):
    """Run one complaint contribution using its own strict policy fragment."""

    def __call__(
        self, root: Path, files: Sequence[Path], policy: _Policy_contra, /
    ) -> list[Finding]: ...


class ComplaintContributionRecord:
    """Non-generic runtime identity for a typed complaint contribution."""

    __slots__ = ()


@dataclass(frozen=True, slots=True)
class ComplaintContributionDefinition(Generic[_Policy]):
    """Metadata for one complaint contribution to an existing selector."""

    selector: str
    policy_field: str
    policy_model: type[_Policy]
    morphology: RuleMorphology
    summary: str

    def __post_init__(self) -> None:
        if _SELECTOR.fullmatch(self.selector) is None:
            raise ValueError("complaint contribution selector must be a lowercase slug")
        if _POLICY_FIELD.fullmatch(self.policy_field) is None:
            raise ValueError(
                "complaint contribution policy field must be an identifier"
            )
        if self.morphology.selector != self.selector:
            raise ValueError("complaint contribution selector and morphology differ")
        if not _is_strict_model(self.policy_model):
            raise TypeError("complaint contribution policy must extend StrictModel")
        if not self.summary.strip():
            raise ValueError("complaint contributions need a summary")


@dataclass(frozen=True, slots=True)
class ComplaintContribution(ComplaintContributionRecord, Generic[_Policy]):
    """A feature-owned typed provider declared through a wheel entry point."""

    definition: ComplaintContributionDefinition[_Policy]
    runner: ComplaintRunner[_Policy]

    def __post_init__(self) -> None:
        if not callable(self.runner):
            raise TypeError("complaint contribution runner must be callable")


__all__ = [
    "ComplaintContribution",
    "ComplaintContributionDefinition",
    "ComplaintContributionRecord",
    "ComplaintRunner",
]
