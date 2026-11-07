"""Find configured quaternion inverses expressed as conjugate over squared norm."""

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
from alphus.policy.review import QuaternionInversionPolicy
from alphus.support.inventory import matches_path
from alphus.support.source_text import read_python_source

ALPHUS_CHECK: Final = FeatureDefinition(
    selector="manual-quaternion-inversion",
    input_mode="configured-source-scan",
    policy_field="manual_quaternion_inversion",
    policy_model=QuaternionInversionPolicy,
    output_shape="findings",
    summary="Reviews configured hand-written quaternion inversion patterns.",
    applies_to=("python",),
    domains=("numerical",),
    requires_files=True,
)

ALPHUS_MORPHOLOGY: Final = RuleMorphology(
    selector="manual-quaternion-inversion",
    finding_ids=(
        RuleTag(
            Scope.PYTHON,
            Framework.NONE,
            Category.MAINTAINABILITY,
            "manual-quaternion-inversion",
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
    "manual-quaternion-inversion",
)


@dataclass(frozen=True, slots=True)
class _InversionSite:
    function: str
    norm_line: int
    return_line: int


def _arguments(function: ast.FunctionDef) -> tuple[str, ...]:
    arguments = function.args
    if (
        arguments.defaults
        or arguments.kw_defaults
        or arguments.vararg is not None
        or arguments.kwarg is not None
        or arguments.kwonlyargs
    ):
        return ()
    return tuple(argument.arg for argument in (*arguments.posonlyargs, *arguments.args))


def _statements(function: ast.FunctionDef) -> Sequence[ast.stmt]:
    if ast.get_docstring(function, clean=False) is not None:
        return function.body[1:]
    return function.body


def _inverse_component(
    node: ast.expr, component: str, norm: str, *, negated: bool
) -> bool:
    match node:
        case ast.BinOp(
            left=ast.Name(id=actual), op=ast.Div(), right=ast.Name(id=denominator)
        ):
            return not negated and component == actual and norm == denominator
        case ast.BinOp(
            left=ast.UnaryOp(op=ast.USub(), operand=ast.Name(id=actual)),
            op=ast.Div(),
            right=ast.Name(id=denominator),
        ):
            return negated and actual == component and denominator == norm
        case _:
            return False


def _match_function(
    function: ast.FunctionDef, policy: QuaternionInversionPolicy
) -> _InversionSite | None:
    if (
        function.name not in policy.function_names
        or _arguments(function) != policy.components
    ):
        return None
    match _statements(function):
        case [
            ast.Assign(
                targets=[ast.Name(id=norm)],
                value=norm_expression,
            ) as norm_assignment,
            ast.Return(value=ast.Tuple(elts=returned)) as inverse_return,
        ] if len(returned) == 4:
            pass
        case _:
            return None
    if norm in policy.components:
        return None
    if not is_sum_of_four_squares(norm_expression, policy.components):
        return None
    if not all(
        _inverse_component(value, component, norm, negated=index > 0)
        for index, (value, component) in enumerate(
            zip(returned, policy.components, strict=True)
        )
    ):
        return None
    return _InversionSite(function.name, norm_assignment.lineno, inverse_return.lineno)


def quaternion_inversion_sites(
    source: str, policy: QuaternionInversionPolicy
) -> list[_InversionSite]:
    """Return exact inverse shapes unless same-scope redefinition makes them dead."""
    shadowed = redefined_function_names(source, policy.function_names)
    return configured_function_observations(
        source,
        policy.function_names,
        lambda function: (
            None if function.name in shadowed else _match_function(function, policy)
        ),
        lambda site: (site.function, site.norm_line),
    )


def check_manual_quaternion_inversion(
    root: Path,
    paths: Iterable[Path],
    policy: QuaternionInversionPolicy,
) -> list[Finding]:
    """Report exact configured inverse kernels for review without rewriting."""
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
        for site in quaternion_inversion_sites(read_python_source(path), policy):
            findings.append(
                Finding(
                    rule_id=_RULE_ID,
                    path=name,
                    line=site.norm_line,
                    message=(
                        f"Configured function {site.function!r} computes a sum of "
                        f"the four component squares (line {site.norm_line}) and "
                        f"returns the conjugated components over that value (line "
                        f"{site.return_line}). Review whether an existing quaternion "
                        "abstraction fits. This syntax does not establish a defect "
                        "or performance gain; preserve non-unit inverse semantics, "
                        "zero and non-finite behavior, component order, dtype and "
                        "failure contracts."
                    ),
                    severity=policy.severity,
                )
            )
    return findings


def _run_builtin_manual_quaternion_inversion(
    root: Path,
    files: Sequence[Path],
    config: QualityGateConfig,
) -> list[Finding]:
    policy = require_policy(
        config.checks.manual_quaternion_inversion, "manual_quaternion_inversion"
    )
    return check_manual_quaternion_inversion(root, files, policy)


ALPHUS_FEATURE: Final = BuiltinFeature(
    definition=ALPHUS_CHECK,
    morphology=ALPHUS_MORPHOLOGY,
    runner=_run_builtin_manual_quaternion_inversion,
)
