"""Find configured text-preserving functions that return only token matches."""

from __future__ import annotations

import ast
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from alphus.config import HeuristicTotalConsumptionPolicy
from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import Category, Framework, Scope, rule_tag
from alphus.support.inventory import matches_path
from alphus.support.source_text import read_python_source

_RULE_ID = rule_tag(
    Scope.PYTHON,
    Framework.NONE,
    Category.CORRECTNESS,
    "heuristic-total-consumption",
)


@dataclass(frozen=True, slots=True)
class _ConsumptionSite:
    function: str
    input_name: str
    helper: str
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


def _functions(statements: Iterable[ast.stmt]) -> Iterable[ast.FunctionDef]:
    for statement in statements:
        if isinstance(statement, ast.FunctionDef):
            yield statement


def _scope_nodes(root: ast.AST) -> Iterable[ast.AST]:
    yield root
    for child in ast.iter_child_nodes(root):
        if isinstance(
            child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
        ):
            yield child
            continue
        yield from _scope_nodes(child)


def _redefined(tree: ast.Module, selected: tuple[str, ...]) -> bool:
    selected_names = set(selected)
    definitions: list[str] = []
    for node in _scope_nodes(tree):
        match node:
            case ast.FunctionDef(name=name) | ast.AsyncFunctionDef(name=name):
                if name in selected_names:
                    definitions.append(name)
            case ast.Name(id=name, ctx=ast.Store()) if name in selected_names:
                return True
            case _:
                continue
    return len(definitions) != len(set(definitions))


def _input_name(function: ast.FunctionDef, configured: tuple[str, ...]) -> str | None:
    arguments = {
        argument.arg
        for argument in (
            *function.args.posonlyargs,
            *function.args.args,
            *function.args.kwonlyargs,
        )
    }
    matched = arguments & set(configured)
    return next(iter(matched)) if len(matched) == 1 else None


def _matched_input(
    call: ast.Call,
    function: ast.FunctionDef,
    policy: HeuristicTotalConsumptionPolicy,
) -> tuple[str, str] | None:
    helper = _qualified_name(call.func)
    if helper not in policy.token_match_helpers:
        return None
    input_name = _input_name(function, policy.input_names)
    if input_name is None:
        return None
    input_references = [
        argument
        for argument in (*call.args, *(keyword.value for keyword in call.keywords))
        if _is_named_input(argument, input_name)
    ]
    if len(input_references) != 1:
        return None
    return input_name, helper


def _is_named_input(node: ast.expr, input_name: str) -> bool:
    match node:
        case ast.Name(id=name) if name == input_name:
            return True
        case _:
            return False


def _match_function(
    function: ast.FunctionDef, policy: HeuristicTotalConsumptionPolicy
) -> _ConsumptionSite | None:
    if function.name not in policy.function_names:
        return None
    body = function.body[1:] if ast.get_docstring(function) else function.body
    match body:
        case [ast.Return(value=ast.Call() as call) as returned]:
            evidence = _matched_input(call, function, policy)
            if evidence is not None:
                input_name, helper = evidence
                return _ConsumptionSite(
                    function.name, input_name, helper, returned.lineno
                )
        case [
            ast.Assign(targets=[ast.Name(id=capture_name)], value=ast.Call() as call),
            ast.Return(value=ast.Name(id=return_name)) as returned,
        ] if capture_name == return_name:
            evidence = _matched_input(call, function, policy)
            if evidence is not None:
                input_name, helper = evidence
                if capture_name != input_name:
                    return _ConsumptionSite(
                        function.name, input_name, helper, returned.lineno
                    )
        case _:
            pass
    return None


def heuristic_total_consumption_sites(
    source: str, policy: HeuristicTotalConsumptionPolicy
) -> list[_ConsumptionSite]:
    """Match only direct, configured token-result returns in selected functions."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    if len(list(ast.walk(tree))) > 10_000:
        return []
    if _redefined(tree, policy.function_names):
        return []
    sites = {
        site
        for function in _functions(tree.body)
        if (site := _match_function(function, policy)) is not None
    }
    return sorted(sites, key=lambda site: (site.function, site.line))


def check_heuristic_total_consumption(
    root: Path,
    paths: Iterable[Path],
    policy: HeuristicTotalConsumptionPolicy,
) -> list[Finding]:
    """Report configured token-only output as an advisory preservation risk."""
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
        source = read_python_source(path)
        for site in heuristic_total_consumption_sites(source, policy):
            findings.append(
                Finding(
                    _RULE_ID,
                    name,
                    f"Configured content-preserving function {site.function!r} returns "
                    f"only configured token-matcher results from input {site.input_name!r} "
                    f"via {site.helper!r}; review whether unmatched text is lost. The "
                    "declared output contract does not prove that losing those spans is "
                    "incorrect; explicit lossy extractors should not be configured here.",
                    site.line,
                    policy.severity,
                )
            )
    return findings
