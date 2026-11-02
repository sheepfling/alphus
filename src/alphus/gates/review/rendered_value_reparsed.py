"""Find configured rendered strings used as semantic source predicates."""

from __future__ import annotations

import ast
from collections.abc import Iterable, Mapping, Sequence
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


def _target_names(target: ast.expr) -> set[str]:
    names: set[str] = set()
    match target:
        case ast.Name(id=name):
            names.add(name)
        case ast.Tuple(elts=items) | ast.List(elts=items):
            for item in items:
                names.update(_target_names(item))
        case ast.Starred(value=value):
            names.update(_target_names(value))
        case _:
            pass
    return names


def _pattern_names(pattern: ast.pattern) -> set[str]:
    names: set[str] = set()
    match pattern:
        case ast.MatchAs(pattern=inner, name=name):
            if name is not None:
                names.add(name)
            if inner is not None:
                names.update(_pattern_names(inner))
        case ast.MatchStar(name=name):
            if name is not None:
                names.add(name)
        case ast.MatchMapping(patterns=patterns, rest=rest):
            if rest is not None:
                names.add(rest)
            for item in patterns:
                names.update(_pattern_names(item))
        case ast.MatchClass(patterns=patterns, kwd_patterns=keyword_patterns):
            for item in (*patterns, *keyword_patterns):
                names.update(_pattern_names(item))
        case ast.MatchSequence(patterns=patterns) | ast.MatchOr(patterns=patterns):
            for item in patterns:
                names.update(_pattern_names(item))
        case _:
            pass
    return names


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


def _common_bindings(states: Sequence[Mapping[str, int]]) -> dict[str, int]:
    if not states:
        return {}
    first = states[0]
    return {
        name: line
        for name, line in first.items()
        if all(state.get(name) == line for state in states[1:])
    }


def _sites(source: str, helpers: tuple[str, ...]) -> list[tuple[int, int, str]]:
    if not helpers:
        return []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    found: set[tuple[int, int, str]] = set()

    def scan(
        statements: Sequence[ast.stmt], rendered: Mapping[str, int]
    ) -> dict[str, int]:
        """Walk statements in source order, keeping only proven local bindings."""
        current = dict(rendered)
        for statement in statements:
            match statement:
                case ast.If(test=test, body=body, orelse=orelse) as conditional:
                    name = _uses_rendered_suffix(test, tuple(current))
                    if name is not None:
                        found.add((current[name], conditional.lineno, name))
                    branch_state = current.copy()
                    for node in ast.walk(test):
                        match node:
                            case ast.NamedExpr(target=ast.Name(id=name)):
                                branch_state.pop(name, None)
                            case _:
                                continue
                    then_state = scan(body, branch_state)
                    else_state = (
                        scan(orelse, branch_state) if orelse else branch_state.copy()
                    )
                    current = {
                        name: line
                        for name, line in then_state.items()
                        if else_state.get(name) == line
                    }
                case ast.Assign(
                    targets=[ast.Name(id=name)],
                    value=ast.Call(func=func, args=args, keywords=keywords),
                ) if _qualified_name(func) in helpers and (args or keywords):
                    current.pop(name, None)
                    current[name] = statement.lineno
                case ast.Assign(targets=targets):
                    names: set[str] = set()
                    for target in targets:
                        names.update(_target_names(target))
                    for name in names:
                        current.pop(name, None)
                case ast.AnnAssign(
                    target=ast.Name(id=name),
                    value=ast.Call(func=func, args=args, keywords=keywords),
                ) if _qualified_name(func) in helpers and (args or keywords):
                    current.pop(name, None)
                    current[name] = statement.lineno
                case ast.AnnAssign(target=target):
                    names = _target_names(target)
                    for name in names:
                        current.pop(name, None)
                case ast.AugAssign(target=target):
                    for name in _target_names(target):
                        current.pop(name, None)
                case (
                    ast.For(target=target, body=body, orelse=orelse)
                    | ast.AsyncFor(target=target, body=body, orelse=orelse)
                ):
                    before = current.copy()
                    loop_state = current.copy()
                    for name in _target_names(target):
                        loop_state.pop(name, None)
                    loop_state = scan(body, loop_state)
                    else_state = scan(orelse, current) if orelse else current.copy()
                    current = {
                        name: line
                        for name, line in before.items()
                        if loop_state.get(name) == line and else_state.get(name) == line
                    }
                case ast.While(test=test, body=body, orelse=orelse):
                    before = current.copy()
                    loop_state = current.copy()
                    for node in ast.walk(test):
                        match node:
                            case ast.NamedExpr(target=ast.Name(id=name)):
                                loop_state.pop(name, None)
                            case _:
                                continue
                    body_state = scan(body, loop_state)
                    else_state = (
                        scan(orelse, loop_state) if orelse else loop_state.copy()
                    )
                    current = {
                        name: line
                        for name, line in before.items()
                        if body_state.get(name) == line and else_state.get(name) == line
                    }
                case (
                    ast.With(items=items, body=body)
                    | ast.AsyncWith(items=items, body=body)
                ):
                    before = current.copy()
                    body_state = current.copy()
                    for item in items:
                        if item.optional_vars is not None:
                            for name in _target_names(item.optional_vars):
                                body_state.pop(name, None)
                    body_state = scan(body, body_state)
                    current = {
                        name: line
                        for name, line in before.items()
                        if body_state.get(name) == line
                    }
                case ast.Try(
                    body=body, handlers=handlers, orelse=orelse, finalbody=finalbody
                ):
                    body_state = scan(body, current)
                    normal_state = scan(orelse, body_state) if orelse else body_state
                    paths = [normal_state]
                    exception_state = _common_bindings([current, body_state])
                    paths.extend(
                        scan(handler.body, exception_state) for handler in handlers
                    )
                    if finalbody:
                        # An exception can enter finally before the body completes,
                        # so only bindings common to normal and exceptional paths
                        # are available there.
                        paths.append(current.copy())
                    current = _common_bindings(paths)
                    if finalbody:
                        current = scan(finalbody, current)
                case ast.Match(cases=cases):
                    before = current.copy()
                    paths: list[dict[str, int]] = []
                    for case in cases:
                        case_state = current.copy()
                        for name in _pattern_names(case.pattern):
                            case_state.pop(name, None)
                        paths.append(scan(case.body, case_state))
                    current = {
                        name: line
                        for name, line in before.items()
                        if all(path.get(name) == line for path in paths)
                    }
                case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef():
                    # Nested definitions have separate scopes and are visited
                    # independently by the outer function walk below.
                    continue
                case _:
                    continue
        return current

    for node in ast.walk(tree):
        match node:
            case ast.FunctionDef() | ast.AsyncFunctionDef() as function:
                scan(function.body, {})
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
