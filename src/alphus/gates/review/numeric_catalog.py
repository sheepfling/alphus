"""Language-neutral matching of normalized arithmetic literals against catalogs."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum

from alphus.config import NumericLiteralSpec
from alphus.contracts.rule_tags import Category, Framework, Scope, rule_tag


class NumericOperation(StrEnum):
    ADD = "add"
    SUBTRACT = "subtract"
    MULTIPLY = "multiply"
    DIVIDE = "divide"
    FLOOR_DIVIDE = "floor_divide"
    MODULO = "modulo"
    POWER = "power"


@dataclass(frozen=True, slots=True)
class NumericUse:
    """A parser-provided arithmetic literal, independent of source language."""

    value: int | float
    line: int
    operation: NumericOperation
    name_tokens: frozenset[str] = frozenset()


@dataclass(frozen=True, order=True, slots=True)
class NumericLiteralFinding:
    """An exact source location and stable category before adding a file path."""

    line: int
    rule_id: str
    message: str


def match_numeric_uses(
    uses: Iterable[NumericUse],
    specs: Sequence[NumericLiteralSpec],
    *,
    scope: Scope,
    framework: Framework,
) -> list[NumericLiteralFinding]:
    """Match exact values and named context after a language adapter parses source."""
    findings: set[NumericLiteralFinding] = set()
    for use in uses:
        for spec in specs:
            if use.value not in spec.values:
                continue
            if spec.name_tokens and not use.name_tokens.intersection(
                token.casefold() for token in spec.name_tokens
            ):
                continue
            if spec.kind == "conversion" and use.operation not in {
                NumericOperation.MULTIPLY,
                NumericOperation.DIVIDE,
            }:
                continue
            findings.add(
                NumericLiteralFinding(
                    line=use.line,
                    rule_id=rule_tag(
                        scope, framework, Category.STYLE, f"inline-{spec.kind}"
                    ),
                    message=(
                        f"possible inline {spec.name} {spec.kind} literal {use.value!r}; "
                        f"review use of {spec.replacement}"
                    ),
                )
            )
    return sorted(findings)
