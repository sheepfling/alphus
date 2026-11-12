"""Find configured unknown-inference branches returning a success-shaped empty list."""

from __future__ import annotations

import ast
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Final, NamedTuple

from alphus.config import QualityGateConfig
from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import Category, Framework, RuleTag, Scope, rule_tag
from alphus.plugins.builtin import FindingBuiltinFeature
from alphus.policy.base import require_policy
from alphus.policy.feature_definition import FeatureDefinition
from alphus.policy.morphology import (
    ClaimKind,
    DetectionMechanism,
    EvaluationMaturity,
    RuleMorphology,
)
from alphus.policy.review import UnexplainedEmptyResultPolicy
from alphus.support.inventory import matches_path
from alphus.support.source_text import read_python_source

ALPHUS_CHECK: Final = FeatureDefinition(
    selector="unexplained-empty-results",
    policy_field="unexplained_empty_results",
    policy_model=UnexplainedEmptyResultPolicy,
    output_shape="findings",
    summary="Reviews empty results without an evident explanation.",
    applies_to=("python",),
    domains=(),
    requires_files=True,
)

ALPHUS_MORPHOLOGY: Final = RuleMorphology(
    selector="unexplained-empty-results",
    finding_ids=(
        RuleTag(
            Scope.PYTHON,
            Framework.NONE,
            Category.VALIDATION,
            "unexplained-empty-result",
        ),
    ),
    concern="unknown-inference-is-presented-as-valid-empty-result",
    claim_kind=ClaimKind.RISK,
    claim=(
        "A configured nonempty input and unavailable-inference branch returns an "
        "empty list; the syntax does not prove that emptiness is incorrect."
    ),
    mechanisms=(DetectionMechanism.BOUNDED_HEURISTIC,),
    inspected_scope=("configured-python-source", "unknown-inference-branches"),
    languages_formats=("python",),
    evidence_kinds=("configured-name-pairs", "ast-branch-analysis", "source-location"),
    evaluation_maturity=EvaluationMaturity.SYNTHETIC_ONLY,
)

_RULE_ID = rule_tag(
    Scope.PYTHON,
    Framework.NONE,
    Category.VALIDATION,
    "unexplained-empty-result",
)


class _EmptyResultEvidence(NamedTuple):
    """Names in the unavailable-inference branch and its empty return line."""

    input_name: str
    unavailable_flag: str
    return_line: int


class _EmptyResultSite(NamedTuple):
    """A matched return site with the input and unavailable flag it tests."""

    return_line: int
    input_name: str
    unavailable_flag: str


def _names_in_empty_result_branch(
    node: ast.If, policy: UnexplainedEmptyResultPolicy
) -> _EmptyResultEvidence | None:
    match node.test:
        case ast.BoolOp(op=ast.And(), values=[first, second]):
            conditions = (first, second)
        case _:
            return None
    input_name: str | None = None
    unavailable_name: str | None = None
    for condition in conditions:
        match condition:
            case ast.Name(id=name) if name in policy.nonempty_inputs:
                input_name = name
            case ast.UnaryOp(op=ast.Not(), operand=ast.Name(id=name)) if (
                name in policy.unavailable_flags
            ):
                unavailable_name = name
            case _:
                return None
    if input_name is None or unavailable_name is None:
        return None
    for statement in node.body:
        match statement:
            case ast.Return(value=ast.List(elts=[])):
                return _EmptyResultEvidence(
                    input_name, unavailable_name, statement.lineno
                )
            case _:
                continue
    return None


def empty_result_branches(
    source: str, policy: UnexplainedEmptyResultPolicy
) -> list[_EmptyResultSite]:
    """Match only nonempty-input AND unavailable-inference branches returning []."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    results: set[_EmptyResultSite] = set()
    for node in ast.walk(tree):
        match node:
            case ast.If() as conditional:
                evidence = _names_in_empty_result_branch(conditional, policy)
                if evidence is not None:
                    results.add(
                        _EmptyResultSite(
                            evidence.return_line,
                            evidence.input_name,
                            evidence.unavailable_flag,
                        )
                    )
            case _:
                continue
    return sorted(results)


def check_unexplained_empty_results(
    root: Path,
    paths: Iterable[Path],
    policy: UnexplainedEmptyResultPolicy,
) -> list[Finding]:
    """Report one configured inference-failure branch per selected source site."""
    checkout = root.resolve(strict=True)
    findings: list[Finding] = []
    for relative in sorted(paths):
        name = relative.as_posix()
        if (
            relative.suffix != ".py"
            or any(matches_path(name, item) for item in policy.exclude)
            or not any(matches_path(name, item) for item in policy.source_paths)
        ):
            continue
        path = checkout / relative
        if not path.is_file():
            continue
        for site in empty_result_branches(read_python_source(path), policy):
            findings.append(
                Finding(
                    _RULE_ID,
                    name,
                    "configured nonempty input and unavailable inference return an "
                    f"empty list ({site.input_name} and not "
                    f"{site.unavailable_flag}); consider "
                    "an explicit unknown/unsupported result so callers can distinguish "
                    "inference failure from valid emptiness. This syntax does not prove "
                    "the empty result is incorrect.",
                    site.return_line,
                    policy.severity,
                )
            )
    return findings


def resolve_unexplained_empty_results_policy(
    config: QualityGateConfig,
) -> UnexplainedEmptyResultPolicy:
    """Resolve the check's strict policy from validated aggregate config."""
    return require_policy(
        config.checks.unexplained_empty_results, "unexplained_empty_results"
    )


def _run_builtin_unexplained_empty_results(
    root: Path,
    files: Sequence[Path],
    policy: UnexplainedEmptyResultPolicy,
) -> list[Finding]:
    return check_unexplained_empty_results(root, files, policy)


ALPHUS_FEATURE: Final = FindingBuiltinFeature(
    definition=ALPHUS_CHECK,
    morphology=ALPHUS_MORPHOLOGY,
    runner=_run_builtin_unexplained_empty_results,
    policy_resolver=resolve_unexplained_empty_results_policy,
)
