"""Language-neutral matching for normalized numeric source occurrences."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import TypeAlias

from alphus.config import NumericLiteralSpec
from alphus.contracts.rule_tags import Category, Framework, Scope, rule_tag

NumericValue: TypeAlias = int | float


class NumericOperation(StrEnum):
    """Arithmetic context normalized by a source-language frontend."""

    ADD = "add"
    SUBTRACT = "subtract"
    MULTIPLY = "multiply"
    DIVIDE = "divide"
    FLOOR_DIVIDE = "floor-divide"
    MODULO = "modulo"
    POWER = "power"


# TODO add other ops like the bianry ops and shifts and also @ for matmul
# we should probably add extras like elementwise or other ops that are endemic to octave + matlab


@dataclass(frozen=True, slots=True)
class NumericOccurrence:
    """A numeric literal and its relevant arithmetic context."""

    line: int
    value: NumericValue
    operation: NumericOperation
    tokens: frozenset[str]


@dataclass(frozen=True, order=True, slots=True)
class NumericLiteralFinding:
    """An exact source location and stable category before adding a file path."""

    line: int
    rule_id: str
    message: str


def match_numeric_occurrences(
    occurrences: Sequence[NumericOccurrence],
    specs: tuple[NumericLiteralSpec, ...],
    *,
    framework: Framework,
    scope: Scope,
) -> list[NumericLiteralFinding]:
    """Match language-neutral arithmetic observations against a value catalog."""
    findings: set[NumericLiteralFinding] = set()
    for occurrence in occurrences:
        for spec in specs:
            if occurrence.value not in spec.values:
                continue
            if spec.name_tokens and not occurrence.tokens.intersection(
                token.casefold() for token in spec.name_tokens
            ):
                continue
            if spec.kind == "conversion" and occurrence.operation not in {
                NumericOperation.MULTIPLY,
                NumericOperation.DIVIDE,
            }:
                continue
            findings.add(
                NumericLiteralFinding(
                    line=occurrence.line,
                    rule_id=rule_tag(
                        scope,
                        framework,
                        Category.STYLE,
                        f"inline-{spec.kind}",
                    ),
                    message=(
                        f"possible inline {spec.name} {spec.kind} literal "
                        f"{occurrence.value!r}; review use of {spec.replacement}"
                    ),
                )
            )
    return sorted(findings)
