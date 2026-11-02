"""Review path-only record exclusion under configured span ownership contracts."""

from __future__ import annotations

import ast
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from alphus.config import ProvenanceOwnershipPolicy
from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import Category, Framework, Scope, rule_tag
from alphus.support.inventory import matches_path
from alphus.support.source_text import read_python_source

_RULE_ID = rule_tag(
    Scope.PYTHON,
    Framework.NONE,
    Category.ARCHITECTURE,
    "provenance-as-ownership",
)


@dataclass(frozen=True, slots=True)
class _OwnershipSite:
    function: str
    owner_collection: str
    candidate_collection: str
    line: int


@dataclass(frozen=True, slots=True)
class _OwnerPathSet:
    collection: str
    line: int


def _attribute_parts(node: ast.expr) -> tuple[str, str] | None:
    match node:
        case ast.Name(id=name):
            return name, ""
        case ast.Attribute(value=parent, attr=attribute):
            parent_parts = _attribute_parts(parent)
            if parent_parts is None:
                return None
            root, suffix = parent_parts
            return root, f"{suffix}.{attribute}" if suffix else attribute
        case _:
            return None


def _local_nodes(root: ast.AST) -> Iterable[ast.AST]:
    yield root
    for child in ast.iter_child_nodes(root):
        match child:
            case (
                ast.FunctionDef()
                | ast.AsyncFunctionDef()
                | ast.ClassDef()
                | ast.Lambda()
            ):
                continue
            case _:
                yield from _local_nodes(child)


def _path_set_assignments(
    function: ast.FunctionDef, policy: ProvenanceOwnershipPolicy
) -> dict[str, _OwnerPathSet]:
    nodes = tuple(_local_nodes(function))
    # A nested closure may mutate a captured set and be called before the
    # comprehension. Without call-order and escape analysis, its effect is
    # unknown; abstain rather than treating the original set as intact.
    has_nested_scope = False
    for statement in function.body:
        for node in ast.walk(statement):
            match node:
                case ast.FunctionDef() | ast.AsyncFunctionDef() if node is not function:
                    has_nested_scope = True
                case _:
                    continue
    if has_nested_scope:
        return {}
    assignments: dict[str, list[_OwnerPathSet]] = {}
    for node in nodes:
        match node:
            case ast.Assign(
                targets=[ast.Name(id=target_name)],
                value=ast.SetComp(
                    elt=element,
                    generators=[
                        ast.comprehension(
                            target=ast.Name(),
                            iter=ast.Name(id=owner_name),
                            ifs=[],
                        )
                    ],
                ),
            ) if owner_name in policy.owner_collection_names:
                parts = _attribute_parts(element)
                if parts is not None and parts[1] == policy.source_path_suffix:
                    assignments.setdefault(target_name, []).append(
                        _OwnerPathSet(owner_name, node.lineno)
                    )
            case _:
                continue
    result: dict[str, _OwnerPathSet] = {}
    for name, values in assignments.items():
        store_count = 0
        load_count = 0
        declarations = False
        mutated = False
        for node in nodes:
            match node:
                case ast.Name(id=bound, ctx=ast.Store() | ast.Del()) if bound == name:
                    store_count += 1
                case ast.Name(id=bound, ctx=ast.Load()) if bound == name:
                    load_count += 1
                case ast.Global(names=names) | ast.Nonlocal(names=names) if (
                    name in names
                ):
                    declarations = True
                case ast.Call(
                    func=ast.Attribute(value=ast.Name(id=bound), attr=method)
                ) if bound == name and method in {
                    "add",
                    "clear",
                    "discard",
                    "pop",
                    "remove",
                    "update",
                }:
                    mutated = True
                case _:
                    continue
        if (
            len(values) == 1
            and store_count == 1
            and load_count == 1
            and not declarations
            and not mutated
        ):
            result[name] = values[0]
    return result


