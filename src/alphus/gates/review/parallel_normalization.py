"""Compare explicitly equivalent string canonicalizers for separator drift."""

from __future__ import annotations

import ast
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from alphus.config import ParallelNormalizationPair, ParallelNormalizationPolicy
from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import Category, Framework, Scope, rule_tag
from alphus.support.inventory import matches_path
from alphus.support.source_text import read_python_source

_RULE_ID = rule_tag(
    Scope.PYTHON,
    Framework.NONE,
    Category.MAINTAINABILITY,
    "parallel-normalization",
)
_MAX_AST_NODES = 10_000


@dataclass(frozen=True, slots=True)
class _NormalizationSignature:
    split_separator: str | None
    join_separator: str
    line: int


@dataclass(frozen=True, slots=True)
class _NormalizationSite:
    concept: str
    first_function: str
    second_function: str
    first_signature: _NormalizationSignature
    second_signature: _NormalizationSignature


@dataclass(frozen=True, slots=True)
class _FunctionObservation:
    name: str
    binding_count: int
    signature: _NormalizationSignature | None


@dataclass(frozen=True, slots=True)
class _LocatedObservation:
    path: str
    observation: _FunctionObservation


def _module_bindings(
    tree: ast.Module, names: frozenset[str]
) -> tuple[_FunctionObservation, ...]:
    functions: dict[str, list[ast.FunctionDef]] = {}
    bindings: dict[str, int] = {}

    def record(name: str, function: ast.FunctionDef | None = None) -> None:
        if name not in names:
            return
        bindings[name] = bindings.get(name, 0) + 1
        if function is not None:
            functions.setdefault(name, []).append(function)

    def scan(node: ast.AST) -> None:
        match node:
            case ast.FunctionDef(name=name) as function:
                record(name, function)
            case ast.AsyncFunctionDef(name=name):
                record(name)
            case ast.ClassDef(name=name):
                record(name)
                return
            case ast.Name(id=name, ctx=ast.Store()):
                record(name)
            case ast.Import(names=aliases):
                for alias in aliases:
                    record(alias.asname or alias.name.split(".", maxsplit=1)[0])
            case ast.ImportFrom(names=aliases):
                for alias in aliases:
                    record(alias.asname or alias.name)
            case _:
                for child in ast.iter_child_nodes(node):
                    scan(child)

    for statement in tree.body:
        scan(statement)
    return tuple(
        _FunctionObservation(name, bindings[name], _normalization_signature(function))
        for name, definitions in functions.items()
        for function in definitions
    )


def _normalization_signature(
    function: ast.FunctionDef,
) -> _NormalizationSignature | None:
    arguments = (*function.args.posonlyargs, *function.args.args)
    if (
        len(arguments) != 1
        or function.args.defaults
        or function.args.kwonlyargs
        or function.args.vararg
        or function.args.kwarg
    ):
        return None
    argument = arguments[0]
    match argument.annotation:
        case ast.Name(id="str"):
            pass
        case _:
            return None
    body = function.body[1:] if ast.get_docstring(function) else function.body
    match body:
        case [
            ast.Return(
                value=ast.Call(
                    func=ast.Attribute(
                        value=ast.Constant(value=str() as join_separator), attr="join"
                    ),
                    args=[
                        ast.Call(
                            func=ast.Attribute(
                                value=ast.Name(id=input_name), attr="split"
                            ),
                            args=split_arguments,
                            keywords=[],
                        )
                    ],
                    keywords=[],
                )
            ) as returned
        ] if input_name == argument.arg:
            match split_arguments:
                case []:
                    split_separator = None
                case [ast.Constant(value=str() as separator)]:
                    split_separator = separator
                case _:
                    return None
            return _NormalizationSignature(
                split_separator, join_separator, returned.lineno
            )
        case _:
            return None


