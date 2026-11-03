"""Find configured source-anchor plus fixed replacement paragraph patterns."""

from __future__ import annotations

import ast
from collections.abc import Iterable
from pathlib import Path

from alphus.config import EmbeddedSemanticOverridePolicy
from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import Category, Framework, Scope, rule_tag
from alphus.support.inventory import matches_path
from alphus.support.source_text import read_python_source

_RULE_ID = rule_tag(
    Scope.PYTHON,
    Framework.NONE,
    Category.CORRECTNESS,
    "embedded-semantic-override",
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


def _lookup_assignment(
    statement: ast.stmt, policy: EmbeddedSemanticOverridePolicy
) -> tuple[str, int] | None:
    match statement:
        case ast.Assign(
            targets=[ast.Name(id=result)],
            value=ast.Call(
                func=ast.Attribute(value=mapping, attr="get"),
                args=[_],
            ),
        ) if _qualified_name(mapping) in policy.replacement_maps:
            return result, statement.lineno
        case _:
            return None


def _replacement_return(
    statement: ast.stmt,
    replacement_name: str,
    policy: EmbeddedSemanticOverridePolicy,
) -> bool:
    match statement:
        case ast.Return(
            value=ast.BinOp(
                left=ast.Call(func=anchor, args=[_, *_]),
                op=ast.Add(),
                right=ast.Name(id=name),
            )
        ) if (
            name == replacement_name
            and _qualified_name(anchor) in policy.source_anchor_helpers
        ):
            return True
        case _:
            return False


def _current_scope_nodes(root: ast.AST) -> Iterable[ast.AST]:
    """Walk current-scope statements and evaluated definition-time expressions."""
    yield root
    match root:
        case ast.FunctionDef() | ast.AsyncFunctionDef():
            arguments = root.args
            expressions = [
                *root.decorator_list,
                *arguments.defaults,
                *(item for item in arguments.kw_defaults if item is not None),
                *(
                    argument.annotation
                    for argument in (
                        *arguments.posonlyargs,
                        *arguments.args,
                        *arguments.kwonlyargs,
                    )
                    if argument.annotation is not None
                ),
                *(
                    [arguments.vararg.annotation]
                    if arguments.vararg is not None
                    and arguments.vararg.annotation is not None
                    else []
                ),
                *(
                    [arguments.kwarg.annotation]
                    if arguments.kwarg is not None
                    and arguments.kwarg.annotation is not None
                    else []
                ),
                *([root.returns] if root.returns is not None else []),
            ]
            children = expressions
        case ast.ClassDef():
            children = [
                *root.decorator_list,
                *root.bases,
                *(keyword.value for keyword in root.keywords),
            ]
        case ast.Lambda():
            children = [
                *root.args.defaults,
                *(item for item in root.args.kw_defaults if item is not None),
            ]
        case _:
            children = list(ast.iter_child_nodes(root))
    for child in children:
        yield from _current_scope_nodes(child)


def _stores_name(statement: ast.AST, name: str) -> bool:
    for node in _current_scope_nodes(statement):
        match node:
            case ast.FunctionDef(name=stored) | ast.AsyncFunctionDef(name=stored):
                if stored == name:
                    return True
            case ast.ClassDef(name=stored) if stored == name:
                return True
            case ast.Import(names=aliases) if any(
                (alias.asname or alias.name.split(".")[0]) == name for alias in aliases
            ):
                return True
            case ast.ImportFrom(names=aliases) if any(
                alias.name == "*" or (alias.asname or alias.name) == name
                for alias in aliases
            ):
                return True
            case ast.Name(id=stored, ctx=ast.Store() | ast.Del()) if stored == name:
                return True
            case ast.MatchAs(name=stored) | ast.MatchStar(name=stored) if (
                stored == name
            ):
                return True
            case ast.MatchMapping(rest=stored) if stored == name:
                return True
            case ast.ExceptHandler(name=stored) if stored == name:
                return True
            case _:
                continue
    return False


def _is_none_guard(statement: ast.stmt, name: str) -> ast.If | None:
    match statement:
        case ast.If(
            test=ast.Compare(
                left=ast.Name(id=actual),
                ops=[ast.IsNot()],
                comparators=[ast.Constant(value=None)],
            )
        ) if actual == name:
            return statement
        case _:
            return None


def _guard_returns_replacement(
    body: Iterable[ast.stmt],
    replacement_name: str,
    policy: EmbeddedSemanticOverridePolicy,
) -> bool:
    for statement in body:
        if _stores_name(statement, replacement_name):
            return False
        if _replacement_return(statement, replacement_name, policy):
            return True
    return False


def embedded_override_sites(
    source: str, policy: EmbeddedSemanticOverridePolicy
) -> list[tuple[str, int, int, str]]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    sites: set[tuple[str, int, int, str]] = set()
    for node in ast.walk(tree):
        match node:
            case ast.FunctionDef(name=function) | ast.AsyncFunctionDef(name=function):
                for index, statement in enumerate(node.body):
                    lookup = _lookup_assignment(statement, policy)
                    if lookup is None:
                        continue
                    replacement_name, lookup_line = lookup
                    for following in node.body[index + 1 :]:
                        if _stores_name(following, replacement_name):
                            break
                        conditional = _is_none_guard(following, replacement_name)
                        if conditional is not None and _guard_returns_replacement(
                            conditional.body, replacement_name, policy
                        ):
                            sites.add(
                                (
                                    function,
                                    lookup_line,
                                    conditional.lineno,
                                    replacement_name,
                                )
                            )
            case _:
                continue
    return sorted(sites)


def check_embedded_semantic_overrides(
    root: Path,
    paths: Iterable[Path],
    policy: EmbeddedSemanticOverridePolicy,
) -> list[Finding]:
    """Report only configured map lookups combined with configured source anchors."""
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
        for (
            function,
            lookup_line,
            branch_line,
            replacement_name,
        ) in embedded_override_sites(read_python_source(path), policy):
            findings.append(
                Finding(
                    _RULE_ID,
                    name,
                    "configured semantic replacement-map text is returned alongside "
                    f"an existing source anchor ({function}: {replacement_name}, "
                    f"lookup/branch lines {lookup_line}/{branch_line}); review whether "
                    "the replacement preserves source wording and anchor provenance. "
                    "Static syntax does not prove a mismatch.",
                    branch_line,
                    policy.severity,
                )
            )
    return findings
