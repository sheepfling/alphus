"""Recognize one configured scalar-first quaternion rotation matrix formula."""

from __future__ import annotations

import ast
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
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
from alphus.gates.review.numerical.common.ast_helpers import (
    configured_function_observations,
    redefined_function_names,
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
from alphus.policy.review import QuaternionMatrixConversionPolicy
from alphus.support.inventory import matches_path
from alphus.support.source_text import read_python_source

ALPHUS_CHECK: Final = FeatureDefinition(
    selector="manual-quaternion-matrix-conversion",
    input_mode="configured-source-scan",
    policy_field="manual_quaternion_matrix_conversion",
    policy_model=QuaternionMatrixConversionPolicy,
    output_shape="findings",
    summary="Reviews configured quaternion-to-matrix conversions.",
    applies_to=("python",),
    domains=("numerical",),
    requires_files=True,
)

ALPHUS_MORPHOLOGY: Final = RuleMorphology(
    selector="manual-quaternion-matrix-conversion",
    finding_ids=(
        RuleTag(
            Scope.PYTHON,
            Framework.NONE,
            Category.MAINTAINABILITY,
            "manual-quaternion-matrix-conversion",
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
    "manual-quaternion-matrix-conversion",
)


@dataclass(frozen=True, slots=True)
class _MatrixSite:
    function: str
    line: int


def _expected_matrix(components: tuple[str, str, str, str]) -> ast.expr:
    scalar, x, y, z = components
    first_row = (
        f"1 - 2 * ({y} * {y} + {z} * {z}), "
        f"2 * ({x} * {y} - {z} * {scalar}), "
        f"2 * ({x} * {z} + {y} * {scalar})"
    )
    second_row = (
        f"2 * ({x} * {y} + {z} * {scalar}), "
        f"1 - 2 * ({x} * {x} + {z} * {z}), "
        f"2 * ({y} * {z} - {x} * {scalar})"
    )
    third_row = (
        f"2 * ({x} * {z} - {y} * {scalar}), "
        f"2 * ({y} * {z} + {x} * {scalar}), "
        f"1 - 2 * ({x} * {x} + {y} * {y})"
    )
    expression = f"[[{first_row}], [{second_row}], [{third_row}]]"
    return ast.parse(expression, mode="eval").body


def _matrix_rows(node: ast.expr) -> tuple[tuple[ast.expr, ...], ...] | None:
    match node:
        case ast.List(elts=rows) | ast.Tuple(elts=rows) if len(rows) == 3:
            result: list[tuple[ast.expr, ...]] = []
            for row in rows:
                match row:
                    case ast.List(elts=elements) | ast.Tuple(elts=elements) if (
                        len(elements) == 3
                    ):
                        result.append(tuple(elements))
                    case _:
                        return None
            return tuple(result)
        case _:
            return None


def _same_formula(actual: ast.expr, expected: ast.expr) -> bool:
    actual_rows = _matrix_rows(actual)
    expected_rows = _matrix_rows(expected)
    if actual_rows is None or expected_rows is None:
        return False
    return all(
        ast.dump(actual_value, include_attributes=False)
        == ast.dump(expected_value, include_attributes=False)
        for actual_row, expected_row in zip(actual_rows, expected_rows, strict=True)
        for actual_value, expected_value in zip(actual_row, expected_row, strict=True)
    )


def _match(
    function: ast.FunctionDef, policy: QuaternionMatrixConversionPolicy
) -> _MatrixSite | None:
    if function.name not in policy.function_names:
        return None
    arguments = (*function.args.posonlyargs, *function.args.args)
    if (
        tuple(argument.arg for argument in arguments) != policy.components
        or function.args.defaults
        or function.args.kwonlyargs
        or function.args.vararg
        or function.args.kwarg
    ):
        return None
    body = function.body[1:] if ast.get_docstring(function) else function.body
    if len(body) != 1 or not isinstance(body[0], ast.Return) or body[0].value is None:
        return None
    expected = _expected_matrix(policy.components)
    if not _same_formula(body[0].value, expected):
        return None
    return _MatrixSite(function.name, body[0].lineno)


def quaternion_matrix_conversion_sites(
    source: str, policy: QuaternionMatrixConversionPolicy
) -> list[_MatrixSite]:
    """Return exact configured active-column, scalar-first formula matches."""
    shadowed = redefined_function_names(source, policy.function_names)
    return configured_function_observations(
        source,
        policy.function_names,
        lambda function: (
            None if function.name in shadowed else _match(function, policy)
        ),
        lambda site: (site.function, site.line),
    )


def check_manual_quaternion_matrix_conversion(
    root: Path,
    paths: Iterable[Path],
    policy: QuaternionMatrixConversionPolicy,
) -> list[Finding]:
    """Report configured matrix formulas as convention-sensitive candidates."""
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
        for site in quaternion_matrix_conversion_sites(
            read_python_source(path), policy
        ):
            findings.append(
                Finding(
                    rule_id=_RULE_ID,
                    path=name,
                    line=site.line,
                    message=(
                        f"Configured function {site.function!r} returns the exact "
                        "scalar-first active column-vector quaternion rotation matrix. "
                        "Review whether an existing rotation conversion fits. This "
                        "syntax does not establish a defect or performance gain; verify "
                        "handedness, active/passive convention, vector orientation, "
                        "normalization, dtype, failure behavior, and output shape."
                    ),
                    severity=policy.severity,
                )
            )
    return findings


def _run_builtin_manual_quaternion_matrix_conversion(
    root: Path,
    files: Sequence[Path],
    config: QualityGateConfig,
) -> list[Finding]:
    policy = require_policy(
        config.checks.manual_quaternion_matrix_conversion,
        "manual_quaternion_matrix_conversion",
    )
    return check_manual_quaternion_matrix_conversion(root, files, policy)


ALPHUS_FEATURE: Final = BuiltinFeature(
    definition=ALPHUS_CHECK,
    morphology=ALPHUS_MORPHOLOGY,
    runner=_run_builtin_manual_quaternion_matrix_conversion,
)
