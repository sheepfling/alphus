"""Recognize one configured ECEF displacement-vector to ENU formula."""

from __future__ import annotations

import ast
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from alphus.config import QualityGateConfig
from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import Category, Framework, RuleTag, Scope, rule_tag
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
from alphus.policy.review import EcefEnuTransformPolicy
from alphus.support.inventory import matches_path
from alphus.support.source_text import read_python_source

ALPHUS_CHECK: Final = FeatureDefinition(
    selector="ecef-enu-transform",
    input_mode="configured-source-scan",
    policy_field="ecef_enu_transform",
    policy_model=EcefEnuTransformPolicy,
    output_shape="findings",
    summary="Reviews configured ECEF-to-ENU transform patterns.",
    applies_to=("python", "geospatial"),
    domains=(),
    requires_files=True,
)

ALPHUS_MORPHOLOGY: Final = RuleMorphology(
    selector="ecef-enu-transform",
    finding_ids=(
        RuleTag(
            Scope.PYTHON,
            Framework.NONE,
            Category.MAINTAINABILITY,
            "ecef-enu-transform-reuse",
        ),
    ),
    concern="coordinate-frame-transform-implementation",
    claim_kind=ClaimKind.RISK,
    claim=(
        "A configured Python function matches the exact bounded ECEF-to-ENU "
        "formula; this is a review signal, not proof of mathematical error."
    ),
    mechanisms=(DetectionMechanism.BOUNDED_HEURISTIC,),
    inspected_scope=("configured-python-files", "configured-functions"),
    languages_formats=("python",),
    evidence_kinds=("configured-source-path", "ast-pattern-match", "source-location"),
    evaluation_maturity=EvaluationMaturity.SYNTHETIC_ONLY,
)

_RULE_ID = rule_tag(
    Scope.PYTHON,
    Framework.NONE,
    Category.MAINTAINABILITY,
    "ecef-enu-transform-reuse",
)


@dataclass(frozen=True, slots=True)
class _TransformSite:
    function: str
    line: int


def _expected(policy: EcefEnuTransformPolicy) -> ast.Tuple:
    dx, dy, dz = policy.components
    lat, lon = policy.latitude_name, policy.longitude_name
    m = policy.math_module
    expression = (
        f"(-{m}.sin({lon}) * {dx} + {m}.cos({lon}) * {dy}, "
        f"-{m}.sin({lat}) * {m}.cos({lon}) * {dx} "
        f"- {m}.sin({lat}) * {m}.sin({lon}) * {dy} "
        f"+ {m}.cos({lat}) * {dz}, "
        f"{m}.cos({lat}) * {m}.cos({lon}) * {dx} "
        f"+ {m}.cos({lat}) * {m}.sin({lon}) * {dy} "
        f"+ {m}.sin({lat}) * {dz})"
    )
    node = ast.parse(expression, mode="eval").body
    assert isinstance(node, ast.Tuple)
    return node


def _has_module_import(tree: ast.Module, module: str) -> bool:
    return any(
        isinstance(statement, ast.Import)
        and any(
            alias.name == module and (alias.asname or alias.name) == module
            for alias in statement.names
        )
        for statement in tree.body
    )


def _shadowed_math(function: ast.FunctionDef, module: ast.Module, name: str) -> bool:
    if any(
        isinstance(child, ast.Name)
        and isinstance(child.ctx, ast.Store)
        and child.id == name
        for child in ast.walk(module)
    ):
        return True
    if any(
        isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and statement.name == name
        for statement in module.body
    ):
        return True
    if any(
        argument.arg == name
        for argument in (
            *function.args.posonlyargs,
            *function.args.args,
            *function.args.kwonlyargs,
        )
    ):
        return True
    if any(
        isinstance(child, ast.Import)
        and any(
            (alias.asname or alias.name.split(".")[0]) == name for alias in child.names
        )
        for statement in function.body
        for child in ast.walk(statement)
    ):
        return True
    return any(
        isinstance(child, ast.Name)
        and isinstance(child.ctx, ast.Store)
        and child.id == name
        for statement in function.body
        for child in ast.walk(statement)
    )


def _match(
    function: ast.FunctionDef, policy: EcefEnuTransformPolicy
) -> _TransformSite | None:
    if function.name not in policy.function_names:
        return None
    expected_args = (*policy.components, policy.latitude_name, policy.longitude_name)
    arguments = (*function.args.posonlyargs, *function.args.args)
    if (
        tuple(arg.arg for arg in arguments) != expected_args
        or function.args.defaults
        or function.args.kwonlyargs
        or function.args.vararg
        or function.args.kwarg
    ):
        return None
    body = function.body[1:] if ast.get_docstring(function) else function.body
    if len(body) != 1 or not isinstance(body[0], ast.Return) or body[0].value is None:
        return None
    if ast.dump(body[0].value, include_attributes=False) != ast.dump(
        _expected(policy), include_attributes=False
    ):
        return None
    return _TransformSite(function.name, body[0].lineno)


def ecef_enu_transform_sites(
    source: str, policy: EcefEnuTransformPolicy
) -> list[_TransformSite]:
    """Return exact direct-formula matches with a module-bound math import."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    if not _has_module_import(tree, policy.math_module):
        return []
    if any(
        _shadowed_math(node, tree, policy.math_module)
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name in policy.function_names
    ):
        return []
    if redefined_function_names(source, policy.function_names):
        return []
    return configured_function_observations(
        source,
        policy.function_names,
        lambda function: _match(function, policy),
        lambda site: (site.function, site.line),
    )


def check_ecef_enu_transform(
    root: Path, paths: Iterable[Path], policy: EcefEnuTransformPolicy
) -> list[Finding]:
    """Report the exact configured local-frame candidate as advisory evidence."""
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
        source = read_python_source(path)
        for site in ecef_enu_transform_sites(source, policy):
            findings.append(
                Finding(
                    rule_id=_RULE_ID,
                    path=name,
                    line=site.line,
                    message=(
                        f"Configured function {site.function!r} matches a direct "
                        "ECEF displacement-vector to right-handed ENU transform "
                        f"({policy.latitude_type} latitude, radians, meters, "
                        f"east/north/up tuple3 at the configured {policy.origin} "
                        f"using reference ellipsoid {policy.reference_ellipsoid}). "
                        "Review reuse via configured helper(s) "
                        f"{', '.join(policy.preferred_helpers)}. This exact syntax "
                        "does not establish equivalence: verify origin/datum, latitude "
                        "and angular conventions, dtype, batching, shape, and failure "
                        "behavior before considering a change; no speedup is inferred."
                    ),
                    severity=policy.severity,
                )
            )
    return findings


def _run_builtin_ecef_enu_transform(
    root: Path,
    files: Sequence[Path],
    config: QualityGateConfig,
) -> list[Finding]:
    policy = require_policy(config.checks.ecef_enu_transform, "ecef_enu_transform")
    return check_ecef_enu_transform(root, files, policy)


ALPHUS_FEATURE: Final = BuiltinFeature(
    definition=ALPHUS_CHECK,
    morphology=ALPHUS_MORPHOLOGY,
    runner=_run_builtin_ecef_enu_transform,
)
