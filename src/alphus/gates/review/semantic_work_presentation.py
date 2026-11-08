"""Review consumer-declared semantic operations co-located in presentation code."""

from __future__ import annotations

import ast
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from alphus.config import QualityGateConfig
from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import Category, Framework, RuleTag, Scope, rule_tag
from alphus.gates.review._module_bindings import module_binding_counts
from alphus.plugins.builtin import BuiltinFeature
from alphus.policy.base import require_policy
from alphus.policy.feature_definition import FeatureDefinition
from alphus.policy.morphology import (
    ClaimKind,
    DetectionMechanism,
    EvaluationMaturity,
    RuleMorphology,
)
from alphus.policy.review import SemanticWorkPresentationPolicy
from alphus.support.inventory import matches_path
from alphus.support.source_text import read_python_source

ALPHUS_CHECK: Final = FeatureDefinition(
    selector="semantic-work-in-presentation",
    policy_field="semantic_work_presentation",
    policy_model=SemanticWorkPresentationPolicy,
    output_shape="findings",
    summary="Reviews semantic work placed in presentation code.",
    applies_to=("python",),
    domains=(),
    requires_files=True,
)

ALPHUS_MORPHOLOGY: Final = RuleMorphology(
    selector="semantic-work-in-presentation",
    finding_ids=(
        RuleTag(
            Scope.PYTHON,
            Framework.NONE,
            Category.ARCHITECTURE,
            "semantic-work-in-presentation",
        ),
    ),
    concern="semantic-responsibilities-co-located-in-presentation",
    claim_kind=ClaimKind.RISK,
    claim=(
        "Configured source-layout, correction, ownership, and serialization calls "
        "co-occur in a presentation function; this does not prove coupling or a defect."
    ),
    mechanisms=(DetectionMechanism.BOUNDED_HEURISTIC,),
    inspected_scope=("configured-python-functions", "consumer-declared-helper-roles"),
    languages_formats=("python",),
    evidence_kinds=("configured-role-contract", "ast-call-analysis", "source-location"),
    evaluation_maturity=EvaluationMaturity.SYNTHETIC_ONLY,
)

_RULE_ID = rule_tag(
    Scope.PYTHON,
    Framework.NONE,
    Category.ARCHITECTURE,
    "semantic-work-in-presentation",
)


@dataclass(frozen=True, slots=True)
class _BoundarySite:
    function: str
    line: int


def _qualified_name(node: ast.expr) -> str | None:
    match node:
        case ast.Name(id=name):
            return name
        case ast.Attribute(value=parent, attr=attribute):
            prefix = _qualified_name(parent)
            return f"{prefix}.{attribute}" if prefix else None
        case _:
            return None


def _local_nodes(root: ast.AST) -> Iterable[ast.AST]:
    yield root
    for child in ast.iter_child_nodes(root):
        match child:
            case (
                ast.FunctionDef()
                | ast.AsyncFunctionDef()
                | ast.ClassDef()
                | ast.Lambda()
            ):
                continue
            case _:
                yield from _local_nodes(child)


def _module_nodes(tree: ast.Module) -> Iterable[ast.AST]:
    def descend(node: ast.AST) -> Iterable[ast.AST]:
        yield node
        for child in ast.iter_child_nodes(node):
            match child:
                case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef():
                    yield child
                case _:
                    yield from descend(child)

    for statement in tree.body:
        match statement:
            case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef():
                yield statement
            case _:
                yield from descend(statement)


def _matched_roles(
    function: ast.FunctionDef, policy: SemanticWorkPresentationPolicy
) -> frozenset[str]:
    configured_roles = (
        ("source-layout reconstruction", policy.source_layout_helpers),
        ("content correction", policy.content_correction_helpers),
        ("semantic ownership", policy.semantic_ownership_helpers),
        ("serialization", policy.serialization_helpers),
    )
    called: set[str] = set()
    for statement in function.body:
        match statement:
            case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef():
                continue
            case _:
                pass
        for node in _local_nodes(statement):
            match node:
                case ast.Call(func=function_expr):
                    name = _qualified_name(function_expr)
                    if name is not None:
                        called.add(name)
                case _:
                    continue
    return frozenset(
        role for role, helpers in configured_roles if called.intersection(helpers)
    )


def semantic_work_presentation_sites(
    source: str, policy: SemanticWorkPresentationPolicy
) -> list[_BoundarySite]:
    """Match all four configured operation roles within a selected function."""
    if policy.module_role != "presentation":
        return []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    if len(list(ast.walk(tree))) > 10_000:
        return []
    functions: list[ast.FunctionDef] = []
    for statement in _module_nodes(tree):
        match statement:
            case ast.FunctionDef(name=name) if name in policy.function_names:
                functions.append(statement)
            case _:
                continue
    bindings = module_binding_counts(tree, policy.function_names)
    configured_roles = (
        policy.source_layout_helpers,
        policy.content_correction_helpers,
        policy.semantic_ownership_helpers,
        policy.serialization_helpers,
    )
    return sorted(
        (
            _BoundarySite(function.name, function.lineno)
            for function in functions
            if bindings.get(function.name, 0) == 1
            if len(_matched_roles(function, policy)) == len(configured_roles)
        ),
        key=lambda site: (site.function, site.line),
    )


def check_semantic_work_presentation(
    root: Path,
    paths: Iterable[Path],
    policy: SemanticWorkPresentationPolicy,
) -> list[Finding]:
    """Report co-located configured responsibilities as an architecture advisory."""
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
        for site in semantic_work_presentation_sites(read_python_source(path), policy):
            findings.append(
                Finding(
                    _RULE_ID,
                    name,
                    f"Configured presentation function {site.function!r} contains "
                    "configured source-layout reconstruction, content-correction, "
                    "semantic-ownership, and serialization calls. Review whether these "
                    "responsibilities need separate contracts or modules. Co-location "
                    "does not prove coupling, incorrect behavior, or that presentation "
                    "transformations are inherently wrong.",
                    site.line,
                    policy.severity,
                )
            )
    return findings


def _run_builtin_semantic_work_presentation(
    root: Path,
    files: Sequence[Path],
    config: QualityGateConfig,
) -> list[Finding]:
    policy = require_policy(
        config.checks.semantic_work_presentation, "semantic_work_presentation"
    )
    return check_semantic_work_presentation(root, files, policy)


ALPHUS_FEATURE: Final = BuiltinFeature(
    definition=ALPHUS_CHECK,
    morphology=ALPHUS_MORPHOLOGY,
    runner=_run_builtin_semantic_work_presentation,
)
