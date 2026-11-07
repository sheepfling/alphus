"""Find configured quaternion normalization tuples passed to rotation consumers."""

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
    qualified_call_name,
)
from alphus.gates.review.numerical.quaternions.ast_patterns import (
    is_sum_of_four_squares,
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
from alphus.policy.review import QuaternionNormalizationPolicy
from alphus.support.inventory import matches_path
from alphus.support.source_text import read_python_source

ALPHUS_CHECK: Final = FeatureDefinition(
    selector="manual-quaternion-normalization",
    input_mode="configured-source-scan",
    policy_field="manual_quaternion_normalization",
    policy_model=QuaternionNormalizationPolicy,
    output_shape="findings",
    summary="Reviews configured hand-written quaternion normalization patterns.",
    applies_to=("python", "numerical"),
    domains=(),
    requires_files=True,
)

ALPHUS_MORPHOLOGY: Final = RuleMorphology(
    selector="manual-quaternion-normalization",
    finding_ids=(
        RuleTag(
            Scope.PYTHON,
            Framework.NONE,
            Category.MAINTAINABILITY,
            "manual-quaternion-normalization",
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
    "manual-quaternion-normalization",
)


@dataclass(frozen=True, slots=True)
class _NormalizationSite:
    function: str
    norm_line: int
    components_line: int
    consumer_line: int


def _is_division(node: ast.expr, component: str, norm: str) -> bool:
    match node:
        case ast.BinOp(
            left=ast.Name(id=actual_component),
            op=ast.Div(),
            right=ast.Name(id=actual_norm),
        ):
            return actual_component == component and actual_norm == norm
        case _:
            return False


def _function_arguments(function: ast.FunctionDef) -> tuple[str, ...]:
    arguments = function.args
    if arguments.defaults or arguments.kw_defaults:
        return ()
    if arguments.vararg is not None or arguments.kwarg is not None:
        return ()
    names = (*arguments.posonlyargs, *arguments.args)
    if arguments.kwonlyargs:
        return ()
    return tuple(argument.arg for argument in names)


def _function_statements(function: ast.FunctionDef) -> Sequence[ast.stmt] | None:
    if ast.get_docstring(function, clean=False) is None:
        return function.body
    return function.body[1:]


def _match_function(
    function: ast.FunctionDef, policy: QuaternionNormalizationPolicy
) -> _NormalizationSite | None:
    if (
        function.name not in policy.function_names
        or _function_arguments(function) != policy.components
    ):
        return None
    statements = _function_statements(function)
    if statements is None:
        return None
    match statements:
        case [
            ast.Assign(targets=[ast.Name(id=norm)], value=ast.Call() as norm_call),
            ast.Assign(
                targets=[ast.Name(id=normalized)],
                value=ast.Tuple(elts=normalized_components),
            ) as normalized_assignment,
            ast.Return(
                value=ast.Call(
                    func=consumer,
                    args=[ast.Name(id=consumer_input)],
                    keywords=[],
                )
            ) as consumer_return,
        ]:
            pass
        case _:
            return None
    if (
        norm == normalized
        or norm in policy.components
        or normalized in policy.components
        or consumer_input != normalized
        or qualified_call_name(norm_call.func) not in policy.square_root_helpers
        or qualified_call_name(consumer) not in policy.rotation_consumer_helpers
        or len(normalized_components) != 4
    ):
        return None
    argument = norm_call.args
    if len(argument) != 1 or norm_call.keywords:
        return None
    if not is_sum_of_four_squares(argument[0], policy.components):
        return None
    if not all(
        _is_division(value, component, norm)
        for value, component in zip(
            normalized_components, policy.components, strict=True
        )
    ):
        return None
    return _NormalizationSite(
        function.name,
        norm_call.lineno,
        normalized_assignment.lineno,
        consumer_return.lineno,
    )


def quaternion_normalization_sites(
    source: str, policy: QuaternionNormalizationPolicy
) -> list[_NormalizationSite]:
    """Return only configured local norm/divide/rotation-consumer sequences."""
    return configured_function_observations(
        source,
        policy.function_names,
        lambda function: _match_function(function, policy),
        lambda site: (site.function, site.norm_line),
    )


def check_manual_quaternion_normalization(
    root: Path,
    paths: Iterable[Path],
    policy: QuaternionNormalizationPolicy,
) -> list[Finding]:
    """Report exact configured normalization sequences for maintainer review."""
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
        for site in quaternion_normalization_sites(read_python_source(path), policy):
            findings.append(
                Finding(
                    rule_id=_RULE_ID,
                    path=name,
                    message=(
                        f"Configured function {site.function!r} computes a norm "
                        f"(line {site.norm_line}), divides all four configured "
                        f"components by it (line {site.components_line}), and passes "
                        f"the tuple to a configured rotation consumer (line "
                        f"{site.consumer_line}). Review whether the existing "
                        "quaternion abstraction fits. This syntax does not establish "
                        "a defect or performance gain; preserve unit, zero and "
                        "near-zero, finite-value, dtype, ordering and failure "
                        "contracts."
                    ),
                    line=site.norm_line,
                    severity=policy.severity,
                )
            )
    return findings


def _run_builtin_manual_quaternion_normalization(
    root: Path,
    files: Sequence[Path],
    config: QualityGateConfig,
) -> list[Finding]:
    policy = require_policy(
        config.checks.manual_quaternion_normalization, "manual_quaternion_normalization"
    )
    return check_manual_quaternion_normalization(root, files, policy)


ALPHUS_FEATURE: Final = BuiltinFeature(
    definition=ALPHUS_CHECK,
    morphology=ALPHUS_MORPHOLOGY,
    runner=_run_builtin_manual_quaternion_normalization,
)
