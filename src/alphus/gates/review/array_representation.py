"""Find configured direct array -> list -> array conversion chains."""

from __future__ import annotations

import ast
from collections.abc import Iterable
from pathlib import Path

from alphus.config import ArrayRepresentationPolicy
from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import Category, Framework, Scope, rule_tag
from alphus.support.inventory import matches_path
from alphus.support.source_text import read_python_source

_RULE_ID = rule_tag(
    Scope.PYTHON,
    Framework.NONE,
    Category.MAINTAINABILITY,
    "array-representation-churn",
)


def _is_control_flow(node: ast.AST) -> bool:
    match node:
        case (
            ast.If()
            | ast.For()
            | ast.AsyncFor()
            | ast.While()
            | ast.Try()
            | ast.With()
            | ast.Match()
        ):
            return True
        case _:
            return False


def _call_name(node: ast.expr) -> str | None:
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return None
    return ".".join((current.id, *reversed(parts)))


def _round_trip(node: ast.Call, policy: ArrayRepresentationPolicy) -> ast.Call | None:
    if _call_name(node.func) not in policy.array_constructors:
        return None
    if len(node.args) != 1 or node.keywords:
        return None
    source = node.args[0]
    if not isinstance(source, ast.Call) or source.args or source.keywords:
        return None
    method = source.func
    if not isinstance(method, ast.Attribute):
        return None
    if method.attr not in policy.list_conversion_methods:
        return None
    if not isinstance(method.value, ast.Name):
        return None
    return source


def _candidates(
    source: str, policy: ArrayRepresentationPolicy
) -> list[tuple[int, int]]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    parents = {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }
    results: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        match node:
            case ast.Call():
                pass
            case _:
                continue
        inner = _round_trip(node, policy)
        if inner is None:
            continue
        ancestor = parents.get(node)
        inside_control_flow = False
        while ancestor is not None:
            if _is_control_flow(ancestor):
                inside_control_flow = True
                break
            ancestor = parents.get(ancestor)
        if inside_control_flow:
            continue
        results.append((node.lineno, inner.lineno))
    return results


def representation_churn_lines(
    source: str, policy: ArrayRepresentationPolicy
) -> list[tuple[int, int]]:
    """Return outer-constructor and inner-conversion line pairs for fixtures."""
    return _candidates(source, policy)


def check_array_representation(
    root: Path, paths: Iterable[Path], policy: ArrayRepresentationPolicy
) -> list[Finding]:
    """Report only the exact configured nested conversion expression."""
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
        for outer_line, inner_line in _candidates(read_python_source(path), policy):
            findings.append(
                Finding(
                    _RULE_ID,
                    name,
                    "configured array constructor immediately rebuilds an array from "
                    f"a local .tolist() result (lines {inner_line}-{outer_line}); "
                    "review whether the list boundary is required. This does not "
                    "establish a performance problem or equivalent replacement.",
                    outer_line,
                    policy.severity,
                )
            )
    return findings
