"""Language-neutral matching of normalized arithmetic literals against catalogs."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Literal, TypeAlias

from alphus.config import NumericLiteralSpec
from alphus.contracts.rule_tags import Category, Framework, RuleTag, Scope, rule_tag

NumericComplaintEmitter: TypeAlias = Literal[
    "numeric-literals", "scipy-constants", "numeric-cpp-adapter"
]
NumericComplaintContractName: TypeAlias = Literal[
    "numeric-inline", "numeric-inline-cpp-adapter"
]
_NumericComplaintEntry: TypeAlias = tuple[NumericComplaintEmitter, str]
_NumericComplaintContract: TypeAlias = tuple[
    str, tuple[NumericComplaintEmitter, ...], tuple[_NumericComplaintEntry, ...]
]

# One static source for the tags emitted by the shared numeric matcher and
# referenced by both owning checks' morphology declarations.
ALPHUS_COMPLAINT_CONTRACTS: Final[tuple[_NumericComplaintContract, ...]] = (
    (
        "numeric-inline",
        ("numeric-literals", "scipy-constants"),
        (
            (
                "numeric-literals",
                rule_tag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.STYLE,
                    "inline-constant",
                ),
            ),
            (
                "numeric-literals",
                rule_tag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.STYLE,
                    "inline-conversion",
                ),
            ),
            (
                "scipy-constants",
                rule_tag(
                    Scope.PYTHON,
                    Framework.SCIPY,
                    Category.STYLE,
                    "inline-constant",
                ),
            ),
            (
                "scipy-constants",
                rule_tag(
                    Scope.PYTHON,
                    Framework.SCIPY,
                    Category.STYLE,
                    "inline-conversion",
                ),
            ),
        ),
    ),
    (
        "numeric-inline-cpp-adapter",
        ("numeric-cpp-adapter",),
        (
            (
                "numeric-cpp-adapter",
                rule_tag(
                    Scope.CPP,
                    Framework.NONE,
                    Category.STYLE,
                    "inline-constant",
                ),
            ),
            (
                "numeric-cpp-adapter",
                rule_tag(
                    Scope.CPP,
                    Framework.NONE,
                    Category.STYLE,
                    "inline-conversion",
                ),
            ),
        ),
    ),
)


def _numeric_rule_tag(
    contract_id: NumericComplaintContractName,
    emitter: NumericComplaintEmitter,
    scope: Scope,
    framework: Framework,
    complaint: str,
) -> RuleTag:
    for contract_name, emitters, tags in ALPHUS_COMPLAINT_CONTRACTS:
        if contract_name != contract_id or emitter not in emitters:
            continue
        for tag_emitter, rule_id in tags:
            if tag_emitter != emitter:
                continue
            tag = RuleTag.parse(rule_id)
            if tag.complaint == complaint:
                if tag.scope != scope or tag.framework != framework:
                    raise ValueError(
                        f"{contract_name} does not permit {scope}/{framework} "
                        f"for emitter {emitter} complaint {complaint!r}"
                    )
                return tag
    raise ValueError(
        f"no complaint contract resolves {emitter} complaint {complaint!r}"
    )


class NumericOperation(StrEnum):
    ADD = "add"
    SUBTRACT = "subtract"
    MULTIPLY = "multiply"
    DIVIDE = "divide"
    FLOOR_DIVIDE = "floor_divide"
    MODULO = "modulo"
    POWER = "power"
    BITWISE_AND = "bitwise_and"
    BITWISE_OR = "bitwise_or"
    BITWISE_XOR = "bitwise_xor"
    LEFT_SHIFT = "left_shift"
    RIGHT_SHIFT = "right_shift"
    MATRIX_MULTIPLY = "matrix_multiply"


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
    complaint_contract: NumericComplaintContractName,
    emitter: NumericComplaintEmitter,
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
                    rule_id=_numeric_rule_tag(
                        complaint_contract,
                        emitter,
                        scope,
                        framework,
                        f"inline-{spec.kind}",
                    ).rule_id,
                    message=(
                        f"possible inline {spec.name} {spec.kind} literal {use.value!r}; "
                        f"review use of {spec.replacement}"
                    ),
                )
            )
    return sorted(findings)
