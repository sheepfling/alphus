"""Review declared source-specific repair clusters in configured parsers."""

from __future__ import annotations

import ast
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from alphus.config import PatchCascadePolicy
from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import Category, Framework, Scope, rule_tag
from alphus.gates.review._module_bindings import module_binding_counts
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


def _comprehension_target_names(target: ast.expr) -> frozenset[str]:
    match target:
        case ast.Name(id=name):
            return frozenset((name,))
        case ast.Tuple(elts=items) | ast.List(elts=items):
            names: set[str] = set()
            for item in items:
                names.update(_comprehension_target_names(item))
            return frozenset(names)
        case ast.Starred(value=value):
            return _comprehension_target_names(value)
        case _:
            return frozenset()


def _helper_binding_nodes(
    root: ast.AST, shadowed: frozenset[str] = frozenset()
) -> Iterable[ast.AST]:
    """Walk local bindings and definition-time expressions, not nested bodies."""
    if isinstance(root, ast.Name) and root.id in shadowed:
        return
    yield root
    match root:
        case ast.FunctionDef() | ast.AsyncFunctionDef():
            arguments = root.args
            children = [
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
        case (
            ast.ListComp(generators=generators, elt=element)
            | ast.SetComp(generators=generators, elt=element)
            | ast.GeneratorExp(generators=generators, elt=element)
        ):
            local_names = shadowed
            for generator in generators:
                yield from _helper_binding_nodes(generator.iter, local_names)
                local_names = local_names | _comprehension_target_names(
                    generator.target
                )
                for condition in generator.ifs:
                    yield from _helper_binding_nodes(condition, local_names)
            yield from _helper_binding_nodes(element, local_names)
            return
        case ast.DictComp(generators=generators, key=key, value=value):
            local_names = shadowed
            for generator in generators:
                yield from _helper_binding_nodes(generator.iter, local_names)
                local_names = local_names | _comprehension_target_names(
                    generator.target
                )
                for condition in generator.ifs:
                    yield from _helper_binding_nodes(condition, local_names)
            yield from _helper_binding_nodes(key, local_names)
            yield from _helper_binding_nodes(value, local_names)
            return
        case ast.AnnAssign(target=ast.Name(), value=None, annotation=annotation):
            yield from _helper_binding_nodes(annotation, shadowed)
            return
        case _:
            children = list(ast.iter_child_nodes(root))
    for child in children:
        yield from _helper_binding_nodes(child, shadowed)


def _configured_calls(
    root: ast.AST,
    helpers: frozenset[str],
    shadowed: frozenset[str] = frozenset(),
) -> Iterable[str]:
    """Yield configured calls while respecting comprehension-local names."""
    if isinstance(root, ast.Name) and root.id in shadowed:
        return
    match root:
        case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef() | ast.Lambda():
            return
        case (
            ast.ListComp(generators=generators, elt=element)
            | ast.SetComp(generators=generators, elt=element)
            | ast.GeneratorExp(generators=generators, elt=element)
        ):
            local_names = shadowed
            for generator in generators:
                yield from _configured_calls(generator.iter, helpers, local_names)
                local_names = local_names | _comprehension_target_names(
                    generator.target
                )
                for condition in generator.ifs:
                    yield from _configured_calls(condition, helpers, local_names)
            yield from _configured_calls(element, helpers, local_names)
            return
        case ast.DictComp(generators=generators, key=key, value=value):
            local_names = shadowed
            for generator in generators:
                yield from _configured_calls(generator.iter, helpers, local_names)
                local_names = local_names | _comprehension_target_names(
                    generator.target
                )
                for condition in generator.ifs:
                    yield from _configured_calls(condition, helpers, local_names)
            yield from _configured_calls(key, helpers, local_names)
            yield from _configured_calls(value, helpers, local_names)
            return
        case ast.Call() as call:
            name = _call_name(call.func)
            root_name = name.split(".", maxsplit=1)[0] if name else None
            if name in helpers and root_name not in shadowed:
                yield name
        case _:
            pass
    for child in ast.iter_child_nodes(root):
        yield from _configured_calls(child, helpers, shadowed)


def _stored_helper_name(node: ast.AST, names: frozenset[str]) -> bool:
    for child in _helper_binding_nodes(node):
        match child:
            case ast.Name(id=name, ctx=ast.Store()) if name in names:
                return True
            case (
                ast.FunctionDef(name=name)
                | ast.AsyncFunctionDef(name=name)
                | ast.ClassDef(name=name)
            ) if name in names:
                return True
            case ast.Import(names=aliases):
                if any(
                    (alias.asname or alias.name.split(".", maxsplit=1)[0]) in names
                    for alias in aliases
                ):
                    return True
            case ast.ImportFrom(names=aliases):
                if any(
                    alias.name == "*" or (alias.asname or alias.name) in names
                    for alias in aliases
                ):
                    return True
            case ast.MatchAs(name=name) | ast.MatchStar(name=name) if name in names:
                return True
            case ast.MatchMapping(rest=name) if name in names:
                return True
            case _:
                continue
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
        # Reuse the shared module inventory so definition-time expressions and
        # string-valued pattern captures also make the selected binding
        # ambiguous.
        bindings = module_binding_counts(tree, (configured.function_name,))
        if len(definitions) != 1 or bindings.get(configured.function_name, 0) != 1:
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
                *((function.args.vararg,) if function.args.vararg is not None else ()),
                *((function.args.kwarg,) if function.args.kwarg is not None else ()),
            )
        }
        if parameters & helper_roots or any(
            _stored_helper_name(statement, helper_roots) for statement in function.body
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
                for call_name in _configured_calls(
                    statement, frozenset(configured.normalization_helpers)
                )
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
