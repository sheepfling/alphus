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


class NumericContext(StrEnum):
    """Syntax context normalized by a source-language frontend."""

    ARITHMETIC = "arithmetic"
    CALL_ARGUMENT = "call-argument"


# TODO add other ops like the bianry ops and shifts and also @ for matmul
# we should probably add extras like elementwise or other ops that are endemic to octave + matlab


@dataclass(frozen=True, slots=True)
class NumericCatalog:
    """A value realm, its diagnostic attribution, provenance, and entries."""

    realm: str
    framework: Framework
    provenance: str | None
    specs: tuple[NumericLiteralSpec, ...]


@dataclass(frozen=True, slots=True)
class NumericOccurrence:
    """A numeric literal and its normalized source-language context."""

    line: int
    value: NumericValue
    context: NumericContext
    operation: NumericOperation | None
    tokens: frozenset[str]
    callee: str | None = None
    argument: str | None = None
    call_arguments: tuple[tuple[str, NumericValue], ...] = ()


@dataclass(frozen=True, order=True, slots=True)
class NumericLiteralFinding:
    """An exact source location and stable category before adding a file path."""

    line: int
    rule_id: str
    message: str


def match_numeric_occurrences(
    occurrences: Sequence[NumericOccurrence],
    catalog: NumericCatalog,
    *,
    scope: Scope,
) -> list[NumericLiteralFinding]:
    """Match normalized source observations against one named value realm."""
    findings: set[NumericLiteralFinding] = set()
    for occurrence in occurrences:
        for spec in catalog.specs:
            if occurrence.value not in spec.values:
                continue
            if spec.context == "arithmetic":
                if occurrence.context != NumericContext.ARITHMETIC:
                    continue
                if spec.name_tokens and not occurrence.tokens.intersection(
                    token.casefold() for token in spec.name_tokens
                ):
                    continue
            else:
                if occurrence.context != NumericContext.CALL_ARGUMENT:
                    continue
                if occurrence.callee not in spec.call_names:
                    continue
                if occurrence.argument not in spec.argument_names:
                    continue
                if any(
                    (argument, value) not in occurrence.call_arguments
                    for argument, value in spec.required_call_arguments
                ):
                    continue
            if spec.kind == "conversion" and occurrence.operation not in {
                NumericOperation.MULTIPLY,
                NumericOperation.DIVIDE,
            }:
                continue
            provenance = spec.source or catalog.provenance
            source_note = f"; source: {provenance}" if provenance is not None else ""
            findings.add(
                NumericLiteralFinding(
                    line=occurrence.line,
                    rule_id=rule_tag(
                        scope,
                        catalog.framework,
                        Category.STYLE,
                        f"inline-{spec.kind}",
                    ),
                    message=(
                        f"possible inline {spec.name} {spec.kind} literal "
                        f"{occurrence.value!r}; review use of {spec.replacement}"
                        f"{source_note}"
                    ),
                )
            )
    return sorted(findings)
