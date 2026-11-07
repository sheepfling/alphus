"""Find configured scalar-first Hamilton products in tuple assignments."""

from __future__ import annotations

import ast
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Final

from alphus.config import QualityGateConfig
from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import (
    Category,
    Framework,
    RuleTag,
    Scope,
    rule_tag,
)
from alphus.plugins.builtin import BuiltinFeature
from alphus.policy.base import require_policy
from alphus.policy.feature_definition import FeatureDefinition
from alphus.policy.morphology import (
    ClaimKind,
    DetectionMechanism,
    EvaluationMaturity,
    RuleMorphology,
)
from alphus.policy.review import QuaternionProductPolicy
from alphus.support.inventory import matches_path
from alphus.support.source_text import read_python_source

ALPHUS_CHECK: Final = FeatureDefinition(
    selector="manual-quaternion-products",
    input_mode="configured-source-scan",
    policy_field="manual_quaternion_products",
    policy_model=QuaternionProductPolicy,
    output_shape="findings",
    summary="Reviews configured hand-written quaternion product patterns.",
    applies_to=("python",),
    domains=("numerical",),
    requires_files=True,
)

ALPHUS_MORPHOLOGY: Final = RuleMorphology(
    selector="manual-quaternion-products",
    finding_ids=(
        RuleTag(
            Scope.PYTHON,
            Framework.NONE,
            Category.MAINTAINABILITY,
            "manual-quaternion-kernel",
        ),
    ),
    concern="quaternion-operation-implementation",
    claim_kind=ClaimKind.RISK,
    claim=(
        "The configured Python function matches this operation's bounded syntax "
        "shape; a match is a review signal and does not prove mathematical error."
    ),
    mechanisms=(DetectionMechanism.BOUNDED_HEURISTIC,),
    inspected_scope=("configured-python-files", "configured-functions"),
    languages_formats=("python",),
    evidence_kinds=(
        "configured-source-path",
        "configured-function-name",
        "ast-pattern-match",
        "source-location",
    ),
    evaluation_maturity=EvaluationMaturity.SYNTHETIC_ONLY,
)

_RULE_ID = rule_tag(
    Scope.PYTHON,
    Framework.NONE,
    Category.MAINTAINABILITY,
    "manual-quaternion-kernel",
)
_Term = tuple[tuple[str, str], int]


def _signed_terms(node: ast.expr, sign: int = 1) -> list[_Term] | None:
    match node:
        case ast.BinOp(left=left, op=ast.Add(), right=right):
            left_terms = _signed_terms(left, sign)
            right_terms = _signed_terms(right, sign)
            if left_terms is None or right_terms is None:
                return None
            return [*left_terms, *right_terms]
        case ast.BinOp(left=left, op=ast.Sub(), right=right):
            left_terms = _signed_terms(left, sign)
            right_terms = _signed_terms(right, -sign)
            if left_terms is None or right_terms is None:
                return None
            return [*left_terms, *right_terms]
        case ast.UnaryOp(op=ast.USub(), operand=operand):
            return _signed_terms(operand, -sign)
        case ast.UnaryOp(op=ast.UAdd(), operand=operand):
            return _signed_terms(operand, sign)
        case ast.BinOp(
            left=ast.Name(id=left_name),
            op=ast.Mult(),
            right=ast.Name(id=right_name),
        ):
            factors = (
                (left_name, right_name)
                if left_name <= right_name
                else (right_name, left_name)
            )
            return [(factors, sign)]
        case _:
            return None


def _expected_terms(
    left: tuple[str, str, str, str], right: tuple[str, str, str, str]
) -> tuple[tuple[_Term, ...], ...]:
    w, x, y, z = left
    a, b, c, d = right

    def component(*terms: tuple[str, str, int]) -> tuple[_Term, ...]:
        normalized: list[_Term] = []
        for first, second, sign in terms:
            factors = (first, second) if first <= second else (second, first)
            normalized.append((factors, sign))
        return tuple(sorted(normalized))

    return (
        component((w, a, 1), (x, b, -1), (y, c, -1), (z, d, -1)),
        component((w, b, 1), (x, a, 1), (y, d, 1), (z, c, -1)),
        component((w, c, 1), (x, d, -1), (y, a, 1), (z, b, 1)),
        component((w, d, 1), (x, c, 1), (y, b, -1), (z, a, 1)),
    )


def _tuple_names(node: ast.expr) -> tuple[str, ...] | None:
    match node:
        case ast.Tuple(elts=items) | ast.List(elts=items):
            names: list[str] = []
            for item in items:
                match item:
                    case ast.Name(id=name):
                        names.append(name)
                    case _:
                        return None
            return tuple(names)
        case _:
            return None


def _expression_terms(node: ast.expr) -> tuple[_Term, ...] | None:
    terms = _signed_terms(node)
    return tuple(sorted(terms)) if terms is not None else None


def _matched_assignments(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    policy: QuaternionProductPolicy,
) -> list[int]:
    expected = _expected_terms(policy.left_components, policy.right_components)
    lines: list[int] = []
    for node in ast.walk(function):
        match node:
            case ast.Assign(
                targets=[target], value=ast.Tuple(elts=values) | ast.List(elts=values)
            ):
                output_names = _tuple_names(target)
                if output_names != policy.result_components or len(values) != 4:
                    continue
                actual = tuple(_expression_terms(value) for value in values)
                if actual == expected:
                    lines.append(node.lineno)
            case _:
                continue
    return sorted(set(lines))


def quaternion_product_lines(
    source: str, policy: QuaternionProductPolicy
) -> list[tuple[str, int]]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    results: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        match node:
            case ast.FunctionDef(name=name) | ast.AsyncFunctionDef(name=name) if (
                name in policy.function_names
            ):
                results.extend(
                    (name, line) for line in _matched_assignments(node, policy)
                )
            case _:
                continue
    return sorted(set(results))


def check_manual_quaternion_products(
    root: Path, paths: Iterable[Path], policy: QuaternionProductPolicy
) -> list[Finding]:
    """Report only complete, configured scalar-first Hamilton product tuples."""
    checkout = root.resolve(strict=True)
    findings: list[Finding] = []
    for relative in sorted(paths):
        name = relative.as_posix()
        if (
            relative.suffix != ".py"
            or any(matches_path(name, pattern) for pattern in policy.exclude)
            or not any(matches_path(name, pattern) for pattern in policy.source_paths)
        ):
            continue
        path = checkout / relative
        if not path.is_file():
            continue
        for function, line in quaternion_product_lines(
            read_python_source(path), policy
        ):
            findings.append(
                Finding(
                    _RULE_ID,
                    name,
                    "configured function contains the complete scalar-first "
                    f"Hamilton product tuple ({function}, line {line}); review the "
                    "existing quaternion abstraction and preserve component order, "
                    "multiplication convention, dtype, normalization and failure "
                    "contracts. A match does not establish incorrectness or speed.",
                    line,
                    policy.severity,
                )
            )
    return findings


def _run_builtin_manual_quaternion_products(
    root: Path,
    files: Sequence[Path],
    config: QualityGateConfig,
) -> list[Finding]:
    policy = require_policy(
        config.checks.manual_quaternion_products, "manual_quaternion_products"
    )
    return check_manual_quaternion_products(root, files, policy)


ALPHUS_FEATURE: Final = BuiltinFeature(
    definition=ALPHUS_CHECK,
    morphology=ALPHUS_MORPHOLOGY,
    runner=_run_builtin_manual_quaternion_products,
)