def _candidate_filter(
    node: ast.AST,
    path_sets: Mapping[str, _OwnerPathSet],
    policy: ProvenanceOwnershipPolicy,
) -> tuple[str, int] | None:
    match node:
        case ast.ListComp(
            lineno=site_line,
            elt=ast.Name(id=candidate),
            generators=[
                ast.comprehension(
                    target=ast.Name(id=candidate_target),
                    iter=ast.Name(id=candidate_collection),
                    ifs=conditions,
                )
            ],
        ) if (
            candidate_target == candidate
            and candidate_collection in policy.candidate_collection_names
        ):
            for condition in conditions:
                match condition:
                    case ast.Compare(
                        left=left,
                        ops=[ast.NotIn()],
                        comparators=[ast.Name(id=path_set_name)],
                    ) if path_set_name in path_sets:
                        parts = _attribute_parts(left)
                        if parts is None or parts != (
                            candidate,
                            policy.source_path_suffix,
                        ):
                            continue
                        owner_path_set = path_sets[path_set_name]
                        if owner_path_set.line < site_line:
                            return owner_path_set.collection, condition.lineno
                    case _:
                        continue
        case _:
            return None
    return None


def _returned_filter_line(
    function: ast.FunctionDef, candidate_filter: ast.ListComp
) -> int | None:
    """Require the filtered comprehension to reach a direct returned value."""
    body = function.body[1:] if ast.get_docstring(function) else function.body
    for index, statement in enumerate(body):
        match statement:
            case ast.Return(value=ast.ListComp() as returned) as return_statement if (
                returned is candidate_filter
            ):
                return return_statement.lineno
            case ast.Assign(
                targets=[ast.Name(id=result_name)],
                value=ast.ListComp() as assigned,
            ) if assigned is candidate_filter and index + 1 < len(body):
                match body[index + 1]:
                    case ast.Return(value=ast.Name(id=name)) as return_statement if (
                        name == result_name
                    ):
                        return return_statement.lineno
                    case _:
                        continue
            case _:
                continue
    return None


def provenance_ownership_sites(
    source: str, policy: ProvenanceOwnershipPolicy
) -> list[_OwnershipSite]:
    """Find configured path-only exclusion when policy requires exact-span ownership."""
    if policy.ownership_basis != "exact-source-span":
        return []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    if len(list(ast.walk(tree))) > 10_000:
        return []
    functions: list[ast.FunctionDef] = []
    for statement in tree.body:
        match statement:
            case ast.FunctionDef(name=name) if name in policy.function_names:
                functions.append(statement)
            case _:
                continue
    if any(
        sum(function.name == name for function in functions) != 1
        for name in policy.function_names
    ):
        return []
    sites: set[_OwnershipSite] = set()
    for function in functions:
        path_sets = _path_set_assignments(function, policy)
        for node in _local_nodes(function):
            match node:
                case ast.ListComp() as candidate_filter:
                    evidence = _candidate_filter(candidate_filter, path_sets, policy)
                    if evidence is None:
                        continue
                    return_line = _returned_filter_line(function, candidate_filter)
                    if return_line is None:
                        continue
                    owner_collection, _condition_line = evidence
                    match candidate_filter.generators:
                        case [
                            ast.comprehension(iter=ast.Name(id=candidate_collection))
                        ]:
                            sites.add(
                                _OwnershipSite(
                                    function.name,
                                    owner_collection,
                                    candidate_collection,
                                    return_line,
                                )
                            )
                        case _:
                            continue
                case _:
                    continue
    return sorted(sites, key=lambda site: (site.function, site.line))


def check_provenance_ownership(
    root: Path,
    paths: Iterable[Path],
    policy: ProvenanceOwnershipPolicy,
) -> list[Finding]:
    """Report path equality used where consumer policy requires span ownership."""
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
        for site in provenance_ownership_sites(read_python_source(path), policy):
            findings.append(
                Finding(
                    _RULE_ID,
                    name,
                    f"Configured exact-source-span ownership function {site.function!r} "
                    f"returns {site.candidate_collection} filtered using paths from "
                    f"{site.owner_collection}; path-only equality may omit distinct "
                    "same-file spans. Review whether span containment is required. "
                    "This candidate does not establish record ownership or a defect.",
                    site.line,
                    policy.severity,
                )
            )
    return findings
