"""Review declared source-specific repair clusters in configured parsers."""

from __future__ import annotations

import ast
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from alphus.config import PatchCascadePolicy
from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import Category, Framework, Scope, rule_tag
from alphus.support.inventory import matches_path
from alphus.support.source_text import read_python_source

_RULE_ID = rule_tag(
    Scope.PYTHON, Framework.NONE, Category.MAINTAINABILITY, "patch-cascade"
)


@dataclass(frozen=True, slots=True)
class _PatchCascadeSite:
    function_name: str
    repair_ids: tuple[str, ...]
    helpers: tuple[str, ...]
    line: int


def _call_name(node: ast.expr) -> str | None:
    match node:
        case ast.Name(id=name):
            return name
        case ast.Attribute(value=value, attr=attribute):
            parent = _call_name(value)
            return f"{parent}.{attribute}" if parent else None
        case _:
            return None


def _call(node: ast.AST) -> ast.Call | None:
    match node:
        case ast.Call() as call:
            return call
        case _:
            return None


def _stored_helper_name(node: ast.AST, names: frozenset[str]) -> bool:
    match node:
        case ast.Name(id=name, ctx=ast.Store()) if name in names:
            return True
        case _:
            return False


def _walk_function_body(node: ast.AST) -> Iterable[ast.AST]:
    """Walk statements and expressions without crossing lexical scope boundaries."""
    yield node
    match node:
        case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef() | ast.Lambda():
            return
        case _:
            pass
    for child in ast.iter_child_nodes(node):
        yield from _walk_function_body(child)


def _repair_id(
    test: ast.expr, selectors: frozenset[str], ids: frozenset[str]
) -> str | None:
    match test:
        case ast.Compare(
            left=ast.Name(id=selector),
            ops=[ast.Eq()],
            comparators=[ast.Constant(value=str() as value)],
        ):
            return value if selector in selectors and value in ids else None
        case ast.Compare(
            left=ast.Constant(value=str() as value),
            ops=[ast.Eq()],
            comparators=[ast.Name(id=selector)],
        ):
            return value if selector in selectors and value in ids else None
        case _:
            return None


def patch_cascade_sites(
    source: str, policy: PatchCascadePolicy
) -> list[_PatchCascadeSite]:
    """Find two distinct configured repair branches with configured normalizers."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    if len(list(ast.walk(tree))) > 10_000:
        return []

    sites: list[_PatchCascadeSite] = []
    for configured in policy.functions:
        definitions: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
        for node in tree.body:
            match node:
                case ast.FunctionDef(name=name) | ast.AsyncFunctionDef(name=name) if (
                    name == configured.function_name
                ):
                    definitions.append(node)
                case _:
                    continue
        # Only one top-level definition is accepted. Rebinding in module-level
        # control flow or assignment makes the configured function ambiguous.
        bindings = 0
        for statement in tree.body:
            for node in _walk_function_body(statement):
                match node:
                    case (
                        ast.FunctionDef(name=name) | ast.AsyncFunctionDef(name=name)
                    ) if name == configured.function_name:
                        bindings += 1
                    case ast.ClassDef(name=name) if name == configured.function_name:
                        bindings += 1
                    case ast.Name(id=name, ctx=ast.Store() | ast.Del()) if (
                        name == configured.function_name
                    ):
                        bindings += 1
                    case ast.Import(names=aliases):
                        if any(
                            (alias.asname or alias.name.split(".", maxsplit=1)[0])
                            == configured.function_name
                            for alias in aliases
                        ):
                            bindings += 1
                    case ast.ImportFrom(names=aliases):
                        if any(
                            (alias.asname or alias.name) == configured.function_name
                            for alias in aliases
                        ):
                            bindings += 1
                    case _:
                        continue
        if len(definitions) != 1 or bindings != 1:
            continue
        function = definitions[0]
        helper_roots = frozenset(
            item.split(".", maxsplit=1)[0] for item in configured.normalization_helpers
        )
        body_nodes = [
            node
            for statement in function.body
            for node in _walk_function_body(statement)
        ]
        # If a configured helper root is locally rebound, its call identity is
        # unknown; abstain for this function rather than treating spelling as proof.
        parameters = {
            argument.arg
            for argument in (
                *function.args.posonlyargs,
                *function.args.args,
                *function.args.kwonlyargs,
            )
        }
        if parameters & helper_roots or any(
            _stored_helper_name(node, helper_roots) for node in body_nodes
        ):
            continue
        matched: dict[str, tuple[int, set[str]]] = {}
        for node in body_nodes:
            match node:
                case ast.If() as branch:
                    pass
                case _:
                    continue
            repair_id = _repair_id(
                branch.test,
                frozenset(configured.selector_names),
                frozenset(configured.repair_ids),
            )
            if repair_id is None:
                continue
            calls = {
                call_name
                for statement in branch.body
                for candidate in _walk_function_body(statement)
                if (call := _call(candidate)) is not None
                if (call_name := _call_name(call.func)) is not None
                and call_name in configured.normalization_helpers
            }
            if calls:
                matched[repair_id] = (branch.lineno, calls)
        if len(matched) < 2:
            continue
        repair_ids = tuple(sorted(matched))
        helpers = tuple(
            sorted({helper for _, names in matched.values() for helper in names})
        )
        line = sorted(matched.values())[1][0]
        sites.append(
            _PatchCascadeSite(configured.function_name, repair_ids, helpers, line)
        )
    return sites


def check_patch_cascade(
    root: Path, paths: Iterable[Path], policy: PatchCascadePolicy
) -> list[Finding]:
    """Report declared repair clusters as review prompts, never defect claims."""
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
        for site in patch_cascade_sites(read_python_source(path), policy):
            findings.append(
                Finding(
                    _RULE_ID,
                    name,
                    f"Configured general parser {site.function_name!r} has separate "
                    "normalization branches for repair IDs "
                    f"{', '.join(map(repr, site.repair_ids))}; "
                    f"configured helpers: {', '.join(site.helpers)}. Review whether this "
                    "source-specific repair cluster belongs in a shared parsing policy. "
                    "The declared contract and syntax do not prove unrelated patches or a defect.",
                    site.line,
                    policy.severity,
                )
            )
    return findings
