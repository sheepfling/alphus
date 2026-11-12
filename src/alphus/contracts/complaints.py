"""Named immutable contracts for stable finding identities and emitters."""

from __future__ import annotations

import re
from dataclasses import dataclass

from alphus.contracts.rule_tags import RuleTag

_SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")


@dataclass(frozen=True, slots=True)
class ComplaintEntry:
    """One stable RuleTag emitted under a feature selector."""

    emitter: str
    tag: RuleTag

    def __post_init__(self) -> None:
        if _SLUG.fullmatch(self.emitter) is None:
            raise ValueError("complaint entry emitters must be lowercase slugs")


@dataclass(frozen=True, slots=True)
class ComplaintContract:
    """Named finding contract shared by one or more feature providers."""

    name: str
    emitters: tuple[str, ...]
    entries: tuple[ComplaintEntry, ...]

    def __post_init__(self) -> None:
        if _SLUG.fullmatch(self.name) is None:
            raise ValueError("complaint contract names must be lowercase slugs")
        match (self.emitters, self.entries):
            case (tuple(), tuple()):
                pass
            case _:
                raise TypeError(
                    "complaint contract collections must be immutable tuples"
                )
        if not self.emitters or not self.entries:
            raise ValueError("complaint contracts need emitters and entries")
        if len(self.emitters) != len(set(self.emitters)):
            raise ValueError("complaint contract emitters must be unique")
        if any(_SLUG.fullmatch(emitter) is None for emitter in self.emitters):
            raise ValueError("complaint contract emitters must be lowercase slugs")
        for entry in self.entries:
            match entry:
                case ComplaintEntry():
                    pass
                case _:
                    raise TypeError(
                        "complaint contract entries must be ComplaintEntry records"
                    )
        if any(entry.emitter not in self.emitters for entry in self.entries):
            raise ValueError("complaint entry emitter must belong to its contract")
        if {entry.emitter for entry in self.entries} != set(self.emitters):
            raise ValueError("every complaint contract emitter needs a RuleTag")
        if len({(entry.emitter, entry.tag) for entry in self.entries}) != len(
            self.entries
        ):
            raise ValueError("complaint contract entries must be unique")
