"""Review configured positional branches that replace semantic field text."""

from __future__ import annotations

import ast
from collections.abc import Iterable
from pathlib import Path

from alphus.config import PositionalSemanticOverridePolicy
from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import Category, Framework, Scope, rule_tag
from alphus.support.inventory import matches_path
from alphus.support.source_text import read_python_source

ALPHUS_MORPHOLOGY = (
    ("selector", "positional-semantic-overrides"),
    ("concern", "semantic-field-overrides"),
    ("claim_kind", "risk"),
    (
        "claim",
        (
            "A configured positional branch assigns hard-coded text to a semantic field; the "
            "match is a review candidate, not proof of a defect."
        ),
    ),
    ("mechanisms", ("bounded-heuristic",)),
    (
        "inspected_scope",
        ("configured-python-paths", "if-branches", "semantic-field-assignments"),
    ),
    ("languages_formats", ("python",)),
    (
        "evidence_kinds",
        ("python-ast-branch", "configured-field", "assignment-source-line"),
    ),
    ("evaluation_maturity", "public-sample-reviewed"),
    ("finding_tag_complaints", ("positional-semantic-override",)),
)


_RULE_ID = rule_tag(
    Scope.PYTHON,
    Framework.NONE,
    Category.MAINTAINABILITY,
    "positional-semantic-override",
)


def _integer_values(node: ast.expr) -> tuple[int, ...]:
    match node:
        case ast.Constant(value=True | False):
            return ()
        case ast.Constant(value=int(value)):
            return (value,)
        case ast.Tuple(elts=items) | ast.List(elts=items) | ast.Set(elts=items):
            values: list[int] = []
            for item in items:
                match item:
                    case ast.Constant(value=True | False):
                        return ()
                    case ast.Constant(value=int(value)):
                        values.append(value)
                    case _:
                        return ()
            return tuple(values)
        case _:
            return ()


def _position_branch(
    test: ast.expr, names: tuple[str, ...]
) -> tuple[str, tuple[int, ...]] | None:
    match test:
        case ast.Compare(
            left=ast.Name(id=name),
            ops=[ast.Eq() | ast.In()],
            comparators=[literal],
        ) if name in names:
            values = _integer_values(literal)
            return (name, values) if values else None
        case _:
            return None


def _semantic_assignment(
    node: ast.stmt, policy: PositionalSemanticOverridePolicy
) -> tuple[int, str] | None:
    match node:
        case ast.Assign(
            targets=[
                ast.Subscript(
                    slice=ast.Constant(value=str(field)),
                )
            ],
            value=ast.Constant(value=str(text)),
        ) if (
            field in policy.semantic_fields
            and len(text) >= policy.minimum_override_characters
        ):
            return node.lineno, text
        case _:
            return None


def positional_override_sites(
    source: str, policy: PositionalSemanticOverridePolicy
) -> list[tuple[int, int, str, tuple[int, ...], str]]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    sites: set[tuple[int, int, str, tuple[int, ...], str]] = set()
    for node in ast.walk(tree):
        match node:
            case ast.If(test=test, body=body):
                position = _position_branch(test, policy.position_variables)
                if position is None:
                    continue
                variable, values = position
                for statement in body:
                    assignment = _semantic_assignment(statement, policy)
                    if assignment is not None:
                        line, text = assignment
                        sites.add((node.lineno, line, variable, values, text))
            case _:
                continue
    return sorted(sites)


def check_positional_semantic_overrides(
    root: Path,
    paths: Iterable[Path],
    policy: PositionalSemanticOverridePolicy,
) -> list[Finding]:
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
        for (
            branch_line,
            assignment_line,
            variable,
            positions,
            text,
        ) in positional_override_sites(read_python_source(path), policy):
            excerpt = text if len(text) <= 80 else text[:77] + "..."
            findings.append(
                Finding(
                    _RULE_ID,
                    name,
                    "consumer-configured positional branch replaces a semantic "
                    f"field with hard-coded text ({variable}={positions!r}, "
                    f"lines {branch_line}/{assignment_line}: {excerpt!r}); review the "
                    "source contract and provenance. This match does not prove the "
                    "override is invalid.",
                    assignment_line,
                    policy.severity,
                )
            )
    return findings
