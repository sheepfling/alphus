"""Find configured unknown-inference branches returning a success-shaped empty list."""

from __future__ import annotations

import ast
from collections.abc import Iterable
from pathlib import Path

from alphus.config import UnexplainedEmptyResultPolicy
from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import Category, Framework, Scope, rule_tag
from alphus.support.inventory import matches_path
from alphus.support.source_text import read_python_source

_RULE_ID = rule_tag(
    Scope.PYTHON,
    Framework.NONE,
    Category.VALIDATION,
    "unexplained-empty-result",
)


def _names_in_empty_result_branch(
    node: ast.If, policy: UnexplainedEmptyResultPolicy
) -> tuple[str, str, int] | None:
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
                return input_name, unavailable_name, statement.lineno
            case _:
                continue
    return None


def empty_result_branches(
    source: str, policy: UnexplainedEmptyResultPolicy
) -> list[tuple[int, str, str]]:
    """Match only nonempty-input AND unavailable-inference branches returning []."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    results: set[tuple[int, str, str]] = set()
    for node in ast.walk(tree):
        match node:
            case ast.If() as conditional:
                evidence = _names_in_empty_result_branch(conditional, policy)
                if evidence is not None:
                    input_name, unavailable_name, return_line = evidence
                    results.add((return_line, input_name, unavailable_name))
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
        for line, input_name, unavailable_name in empty_result_branches(
            read_python_source(path), policy
        ):
            findings.append(
                Finding(
                    _RULE_ID,
                    name,
                    "configured nonempty input and unavailable inference return an "
                    f"empty list ({input_name} and not {unavailable_name}); consider "
                    "an explicit unknown/unsupported result so callers can distinguish "
                    "inference failure from valid emptiness. This syntax does not prove "
                    "the empty result is incorrect.",
                    line,
                    policy.severity,
                )
            )
    return findings
