"""Find one configured quaternion/pure-vector/conjugate sandwich expression."""

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
from alphus.plugins.builtin import BuiltinFeature
from alphus.policy.base import require_policy
from alphus.policy.feature_definition import FeatureDefinition
from alphus.policy.morphology import (
    ClaimKind,
    DetectionMechanism,
    EvaluationMaturity,
    RuleMorphology,
)
from alphus.policy.review import QuaternionVectorRotationPolicy
from alphus.support.inventory import matches_path
from alphus.support.source_text import read_python_source

ALPHUS_CHECK: Final = FeatureDefinition(
    selector="manual-quaternion-vector-rotation",
    input_mode="configured-source-scan",
    policy_field="manual_quaternion_vector_rotation",
    policy_model=QuaternionVectorRotationPolicy,
    output_shape="findings",
    summary="Reviews configured hand-written quaternion vector rotations.",
    applies_to=("python",),
    domains=("numerical",),
    requires_files=True,
)

ALPHUS_MORPHOLOGY: Final = RuleMorphology(
    selector="manual-quaternion-vector-rotation",
    finding_ids=(
        RuleTag(
            Scope.PYTHON,
            Framework.NONE,
            Category.MAINTAINABILITY,
            "manual-quaternion-vector-rotation",
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
    "manual-quaternion-vector-rotation",
)


@dataclass(frozen=True, slots=True)
class _RotationSite:
    function: str
    line: int


def _component_tuple(node: ast.expr, names: tuple[str, ...]) -> bool:
    return (
        isinstance(node, ast.Tuple)
        and len(node.elts) == len(names)
        and all(
            isinstance(element, ast.Name) and element.id == name
            for element, name in zip(node.elts, names, strict=True)
        )
    )


def _pure_vector_tuple(node: ast.expr, names: tuple[str, str, str]) -> bool:
    if not isinstance(node, ast.Tuple) or len(node.elts) != 4:
        return False
    scalar, *vector = node.elts
    return (
        isinstance(scalar, ast.Constant)
        and type(scalar.value) is int
        and scalar.value == 0
        and all(
            isinstance(element, ast.Name) and element.id == name
            for element, name in zip(vector, names, strict=True)
        )
    )


def _match(
    function: ast.FunctionDef, policy: QuaternionVectorRotationPolicy
) -> _RotationSite | None:
    if function.name not in policy.function_names:
        return None
    arguments = (*function.args.posonlyargs, *function.args.args)
    expected_names = (*policy.components, *policy.vector_components)
    if (
        tuple(argument.arg for argument in arguments) != expected_names
        or function.args.defaults
        or function.args.kwonlyargs
        or function.args.vararg
        or function.args.kwarg
    ):
        return None
    body = function.body[1:] if ast.get_docstring(function) else function.body
    if len(body) != 1 or not isinstance(body[0], ast.Return):
        return None
    returned = body[0].value
    if (
        not isinstance(returned, ast.Call)
        or len(returned.args) != 2
        or returned.keywords
    ):
        return None
    inner, conjugated = returned.args
    if not isinstance(inner, ast.Call) or len(inner.args) != 2 or inner.keywords:
        return None
    inner_quaternion, pure_vector = inner.args
    if (
        not _component_tuple(inner_quaternion, policy.components)
        or not _pure_vector_tuple(pure_vector, policy.vector_components)
        or not _component_tuple_call(
            conjugated, policy.conjugation_helpers, policy.components
        )
    ):
        return None
    inner_helper = qualified_call_name(inner.func)
    if inner_helper not in policy.multiplication_helpers:
        return None
    if qualified_call_name(returned.func) != inner_helper:
        return None
    return _RotationSite(function.name, body[0].lineno)


def _component_tuple_call(
    node: ast.expr, helpers: tuple[str, ...], components: tuple[str, ...]
) -> bool:
    return (
        isinstance(node, ast.Call)
        and qualified_call_name(node.func) in helpers
        and len(node.args) == 1
        and not node.keywords
        and _component_tuple(node.args[0], components)
    )


def quaternion_vector_rotation_sites(
    source: str, policy: QuaternionVectorRotationPolicy
) -> list[_RotationSite]:
    """Return only the configured direct q * (0,v) * conjugate(q) call tree."""
    return configured_function_observations(
        source,
        policy.function_names,
        lambda function: _match(function, policy),
        lambda site: (site.function, site.line),
    )


def check_manual_quaternion_vector_rotation(
    root: Path,
    paths: Iterable[Path],
    policy: QuaternionVectorRotationPolicy,
) -> list[Finding]:
    """Report configured sandwich-shaped vector rotation candidates."""
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
        for site in quaternion_vector_rotation_sites(read_python_source(path), policy):
            findings.append(
                Finding(
                    rule_id=_RULE_ID,
                    path=name,
                    line=site.line,
                    message=(
                        f"Configured function {site.function!r} returns a configured "
                        "multiplication sandwich of a quaternion, pure-vector tuple, "
                        "and quaternion conjugate. Review whether an existing vector "
                        "rotation helper fits. This syntax alone does not establish a "
                        "defect or performance gain; conjugation matches inverse only "
                        "for unit quaternions, and convention, normalization, dtype, "
                        "failure behavior, and output shape remain consumer contracts."
                    ),
                    severity=policy.severity,
                )
            )
    return findings


def _run_builtin_manual_quaternion_vector_rotation(
    root: Path,
    files: Sequence[Path],
    config: QualityGateConfig,
) -> list[Finding]:
    policy = require_policy(
        config.checks.manual_quaternion_vector_rotation,
        "manual_quaternion_vector_rotation",
    )
    return check_manual_quaternion_vector_rotation(root, files, policy)


ALPHUS_FEATURE: Final = BuiltinFeature(
    definition=ALPHUS_CHECK,
    morphology=ALPHUS_MORPHOLOGY,
    runner=_run_builtin_manual_quaternion_vector_rotation,
)
