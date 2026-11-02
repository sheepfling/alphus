"""Advisory for long sentence-like literals that select a code branch."""

from __future__ import annotations

import ast
import re
from collections.abc import Iterable
from pathlib import Path

from alphus.config import ProseAsControlPolicy
from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import Category, Framework, Scope, rule_tag
from alphus.support.inventory import matches_path
from alphus.support.source_text import read_python_source

_RULE_ID = rule_tag(
    Scope.PYTHON, Framework.NONE, Category.MAINTAINABILITY, "prose-as-control"
)
_SENTENCE_WORD = re.compile(r"\b[A-Za-z]{2,}\b")


def _branch_comparisons(tree: ast.AST) -> Iterable[ast.Compare]:
    for node in ast.walk(tree):
        match node:
            case ast.If(test=test) | ast.While(test=test) | ast.IfExp(test=test):
                for item in ast.walk(test):
                    match item:
                        case ast.Compare():
                            yield item
                        case _:
                            continue
            case _:
                continue


def _sentence_literals(node: ast.Compare) -> set[str]:
    if not any(_is_text_comparison(op) for op in node.ops):
        return set()
    literals: set[str] = set()
    for value in (node.left, *node.comparators):
        match value:
            case ast.Constant(value=str(literal)):
                literals.add(literal)
            case (
                ast.Tuple(elts=elements)
                | ast.List(elts=elements)
                | ast.Set(elts=elements)
            ):
                for item in elements:
                    match item:
                        case ast.Constant(value=str(literal)):
                            literals.add(literal)
                        case _:
                            continue
            case _:
                continue
    return literals


def _is_text_comparison(operator: ast.cmpop) -> bool:
    match operator:
        case ast.Eq() | ast.NotEq() | ast.In() | ast.NotIn():
            return True
        case _:
            return False


def prose_control_literals(
    source: str, policy: ProseAsControlPolicy
) -> list[tuple[int, str]]:
    """Return long sentence-like branch literals; protocol meaning is unknown."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    allowed = set(policy.allowed_literals)
    observations: set[tuple[int, str]] = set()
    for comparison in _branch_comparisons(tree):
        for literal in _sentence_literals(comparison):
            if (
                literal in allowed
                or len(literal) < policy.minimum_characters
                or not literal.rstrip().endswith((".", "!", "?"))
                or len(_SENTENCE_WORD.findall(literal)) < policy.minimum_words
            ):
                continue
            observations.add((comparison.lineno, literal))
    return sorted(observations)


def check_prose_as_control(
    root: Path, paths: Iterable[Path], policy: ProseAsControlPolicy
) -> list[Finding]:
    """Return review prompts only for explicitly scoped production source."""
    checkout = root.resolve(strict=True)
    findings: list[Finding] = []
    for relative in sorted(paths):
        name = relative.as_posix()
        if (
            relative.suffix != ".py"
            or not any(matches_path(name, pattern) for pattern in policy.source_paths)
            or any(matches_path(name, pattern) for pattern in policy.exclude)
        ):
            continue
        path = checkout / relative
        if not path.is_file():
            continue
        for line, literal in prose_control_literals(read_python_source(path), policy):
            excerpt = literal if len(literal) <= 100 else literal[:97] + "..."
            findings.append(
                Finding(
                    rule_id=_RULE_ID,
                    path=name,
                    line=line,
                    message=(
                        "A long sentence-like literal controls a branch. If this is not "
                        "stable protocol/compatibility text or an intentional content "
                        "predicate, consider separating the decision into a short "
                        "mode/state value and keeping prose as data. This match does not "
                        f"imply AI authorship or prove a defect; literal: {excerpt!r}"
                    ),
                    severity=policy.severity,
                )
            )
    return findings