def _pair_site(
    pair: ParallelNormalizationPair,
    observations: tuple[_FunctionObservation, ...],
) -> _NormalizationSite | None:
    names = (pair.first_function, pair.second_function)
    candidates = tuple(
        tuple(
            item
            for item in observations
            if item.name == name and item.binding_count == 1
        )
        for name in names
    )
    if any(len(items) != 1 for items in candidates):
        return None
    first = candidates[0][0].signature
    second = candidates[1][0].signature
    if first is None or second is None:
        return None
    if first.split_separator == second.split_separator and (
        first.join_separator == second.join_separator
    ):
        return None
    return _NormalizationSite(
        pair.concept, pair.first_function, pair.second_function, first, second
    )


def parallel_normalization_sites(
    source: str, policy: ParallelNormalizationPolicy
) -> list[_NormalizationSite]:
    """Find configured same-output pairs with direct split/join separator drift."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    if len(list(ast.walk(tree))) > _MAX_AST_NODES:
        return []
    selected_names = frozenset(
        name
        for pair in policy.pairs
        for name in (pair.first_function, pair.second_function)
    )
    observations = _module_bindings(tree, selected_names)
    sites = (
        site
        for pair in policy.pairs
        if (site := _pair_site(pair, observations)) is not None
    )
    return sorted(sites, key=lambda site: (site.concept, site.second_signature.line))


def _describe(signature: _NormalizationSignature) -> str:
    split = (
        "default whitespace splitting"
        if signature.split_separator is None
        else f"split separator {signature.split_separator!r}"
    )
    return f"{split}, join separator {signature.join_separator!r}"


def check_parallel_normalization(
    root: Path,
    paths: Iterable[Path],
    policy: ParallelNormalizationPolicy,
) -> list[Finding]:
    """Report declared same-output direct normalizers with differing separators."""
    checkout = root.resolve(strict=True)
    findings: list[Finding] = []
    observations_by_path: dict[str, tuple[_FunctionObservation, ...]] = {}
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
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        if len(list(ast.walk(tree))) > _MAX_AST_NODES:
            continue
        selected_names = frozenset(
            function_name
            for pair in policy.pairs
            for function_name in (pair.first_function, pair.second_function)
        )
        observations_by_path[name] = _module_bindings(tree, selected_names)
        for site in parallel_normalization_sites(source, policy):
            findings.append(
                Finding(
                    _RULE_ID,
                    name,
                    f"Configured normalizers {site.first_function!r} and "
                    f"{site.second_function!r} for {site.concept!r} have different "
                    f"separator signatures ({_describe(site.first_signature)} versus "
                    f"{_describe(site.second_signature)}) despite the declared "
                    "same-output contract. Review whether this delimiter difference is "
                    "intentional. The direct string pattern does not establish a defect "
                    "or equivalence outside the configured contract.",
                    site.second_signature.line,
                    policy.severity,
                )
            )
    located = tuple(
        _LocatedObservation(name, observation)
        for name, observations in observations_by_path.items()
        for observation in observations
    )
    for pair in policy.pairs:
        candidates = tuple(
            tuple(
                item
                for item in located
                if item.observation.name == function_name
                and item.observation.binding_count == 1
                and item.observation.signature is not None
            )
            for function_name in (pair.first_function, pair.second_function)
        )
        if any(len(items) != 1 for items in candidates):
            continue
        first, second = candidates[0][0], candidates[1][0]
        if first.path == second.path:
            continue
        findings.append(
            Finding(
                _RULE_ID,
                second.path,
                f"NOT EVALUATED: configured normalizers {pair.first_function!r} and "
                f"{pair.second_function!r} for {pair.concept!r} are defined in separate "
                "files, while this check compares only same-file pairs. Their declared "
                "same-output contract was not evaluated; this diagnostic makes no claim "
                "that the implementations are equal or different.",
                second.observation.signature.line
                if second.observation.signature is not None
                else None,
                policy.severity,
            )
        )
    return findings
