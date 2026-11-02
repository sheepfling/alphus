"""Find configured rendered strings used as semantic source predicates."""

from __future__ import annotations

import ast
from collections.abc import Iterable, Sequence
from pathlib import Path

from alphus.config import ProseAsControlPolicy
from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import Category, Framework, Scope, rule_tag
from alphus.support.inventory import matches_path
from alphus.support.source_text import read_python_source

_RULE_ID = rule_tag(
    Scope.PYTHON, Framework.NONE, Category.CORRECTNESS, "rendered-value-reparsed"
)


def _qualified_name(node: ast.expr) -> str | None:
    match node:
        case ast.Name(id=name):
            return name
        case ast.Attribute(value=parent, attr=attribute):
            prefix = _qualified_name(parent)
            return f"{prefix}.{attribute}" if prefix else None
        case _:
            return None


def _rendered_locals(
    function: ast.FunctionDef | ast.AsyncFunctionDef, helpers: tuple[str, ...]
) -> dict[str, int]:
    rendered: dict[str, int] = {}
    for node in ast.walk(function):
        match node:
            case ast.Assign(
                targets=[ast.Name(id=name)], value=ast.Call(func=func, args=[_, *_])
            ) if _qualified_name(func) in helpers:
                rendered[name] = node.lineno
            case ast.AnnAssign(
                target=ast.Name(id=name), value=ast.Call(func=func, args=[_, *_])
            ) if _qualified_name(func) in helpers:
                rendered[name] = node.lineno
            case _:
                continue
    return rendered


def _uses_rendered_suffix(test: ast.expr, names: Sequence[str]) -> str | None:
    match test:
        case ast.Call(
            func=ast.Attribute(
                value=ast.Call(
                    func=ast.Attribute(value=ast.Name(id=name), attr="rstrip"),
                    args=[],
                    keywords=[],
                ),
                attr="endswith",
            ),
            args=[ast.Constant(value=str(suffix))],
            keywords=[],
        ) if name in names and suffix:
            return name
        case _:
            return None


def _sites(source: str, helpers: tuple[str, ...]) -> list[tuple[int, int, str]]:
    if not helpers:
        return []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    found: set[tuple[int, int, str]] = set()
    for node in ast.walk(tree):
        match node:
            case ast.FunctionDef() | ast.AsyncFunctionDef() as function:
                rendered = _rendered_locals(function, helpers)
                for branch in ast.walk(function):
                    match branch:
                        case ast.If(test=test) as conditional:
                            name = _uses_rendered_suffix(test, tuple(rendered))
                            if name is not None:
                                found.add((rendered[name], conditional.lineno, name))
                        case _:
                            continue
            case _:
                continue
    return sorted(found)


def check_rendered_value_reparsed(
    root: Path, paths: Iterable[Path], policy: ProseAsControlPolicy
) -> list[Finding]:
    """Report only configured rendering helpers and explicit suffix predicates."""
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
        for render_line, predicate_line, variable in _sites(
            read_python_source(path), policy.rendered_value_helpers
        ):
            findings.append(
                Finding(
                    _RULE_ID,
                    name,
                    "configured rendered output flows into a semantic suffix predicate "
                    f"({variable}.rstrip().endswith(...), lines {render_line}/"
                    f"{predicate_line}); inspect whether source semantics should be "
                    "checked before rendering. Static flow does not prove corruption.",
                    predicate_line,
                    policy.severity,
                )
            )
    return findings
